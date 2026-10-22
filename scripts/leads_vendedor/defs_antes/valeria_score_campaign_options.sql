-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: postgres; reloptions: security_invoker=true
-- acl: {postgres=arwdDxtm/postgres,anon=arwdDxtm/postgres,authenticated=arwdDxtm/postgres,service_role=arwdDxtm/postgres,consulta_ro=r/postgres}

create or replace view public.valeria_score_campaign_options with (security_invoker=true) as
 SELECT DISTINCT campaign_name
   FROM valeria_score_directory
  WHERE campaign_name IS NOT NULL;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.valeria_score_campaign_options to anon;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.valeria_score_campaign_options to authenticated;
grant SELECT on public.valeria_score_campaign_options to consulta_ro;
grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on public.valeria_score_campaign_options to service_role;
