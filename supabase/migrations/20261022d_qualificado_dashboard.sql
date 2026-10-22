-- supabase/migrations/20261022d_qualificado_dashboard.sql
--
-- Cartão b67f1c6b — spec docs/superpowers/specs/2026-10-22-crm-leads-vendedor-design.md (seção 5, D1, D2).
-- Este arquivo é só do dashboard (Task C). O score/diretório está na 20261022d1 (Task D).
--
--   1. dashboard_kpis — cópia LITERAL da versão vigente (20261019_repasse_sla.sql, cartão
--      7b143561; conferida igual a pg_get_functiondef de produção em 22/10/2026). Muda só:
--        * leads_new / leads_prev = leads distintos cuja 1ª `entrada` cai no período, sem
--          importados (origem_cadastro bling_import/reativacao_import) e sem ja_era_cliente (D1);
--        * contacts_new (coluna nova, no fim) = a contagem antiga por leads.created_at;
--        * qualification_rate = leads com o evento `qualificado` no período ÷ leads atendidos
--          no período (mensagem do lead respondida por sent_by agent ou valeria_botoes) (D2).
--      SLA, handoffs, custos e o resto: byte a byte iguais. O tipo de retorno muda, então é
--      DROP + CREATE (com os grants de hoje: PUBLIC, anon, authenticated, service_role).
--   2. dashboard_funnel_conversion — o cohort vira o conjunto D1 (mesma regra de leads_new).
--      Mesma assinatura e mesmas colunas: CREATE OR REPLACE (grants reaplicados).
--
-- Depende da 20261022c (leads.origem_cadastro) e do evento `qualificado` (contrato b67f1c6b).
-- NAO E APLICADA PELO DEPLOY. Aplicar à mão ANTES do push. Reexecutar é seguro.
-- Depois: recarregar o PostgREST com SIGUSR1 (NOTIFY é ignorado na VPS).
-- Definições anteriores: scripts/leads_vendedor/defs_antes/dashboard_*.sql (rollback).

BEGIN;
SET LOCAL lock_timeout = '5s';

-- ── 1. dashboard_kpis ──────────────────────────────────────────────────────────────
DROP FUNCTION IF EXISTS public.dashboard_kpis(date, date, text);

CREATE FUNCTION public.dashboard_kpis(
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
  cost_per_atendimento_usd  numeric,
  contacts_new              bigint
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
  -- b67f1c6b (D1): lead de marketing = 1ª `entrada` do lead, sem importados e sem quem já
  -- era cliente. Reentrada não conta de novo: vale só a 1ª entrada de cada lead.
  first_entrada AS (
    SELECT e.lead_id, min(e.occurred_at) AS em
    FROM lead_events e
    JOIN leads l ON l.id = e.lead_id
    WHERE e.event_type = 'entrada'
      AND l.origem_cadastro NOT IN ('bling_import','reativacao_import')
      AND COALESCE(l.ja_era_cliente, false) = false
    GROUP BY e.lead_id
  ),
  new_leads AS (
    SELECT count(*) AS n FROM first_entrada, bounds
    WHERE em >= bounds.s AND em < bounds.e
  ),
  prev_leads AS (
    SELECT count(*) AS n FROM first_entrada, prev_bounds
    WHERE em >= prev_bounds.ps AND em < prev_bounds.pe
  ),
  -- "Todos os contatos": a contagem antiga de leads_new (leads.created_at no período)
  new_contacts AS (
    SELECT count(*) AS n FROM leads, bounds
    WHERE created_at >= bounds.s AND created_at < bounds.e
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
  -- b67f1c6b (D2): leads distintos com o evento `qualificado` no período ...
  qualified AS (
    SELECT DISTINCT e.lead_id
    FROM lead_events e, bounds
    WHERE e.event_type = 'qualificado'
      AND e.occurred_at >= bounds.s AND e.occurred_at < bounds.e
  ),
  -- ... ÷ leads atendidos no período: mensagem do lead respondida pela IA ou pelo bot de botões
  attended_leads AS (
    SELECT DISTINCT c.lead_id
    FROM messages m
    JOIN conversations c ON c.id = m.conversation_id, bounds
    WHERE m.created_at >= bounds.s AND m.created_at < bounds.e
      AND c.lead_id IS NOT NULL
    GROUP BY m.conversation_id, c.lead_id
    HAVING bool_or(m.role = 'user')
       AND bool_or(m.role = 'assistant' AND m.sent_by IN ('agent','valeria_botoes'))
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
    CASE WHEN (SELECT count(*) FROM attended_leads) > 0
         THEN round((SELECT count(*) FROM qualified)::numeric
                    / (SELECT count(*) FROM attended_leads), 4)
         ELSE 0 END,
    (SELECT round((percentile_cont(0.5) WITHIN GROUP (ORDER BY busy_secs) / 60.0)::numeric, 1) FROM sla),
    (SELECT round((percentile_cont(0.95) WITHIN GROUP (ORDER BY busy_secs) / 60.0)::numeric, 1) FROM sla),
    (SELECT count(*) FROM sla),
    CASE WHEN (SELECT count(*) FROM handoff_msgs) > 0
         THEN round((SELECT total FROM ia_cost) / (SELECT count(*) FROM handoff_msgs), 4)
         ELSE NULL END,
    CASE WHEN (SELECT atendidos FROM ia_cost) > 0
         THEN round((SELECT resp_cost FROM ia_cost) / (SELECT atendidos FROM ia_cost), 4)
         ELSE NULL END,
    (SELECT n FROM new_contacts);
$$;

-- ── 2. dashboard_funnel_conversion (cohort = D1) ───────────────────────────────────
CREATE OR REPLACE FUNCTION public.dashboard_funnel_conversion(
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
  -- b67f1c6b (D1): mesmo conjunto de leads_new em dashboard_kpis
  cohort AS (
    SELECT e.lead_id AS id
    FROM lead_events e
    JOIN leads l ON l.id = e.lead_id, bounds
    WHERE e.event_type = 'entrada'
      AND l.origem_cadastro NOT IN ('bling_import','reativacao_import')
      AND COALESCE(l.ja_era_cliente, false) = false
    GROUP BY e.lead_id, bounds.s, bounds.e
    HAVING min(e.occurred_at) >= bounds.s AND min(e.occurred_at) < bounds.e
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

-- ── 3. Grants (os de hoje; consulta_ro quando existir) ─────────────────────────────
GRANT EXECUTE ON FUNCTION public.dashboard_kpis(date, date, text) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.dashboard_funnel_conversion(date, date, text) TO anon, authenticated, service_role;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'consulta_ro') THEN
    GRANT EXECUTE ON FUNCTION public.dashboard_kpis(date, date, text) TO consulta_ro;
    GRANT EXECUTE ON FUNCTION public.dashboard_funnel_conversion(date, date, text) TO consulta_ro;
  END IF;
END $$;

COMMIT;
