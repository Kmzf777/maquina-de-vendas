-- supabase/migrations/20261019_repasse_sla.sql
--
-- Cartão 7b143561 — spec docs/superpowers/specs/2026-10-19-repasse-sla-closer-design.md (B5/B6).
--
--   1. fn_minutos_uteis_vendedor  — minutos dentro do horário do vendedor (sla_seller_config;
--      padrão 10h-16h seg-sex; dia em sla_overrides não conta). Mesma conta de
--      analytics.vw_resposta_closer, agora versionada no ValerIA.
--   2. trg_leads_first_response   — leads.first_response_at = 1ª mensagem sent_by='seller'
--      (sem reação) depois do 1º repasse, em QUALQUER conversa do lead (D4/D6).
--   3. vw_repasse_resposta        — uma linha por lead repassado (1º repasse, vendedor,
--      1ª resposta, minutos úteis).
--   4. dashboard_kpis             — handoffs = leads com 1º repasse no período (D3); SLA lido da
--      view. Mesma assinatura e mesmas colunas de saída; o resto da função NÃO muda.
--
-- O 1º repasse vem da mensagem-marcador '[encaminhar\_humano] Lead encaminhado%' (min created_at
-- por lead), não de lead_events: funciona desde o deploy, antes do backfill R1, e bate com
-- analytics.vw_repasses. O evento 'repasse' só fornece o vendedor_id (fallback leads.assigned_to).
--
-- NAO E APLICADA PELO DEPLOY. Aplicar à mão ANTES do push, pelo psql do supabase_db.
-- Só aditiva + CREATE OR REPLACE de dashboard_kpis. Reexecutar é seguro.
-- Depois: recarregar o cache do PostgREST com SIGUSR1 (o NOTIFY é ignorado nesta VPS).
-- Desfazer: scripts/repasse_sla/rollback_migration.sql.

BEGIN;
SET LOCAL lock_timeout = '5s';

-- ── 1. Minutos úteis do vendedor ────────────────────────────────────────────────────
-- Agregado sem GROUP BY: sempre devolve uma linha (0 quando nenhum dia conta, NULL nunca).
-- dow: 0=domingo .. 6=sábado (convenção de sla_seller_config.active_weekdays).
-- sla_overrides com user_id NULL = folga de TODOS (feriado), como use-overdue-leads.ts e o
-- watchdog. DIFERE de analytics.vw_resposta_closer, que só usa a folga do próprio vendedor
-- (em 19/10/2026 sla_overrides está vazia, então os números não mudam).
CREATE OR REPLACE FUNCTION public.fn_minutos_uteis_vendedor(p_user uuid, p_de timestamptz, p_ate timestamptz)
RETURNS numeric
LANGUAGE sql STABLE
SET search_path = public
AS $$
  WITH cfg AS (
    SELECT COALESCE(c.window_start_minute, 600)            AS ini,
           COALESCE(c.window_end_minute, 960)              AS fim,
           COALESCE(c.active_weekdays, ARRAY[1,2,3,4,5])   AS dias
      FROM (SELECT 1) um
      LEFT JOIN LATERAL (
        SELECT s.window_start_minute, s.window_end_minute, s.active_weekdays
          FROM sla_seller_config s
         WHERE s.user_id = p_user AND s.active
         ORDER BY s.updated_at DESC NULLS LAST
         LIMIT 1) c ON true
  ), t AS (
    SELECT (p_de  AT TIME ZONE 'America/Sao_Paulo') AS t0,
           (p_ate AT TIME ZONE 'America/Sao_Paulo') AS t1
  )
  SELECT round(COALESCE(sum(GREATEST(0::numeric, EXTRACT(epoch FROM (
             LEAST(t.t1, d.d + make_interval(mins => cfg.fim))
           - GREATEST(t.t0, d.d + make_interval(mins => cfg.ini)))))), 0) / 60.0, 1)
    FROM cfg, t,
         generate_series(date_trunc('day', t.t0), date_trunc('day', t.t1), interval '1 day') d(d)
   WHERE p_ate > p_de
     AND EXTRACT(dow FROM d.d)::int = ANY (cfg.dias)
     AND NOT EXISTS (SELECT 1 FROM sla_overrides o
                      WHERE (o.user_id = p_user OR o.user_id IS NULL)
                        AND d.d::date BETWEEN o.start_date AND o.end_date);
$$;

-- ── 2. leads.first_response_at (D4/D6) ──────────────────────────────────────────────
-- SECURITY DEFINER com search_path fixo (padrão de 20261006b): quem grava a mensagem pode ser
-- `authenticated`. Nunca derruba o insert: falha vira WARNING.
CREATE OR REPLACE FUNCTION public.fn_leads_first_response()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NEW.sent_by = 'seller' AND COALESCE(NEW.message_type, '') <> 'reaction' AND NEW.lead_id IS NOT NULL THEN
    BEGIN
      UPDATE leads l SET first_response_at = NEW.created_at
       WHERE l.id = NEW.lead_id
         AND l.first_response_at IS NULL
         AND EXISTS (SELECT 1 FROM messages h
                      WHERE h.lead_id = NEW.lead_id
                        AND h.role = 'system'
                        AND h.content LIKE '[encaminhar\_humano] Lead encaminhado%'
                        AND h.created_at <= NEW.created_at);
    EXCEPTION WHEN others THEN
      RAISE WARNING 'fn_leads_first_response: lead %: %', NEW.lead_id, SQLERRM;
    END;
  END IF;
  RETURN NULL;
END
$$;
-- Função de trigger não é RPC.
REVOKE EXECUTE ON FUNCTION public.fn_leads_first_response() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_leads_first_response ON public.messages;
CREATE TRIGGER trg_leads_first_response
  AFTER INSERT ON public.messages
  FOR EACH ROW EXECUTE FUNCTION public.fn_leads_first_response();

-- ── 3. Uma linha por lead repassado ────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.vw_repasse_resposta WITH (security_invoker = true) AS
WITH r AS (
  SELECT h.lead_id, min(h.created_at) AS repasse_em
    FROM messages h
   WHERE h.role = 'system'
     AND h.content LIKE '[encaminhar\_humano] Lead encaminhado%'
     AND h.lead_id IS NOT NULL
   GROUP BY h.lead_id
), x AS (
  SELECT r.lead_id,
         r.repasse_em,
         COALESCE(
           (SELECT (e.metadata->>'vendedor_id')::uuid
              FROM lead_events e
             WHERE e.lead_id = r.lead_id
               AND e.event_type = 'repasse'
               AND e.metadata->>'vendedor_id' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
             ORDER BY e.occurred_at
             LIMIT 1),
           l.assigned_to) AS vendedor_id,
         l.first_response_at AS primeira_resposta_em
    FROM r
    JOIN leads l ON l.id = r.lead_id
)
SELECT x.lead_id,
       x.repasse_em,
       x.vendedor_id,
       x.primeira_resposta_em,
       CASE WHEN x.primeira_resposta_em IS NOT NULL
            THEN fn_minutos_uteis_vendedor(x.vendedor_id, x.repasse_em, x.primeira_resposta_em) END AS minutos_uteis,
       CASE WHEN x.primeira_resposta_em IS NULL
            THEN fn_minutos_uteis_vendedor(x.vendedor_id, x.repasse_em, now()) END AS minutos_uteis_em_aberto,
       (x.primeira_resposta_em IS NOT NULL) AS respondeu
  FROM x;

COMMENT ON VIEW public.vw_repasse_resposta IS
  'Cartão 7b143561: 1º repasse (mensagem-marcador) por lead, vendedor (evento repasse ou assigned_to), '
  '1ª resposta seller em qualquer conversa (leads.first_response_at) e minutos no horário do vendedor. '
  'Respostas digitadas no celular do vendedor não são gravadas.';

-- ── 4. dashboard_kpis (cópia de 20260712_dashboard_rpcs.sql; mudam handoff_msgs e sla) ─
-- CAVEAT do SLA humano: mede a 1ª resposta do vendedor DENTRO do CRM (sent_by='seller', sem
-- reação) em QUALQUER conversa do lead, depois do 1º repasse, no horário do vendedor
-- (vw_repasse_resposta). Respostas digitadas no celular do vendedor (fora do CRM) continuam
-- invisíveis — o card mostra as amostras usadas (sla_samples).
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
  -- D3: um handoff por lead, no instante do 1º repasse, quando ele cai no período
  handoff_msgs AS (
    SELECT r.lead_id, r.repasse_em AS created_at
    FROM vw_repasse_resposta r, bounds
    WHERE r.repasse_em >= bounds.s AND r.repasse_em < bounds.e
  ),
  qualified AS (
    SELECT DISTINCT m.conversation_id
    FROM messages m, bounds
    WHERE m.role = 'system'
      AND m.content LIKE '[qualificar\_lead]%'
      AND m.created_at >= bounds.s AND m.created_at < bounds.e
  ),
  -- D4: 1ª resposta seller em qualquer conversa do lead, minutos no horário do vendedor
  sla AS (
    SELECT r.minutos_uteis * 60.0 AS busy_secs
    FROM vw_repasse_resposta r, bounds
    WHERE r.repasse_em >= bounds.s AND r.repasse_em < bounds.e
      AND r.respondeu
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

-- ── 5. Grants (o default ACL não cobre objeto novo para consulta_ro) ──────────────
GRANT EXECUTE ON FUNCTION public.fn_minutos_uteis_vendedor(uuid, timestamptz, timestamptz) TO authenticated, service_role;
GRANT SELECT ON public.vw_repasse_resposta TO authenticated, service_role;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'consulta_ro') THEN
    GRANT EXECUTE ON FUNCTION public.fn_minutos_uteis_vendedor(uuid, timestamptz, timestamptz) TO consulta_ro;
    GRANT SELECT ON public.vw_repasse_resposta TO consulta_ro;
  END IF;
END $$;

COMMIT;
