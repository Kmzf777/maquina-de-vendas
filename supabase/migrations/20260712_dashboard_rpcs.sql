-- Dashboard principal (/dashboard) — RPCs agregadoras (spec 2026-07-12-fix-main-dashboard v2).
-- Substituem os fetchs de tabela inteira do frontend (teto max-rows=1000 + colunas mortas).
-- Padrão das stats RPCs (20260711): LANGUAGE sql STABLE, SECURITY DEFINER, search_path fixo.
--
-- Fatos de dados validados em prod (12/07):
--   marcador de handoff  = messages.role='system' AND content LIKE '[encaminhar\_humano] Lead encaminhado%'
--   marcador qualificacao = '[qualificar\_lead]%'
--   template frio        = broadcasts.template_name LIKE 'utilidade\_%' (ex.: utilidade_22_04_2026_16_40)
--   deals ganhos         = deals.stage_id -> pipeline_stages.key = 'fechado_ganho' (NUNCA deals.stage, coluna morta)
--   sent_by REAIS        = IA:'agent' | vendedor:'seller' | 'broadcast'/'followup'/'handoff'/'bridge'/'recovery'
--                          (NAO existem 'ai' nem 'human' em messages.sent_by — validado por GROUP BY em prod)
--
-- CAVEAT do SLA humano: mede a resposta do vendedor DENTRO do CRM (sent_by='seller' na
-- mesma conversa). Handoffs atendidos pelo numero pessoal do Joao (fora do CRM) nao sao
-- observaveis neste banco — o card mostra as amostras usadas (sla_samples).

-- Alinhamento de schema homolog<-prod (colunas que existem em prod desde o fluxo de
-- entrega do broadcast mas nunca chegaram ao homolog — no-op em prod via IF NOT EXISTS;
-- necessarias para as RPCs abaixo compilarem em ambos os ambientes):
ALTER TABLE broadcast_leads ADD COLUMN IF NOT EXISTS delivered_at timestamptz;
ALTER TABLE broadcast_leads ADD COLUMN IF NOT EXISTS wamid text;

-- ---------------------------------------------------------------------------
-- Helper: segundos DENTRO do horario comercial (seg-sex 10h-16h America/Sao_Paulo)
-- entre dois timestamps. Feriados NAO sao tratados (sem tabela de feriados — limitacao
-- documentada no tooltip do card). STABLE (nao IMMUTABLE: depende do tzdata).
-- Semantica pinada em teste: handoff sexta 20h respondido segunda 10h05 -> 300s.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION dashboard_business_seconds(t_start timestamptz, t_end timestamptz)
RETURNS numeric
LANGUAGE sql STABLE
SET search_path = public
AS $$
  SELECT COALESCE(SUM(GREATEST(0, EXTRACT(EPOCH FROM (
           LEAST((t_end AT TIME ZONE 'America/Sao_Paulo'), d + interval '16 hours')
         - GREATEST((t_start AT TIME ZONE 'America/Sao_Paulo'), d + interval '10 hours')
         )))), 0)
  FROM generate_series(
         date_trunc('day', t_start AT TIME ZONE 'America/Sao_Paulo'),
         date_trunc('day', t_end   AT TIME ZONE 'America/Sao_Paulo'),
         interval '1 day') AS d
  WHERE t_end > t_start
    AND EXTRACT(ISODOW FROM d) BETWEEN 1 AND 5;
$$;

-- ---------------------------------------------------------------------------
-- KPIs dos 8 cards. Janela [p_start, p_end) em dias LOCAIS (p_tz). Campos de
-- snapshot (active_*) ignoram a janela por definicao (estado AGORA, msgs 24h).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION dashboard_kpis(
  p_start date,
  p_end   date,
  p_tz    text DEFAULT 'America/Sao_Paulo'
)
RETURNS TABLE (
  leads_new                 bigint,
  leads_prev                bigint,
  active_with_ai            bigint,
  active_awaiting_lead      bigint,
  conversations_attended    bigint,
  handoffs                  bigint,
  qualification_rate        numeric,
  sla_median_minutes        numeric,
  sla_p95_minutes           numeric,
  sla_samples               bigint,
  cost_per_handoff_usd      numeric,
  cost_per_atendimento_usd  numeric
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
  WITH bounds AS (
    SELECT (p_start::timestamp AT TIME ZONE p_tz) AS s,
           (p_end::timestamp   AT TIME ZONE p_tz) AS e
  ),
  prev_bounds AS (
    SELECT s - (e - s) AS ps, s AS pe FROM bounds
  ),
  new_leads AS (
    SELECT count(*) AS n FROM leads, bounds
    WHERE created_at >= bounds.s AND created_at < bounds.e
  ),
  prev_leads AS (
    SELECT count(*) AS n FROM leads, prev_bounds
    WHERE created_at >= prev_bounds.ps AND created_at < prev_bounds.pe
  ),
  -- snapshot: leads em conversa ativa com a IA (msg do cliente nas ultimas 24h)
  ai_active AS (
    SELECT l.id,
           (SELECT m.role FROM messages m
             JOIN conversations c2 ON c2.id = m.conversation_id
            WHERE c2.lead_id = l.id AND m.role IN ('user','assistant')
            ORDER BY m.created_at DESC LIMIT 1) AS last_role
    FROM leads l
    WHERE l.ai_enabled = true
      AND COALESCE(l.opt_out, false) = false
      AND COALESCE(l.stage, '') <> 'perdido'
      AND EXISTS (
        SELECT 1 FROM conversations c
        JOIN messages m ON m.conversation_id = c.id
        WHERE c.lead_id = l.id AND m.role = 'user'
          AND m.created_at > now() - interval '24 hours'
      )
  ),
  attended AS (
    SELECT m.conversation_id
    FROM messages m, bounds
    WHERE m.created_at >= bounds.s AND m.created_at < bounds.e
    GROUP BY m.conversation_id
    HAVING bool_or(m.role = 'user')
       AND bool_or(m.role = 'assistant' AND m.sent_by = 'agent')
  ),
  handoff_msgs AS (
    SELECT m.id, m.conversation_id, m.created_at
    FROM messages m, bounds
    WHERE m.role = 'system'
      AND m.content LIKE '[encaminhar\_humano] Lead encaminhado%'
      AND m.created_at >= bounds.s AND m.created_at < bounds.e
  ),
  qualified AS (
    SELECT DISTINCT m.conversation_id
    FROM messages m, bounds
    WHERE m.role = 'system'
      AND m.content LIKE '[qualificar\_lead]%'
      AND m.created_at >= bounds.s AND m.created_at < bounds.e
  ),
  sla AS (
    SELECT dashboard_business_seconds(h.created_at, r.resp_at) AS busy_secs
    FROM handoff_msgs h
    CROSS JOIN LATERAL (
      SELECT min(m.created_at) AS resp_at
      FROM messages m
      WHERE m.conversation_id = h.conversation_id
        AND m.sent_by = 'seller'
        AND m.created_at > h.created_at
    ) r
    WHERE r.resp_at IS NOT NULL
  ),
  ia_cost AS (
    SELECT COALESCE(sum(total_cost), 0) AS total,
           COALESCE(sum(total_cost) FILTER (WHERE call_type LIKE 'response%'), 0) AS resp_cost,
           count(DISTINCT lead_id) FILTER (WHERE call_type LIKE 'response%') AS atendidos
    FROM token_usage, bounds
    WHERE created_at >= bounds.s AND created_at < bounds.e
  )
  SELECT
    (SELECT n FROM new_leads),
    (SELECT n FROM prev_leads),
    (SELECT count(*) FROM ai_active),
    (SELECT count(*) FROM ai_active WHERE last_role = 'assistant'),
    (SELECT count(*) FROM attended),
    (SELECT count(*) FROM handoff_msgs),
    CASE WHEN (SELECT count(*) FROM attended) > 0
         THEN round((SELECT count(*) FROM qualified)::numeric
                    / (SELECT count(*) FROM attended), 4)
         ELSE 0 END,
    (SELECT round((percentile_cont(0.5) WITHIN GROUP (ORDER BY busy_secs) / 60.0)::numeric, 1) FROM sla),
    (SELECT round((percentile_cont(0.95) WITHIN GROUP (ORDER BY busy_secs) / 60.0)::numeric, 1) FROM sla),
    (SELECT count(*) FROM sla),
    CASE WHEN (SELECT count(*) FROM handoff_msgs) > 0
         THEN round((SELECT total FROM ia_cost) / (SELECT count(*) FROM handoff_msgs), 4)
         ELSE NULL END,
    CASE WHEN (SELECT atendidos FROM ia_cost) > 0
         THEN round((SELECT resp_cost FROM ia_cost) / (SELECT atendidos FROM ia_cost), 4)
         ELSE NULL END;
$$;

-- ---------------------------------------------------------------------------
-- Conversao fim-a-fim: coorte de leads CRIADOS na janela -> handoff (qualquer
-- momento) -> deal ganho (stage_id -> pipeline_stages.key='fechado_ganho').
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION dashboard_funnel_conversion(
  p_start date,
  p_end   date,
  p_tz    text DEFAULT 'America/Sao_Paulo'
)
RETURNS TABLE (leads_total bigint, with_handoff bigint, won bigint)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
  WITH bounds AS (
    SELECT (p_start::timestamp AT TIME ZONE p_tz) AS s,
           (p_end::timestamp   AT TIME ZONE p_tz) AS e
  ),
  cohort AS (
    SELECT l.id FROM leads l, bounds
    WHERE l.created_at >= bounds.s AND l.created_at < bounds.e
  )
  SELECT
    (SELECT count(*) FROM cohort),
    (SELECT count(*) FROM cohort co WHERE EXISTS (
       SELECT 1 FROM conversations c
       JOIN messages m ON m.conversation_id = c.id
       WHERE c.lead_id = co.id AND m.role = 'system'
         AND m.content LIKE '[encaminhar\_humano] Lead encaminhado%')),
    (SELECT count(*) FROM cohort co WHERE EXISTS (
       SELECT 1 FROM deals d
       JOIN pipeline_stages ps ON ps.id = d.stage_id
       WHERE d.lead_id = co.id AND ps.key = 'fechado_ganho'));
$$;

-- ---------------------------------------------------------------------------
-- Outbound frio: funil enviado -> entregue -> respondeu dos disparos com
-- template utilidade_* (restricao do usuario), janela por sent_at.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION dashboard_outbound_frio(
  p_start date,
  p_end   date,
  p_tz    text DEFAULT 'America/Sao_Paulo'
)
RETURNS TABLE (sent bigint, delivered bigint, replied bigint)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
  WITH bounds AS (
    SELECT (p_start::timestamp AT TIME ZONE p_tz) AS s,
           (p_end::timestamp   AT TIME ZONE p_tz) AS e
  )
  SELECT count(bl.sent_at),
         count(bl.delivered_at),
         count(bl.first_replied_at)
  FROM broadcast_leads bl
  JOIN broadcasts b ON b.id = bl.broadcast_id, bounds
  WHERE b.template_name LIKE 'utilidade\_%'
    AND bl.sent_at >= bounds.s AND bl.sent_at < bounds.e;
$$;

-- ---------------------------------------------------------------------------
-- Esteira de follow-up: hoje local (agendados x executados), pendentes vencidos,
-- quebra por job_type e retornos agendados (ai_scheduled_return) pendentes.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION dashboard_followups(
  p_tz text DEFAULT 'America/Sao_Paulo'
)
RETURNS TABLE (
  scheduled_today bigint,
  sent_today      bigint,
  overdue_pending bigint,
  by_type         jsonb,
  returns_pending bigint,
  next_return_at  timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
  WITH today AS (
    SELECT (date_trunc('day', now() AT TIME ZONE p_tz)::timestamp AT TIME ZONE p_tz) AS s,
           ((date_trunc('day', now() AT TIME ZONE p_tz) + interval '1 day')::timestamp AT TIME ZONE p_tz) AS e
  ),
  base AS (
    SELECT job_type,
           count(*) FILTER (WHERE fire_at >= today.s AND fire_at < today.e) AS scheduled,
           count(*) FILTER (WHERE sent_at >= today.s AND sent_at < today.e AND status = 'sent') AS sent
    FROM follow_up_jobs, today
    GROUP BY job_type
  )
  SELECT
    (SELECT COALESCE(sum(scheduled), 0) FROM base),
    (SELECT COALESCE(sum(sent), 0) FROM base),
    (SELECT count(*) FROM follow_up_jobs WHERE status = 'pending' AND fire_at < now()),
    (SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'job_type', job_type, 'scheduled', scheduled, 'sent', sent)
        ORDER BY job_type) FILTER (WHERE scheduled > 0 OR sent > 0), '[]'::jsonb) FROM base),
    (SELECT count(*) FROM follow_up_jobs
      WHERE job_type = 'ai_scheduled_return' AND status = 'pending'),
    (SELECT min(fire_at) FROM follow_up_jobs
      WHERE job_type = 'ai_scheduled_return' AND status = 'pending');
$$;
