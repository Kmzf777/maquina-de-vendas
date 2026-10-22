-- supabase/migrations/20261022d1_score_directory.sql
--
-- Cartão b67f1c6b — spec docs/superpowers/specs/2026-10-22-crm-leads-vendedor-design.md, item 4 (B4).
--
-- valeria_score_directory deixa de filtrar l.stage = 'atacado' e passa a mostrar todo lead que tem
-- linha em lead_qualification_scores (o score já só é gravado para lead B2B: segmento atacado /
-- private_label ou fn_lead_b2b). Antes era LEFT JOIN + stage='atacado' (lead atacado sem score
-- aparecia vazio; lead pending com score sumia).
--
-- Mesmas colunas, na mesma ordem e com os mesmos tipos: CREATE OR REPLACE mantém os grants e a
-- dependente valeria_score_campaign_options.
--
-- NÃO É APLICADA PELO DEPLOY. Aplicar à mão pelo psql do supabase_db. Reexecutar é seguro.
-- Depois: recarregar o cache do PostgREST com SIGUSR1 (o NOTIFY é ignorado nesta VPS).
-- Desfazer: scripts/leads_vendedor/defs_antes/valeria_score_directory.sql (definição vigente em 22/10).

BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE VIEW public.valeria_score_directory WITH (security_invoker = true) AS
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
FROM public.lead_qualification_scores s
JOIN public.leads l ON l.id = s.lead_id
LEFT JOIN public.meta_ad_campaigns mac ON mac.ad_id = l.meta_ad_id
LEFT JOIN LATERAL (
    SELECT max(conversations.last_msg_at) AS last_interaction_at
    FROM public.conversations
    WHERE conversations.lead_id = l.id
) c ON true;

COMMENT ON VIEW public.valeria_score_directory IS
  'Diretório do score da Valeria: um lead por linha, todo lead com linha em lead_qualification_scores (sem filtro de stage desde b67f1c6b).';

COMMIT;
