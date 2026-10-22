CREATE OR REPLACE FUNCTION public.dashboard_funnel_conversion(p_start date, p_end date, p_tz text DEFAULT 'America/Sao_Paulo'::text)
 RETURNS TABLE(leads_total bigint, with_handoff bigint, won bigint)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
$function$
;
