-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: postgres; reloptions: security_invoker=true
-- acl: {postgres=arwdDxtm/postgres,anon=arwdDxtm/postgres,authenticated=arwdDxtm/postgres,service_role=arwdDxtm/postgres,consulta_ro=r/postgres}

create or replace view public.valeria_score_directory with (security_invoker=true) as
 SELECT l.id AS lead_id,
    l.name,
    l.phone,
    l.company,
    l.stage,
    l.status,
    c.last_interaction_at,
    l.traffic_type,
    l.utm_campaign,
    l.meta_ad_id,
    COALESCE(NULLIF(l.utm_campaign, ''::text), mac.campaign_name) AS campaign_name,
    s.segment,
    s.monthly_volume_kg,
    s.supplier_reason,
    s.purchase_timing,
    s.purchase_intent,
    s.evidence,
    s.normal_score,
    s.final_score,
    s.priority,
        CASE s.priority
            WHEN 'maximum'::text THEN 4
            WHEN 'high'::text THEN 3
            WHEN 'moderate'::text THEN 2
            WHEN 'low'::text THEN 1
            ELSE 0
        END AS priority_rank,
    s.is_provisional,
    s.updated_at AS score_updated_at
   FROM leads l
     LEFT JOIN lead_qualification_scores s ON s.lead_id = l.id
     LEFT JOIN meta_ad_campaigns mac ON mac.ad_id = l.meta_ad_id
     LEFT JOIN LATERAL ( SELECT max(conversations.last_msg_at) AS last_interaction_at
           FROM conversations
          WHERE conversations.lead_id = l.id) c ON true
  WHERE l.stage = 'atacado'::text;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.valeria_score_directory to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.valeria_score_directory to authenticated;
grant SELECT on public.valeria_score_directory to consulta_ro;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.valeria_score_directory to service_role;
