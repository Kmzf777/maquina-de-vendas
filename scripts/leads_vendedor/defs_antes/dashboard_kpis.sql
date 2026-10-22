CREATE OR REPLACE FUNCTION public.dashboard_kpis(p_start date, p_end date, p_tz text DEFAULT 'America/Sao_Paulo'::text)
 RETURNS TABLE(leads_new bigint, leads_prev bigint, active_with_ai bigint, active_awaiting_lead bigint, conversations_attended bigint, handoffs bigint, qualification_rate numeric, sla_median_minutes numeric, sla_p95_minutes numeric, sla_samples bigint, cost_per_handoff_usd numeric, cost_per_atendimento_usd numeric)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
$function$
;
