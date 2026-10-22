-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: supabase_admin; reloptions: security_invoker=true
-- acl: {supabase_admin=arwdDxtm/supabase_admin,consulta_ro=r/supabase_admin}

create or replace view analytics.dim_lead with (security_invoker=true) as
 WITH entrada AS (
         SELECT DISTINCT ON (e.lead_id) e.lead_id,
            e.occurred_at,
            e.metadata,
            e.dedupe_key
           FROM lead_events e
          WHERE e.event_type = 'entrada'::text AND e.lead_id IS NOT NULL
          ORDER BY e.lead_id, e.occurred_at, e.id
        ), camp AS (
         SELECT DISTINCT ON (a_1.platform, a_1.campaign_id) a_1.platform,
            a_1.campaign_id,
            a_1.campaign_name
           FROM ad_spend a_1
          ORDER BY a_1.platform, a_1.campaign_id, a_1.date DESC
        ), google AS (
         SELECT c_1.campaign_id,
            c_1.campaign_name,
            lower(TRIM(BOTH FROM c_1.campaign_name)) AS nome_lower,
            ARRAY( SELECT t.t
                   FROM regexp_split_to_table(lower(translate(c_1.campaign_name, 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇáàâãäéèêëíìîïóòôõöúùûüç'::text, 'AAAAAEEEEIIIIOOOOOUUUUCaaaaaeeeeiiiiooooouuuuc'::text)), '[^a-z0-9]+'::text) t(t)
                  WHERE t.t <> ''::text AND t.t !~ '^[0-9]+$'::text AND t.t <> 'sitelink'::text) AS tok
           FROM camp c_1
          WHERE c_1.platform = 'google'::text
        ), utm_tok AS (
         SELECT u.utm_campaign,
            u.utm_medium,
            ARRAY( SELECT t.t
                   FROM regexp_split_to_table(lower(translate(COALESCE(u.utm_campaign, ''::text), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇáàâãäéèêëíìîïóòôõöúùûüç'::text, 'AAAAAEEEEIIIIOOOOOUUUUCaaaaaeeeeiiiiooooouuuuc'::text)), '[^a-z0-9]+'::text) t(t)
                  WHERE t.t <> ''::text AND t.t !~ '^[0-9]+$'::text AND t.t <> 'sitelink'::text) AS tok,
            ARRAY( SELECT t.t
                   FROM regexp_split_to_table(lower(translate(COALESCE(u.utm_medium, ''::text), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇáàâãäéèêëíìîïóòôõöúùûüç'::text, 'AAAAAEEEEIIIIOOOOOUUUUCaaaaaeeeeiiiiooooouuuuc'::text)), '[^a-z0-9]+'::text) t(t)
                  WHERE t.t <> ''::text AND t.t !~ '^[0-9]+$'::text AND t.t <> 'sitelink'::text) AS tok_meio
           FROM ( SELECT DISTINCT e.metadata ->> 'utm_campaign'::text AS utm_campaign,
                    e.metadata ->> 'utm_medium'::text AS utm_medium
                   FROM entrada e
                  WHERE (e.metadata ->> 'canal'::text) = 'Google Ads'::text AND NULLIF(TRIM(BOTH FROM e.metadata ->> 'utm_campaign'::text), ''::text) IS NOT NULL) u
        ), cand AS (
         SELECT u.utm_campaign,
            u.utm_medium,
            g.campaign_id,
            g.nome_lower = lower(TRIM(BOTH FROM u.utm_campaign)) AS exato,
            cardinality(u.tok_meio) > 0 AND u.tok_meio && g.tok AS por_meio,
            cardinality(ARRAY( SELECT unnest(g.tok) AS unnest
                EXCEPT
                 SELECT unnest(u.tok) AS unnest)) + cardinality(ARRAY( SELECT unnest(u.tok) AS unnest
                EXCEPT
                 SELECT unnest(g.tok) AS unnest)) AS sobra
           FROM utm_tok u
             JOIN google g ON g.nome_lower = lower(TRIM(BOTH FROM u.utm_campaign)) OR cardinality(u.tok) > 0 AND cardinality(g.tok) > 0 AND (u.tok <@ g.tok OR g.tok <@ u.tok)
        ), cand2 AS (
         SELECT c_1.utm_campaign,
            c_1.utm_medium,
            c_1.campaign_id,
            c_1.exato,
            c_1.por_meio,
            c_1.sobra,
            count(*) FILTER (WHERE c_1.por_meio) OVER w AS n_meio,
            bool_or(c_1.exato) OVER w AS tem_exato
           FROM cand c_1
          WINDOW w AS (PARTITION BY c_1.utm_campaign, c_1.utm_medium)
        ), cand3 AS (
         SELECT c_1.utm_campaign,
            c_1.utm_medium,
            c_1.campaign_id,
            c_1.exato,
            c_1.por_meio,
            c_1.sobra,
            c_1.n_meio,
            c_1.tem_exato,
            min(c_1.sobra) OVER w AS min_sobra
           FROM cand2 c_1
          WHERE c_1.tem_exato AND c_1.exato OR NOT c_1.tem_exato AND (c_1.n_meio = 0 OR c_1.por_meio)
          WINDOW w AS (PARTITION BY c_1.utm_campaign, c_1.utm_medium)
        ), google_match AS (
         SELECT c_1.utm_campaign,
            c_1.utm_medium,
            min(c_1.campaign_id) AS campaign_id
           FROM cand3 c_1
          WHERE c_1.sobra = c_1.min_sobra
          GROUP BY c_1.utm_campaign, c_1.utm_medium
         HAVING count(*) = 1 OR bool_or(c_1.exato)
        ), cnpj AS (
         SELECT lbc.lead_id
           FROM lead_bling_contacts lbc
             JOIN bling_contacts bc ON bc.id = lbc.bling_contact_id AND bc.account = lbc.account
          WHERE length(bc.doc_digits) = 14
        UNION
         SELECT l.id
           FROM leads l
             JOIN bling_contacts bc ON bc.id = l.bling_contact_id
          WHERE length(bc.doc_digits) = 14
        ), pipe_b2b AS (
         SELECT DISTINCT d.lead_id
           FROM deals d
             JOIN pipelines p ON p.id = d.pipeline_id
          WHERE p.name ~* '(atacado|private label)'::text
        ), base AS (
         SELECT l.id AS lead_id,
            l.created_at,
            l.assigned_to,
            l.channel,
            l.gclid,
            l.fbclid,
            l.ctwa_clid,
            l.meta_ad_id,
            l.utm_source,
            l.utm_medium,
            l.traffic_type,
            l.gbraid,
            l.wbraid,
            COALESCE(l.ja_era_cliente, false) AS ja_era_cliente,
            l.channel = 'bling'::text OR (COALESCE(l.metadata ->> 'origem'::text, ''::text) = ANY (ARRAY['bling_webhook'::text, 'reativacao_bling'::text])) AS importado_bling,
                CASE
                    WHEN l.stage = ANY (ARRAY['secretaria'::text, 'atacado'::text, 'private_label'::text, 'consumo'::text, 'exportacao'::text]) THEN l.stage
                    WHEN ((l.metadata -> 'handoff'::text) ->> 'segmento'::text) = ANY (ARRAY['secretaria'::text, 'atacado'::text, 'private_label'::text, 'consumo'::text, 'exportacao'::text]) THEN (l.metadata -> 'handoff'::text) ->> 'segmento'::text
                    ELSE NULL::text
                END AS segmento,
            NULLIF(TRIM(BOTH FROM l.campanha_manual_id), ''::text) AS manual_id,
            NULLIF(TRIM(BOTH FROM l.campanha_manual_nome), ''::text) AS manual_nome,
            lower(NULLIF(TRIM(BOTH FROM l.campanha_manual_canal), ''::text)) AS manual_canal,
            e.lead_id IS NOT NULL AS tem_entrada,
                CASE
                    WHEN COALESCE(e.dedupe_key, ''::text) !~~ '%:inicial'::text AND l.utm_campaign = 'WhatsApp do Google'::text AND l.created_at < e.occurred_at THEN l.created_at
                    ELSE e.occurred_at
                END AS entrada_em,
            COALESCE(e.dedupe_key, ''::text) !~~ '%:inicial'::text AND l.utm_campaign = 'WhatsApp do Google'::text AND l.created_at < e.occurred_at AS entrada_ajustada,
            e.metadata ->> 'canal'::text AS entrada_canal,
            NULLIF(e.metadata ->> 'campanha_id'::text, ''::text) AS entrada_campanha_id,
            NULLIF(e.metadata ->> 'campanha_nome'::text, ''::text) AS entrada_campanha_nome,
            mac.campaign_id AS ad_campanha_id,
            gm.campaign_id AS google_campanha_id
           FROM leads l
             LEFT JOIN entrada e ON e.lead_id = l.id
             LEFT JOIN meta_ad_campaigns mac ON mac.ad_id = NULLIF(e.metadata ->> 'meta_ad_id'::text, ''::text)
             LEFT JOIN google_match gm ON gm.utm_campaign = (e.metadata ->> 'utm_campaign'::text) AND NOT gm.utm_medium IS DISTINCT FROM (e.metadata ->> 'utm_medium'::text) AND (e.metadata ->> 'canal'::text) = 'Google Ads'::text
        ), atrib AS (
         SELECT b.lead_id,
            b.created_at,
            b.assigned_to,
            b.channel,
            b.gclid,
            b.fbclid,
            b.ctwa_clid,
            b.meta_ad_id,
            b.utm_source,
            b.utm_medium,
            b.traffic_type,
            b.gbraid,
            b.wbraid,
            b.ja_era_cliente,
            b.importado_bling,
            b.segmento,
            b.manual_id,
            b.manual_nome,
            b.manual_canal,
            b.tem_entrada,
            b.entrada_em,
            b.entrada_ajustada,
            b.entrada_canal,
            b.entrada_campanha_id,
            b.entrada_campanha_nome,
            b.ad_campanha_id,
            b.google_campanha_id,
                CASE
                    WHEN b.manual_id IS NOT NULL OR b.manual_nome IS NOT NULL THEN COALESCE(b.manual_canal, 'manual'::text)
                    WHEN b.entrada_canal = 'Meta Ads'::text THEN 'meta'::text
                    WHEN b.entrada_canal = 'Google Ads'::text THEN 'google'::text
                    WHEN b.entrada_canal = 'Orgânico'::text THEN 'organico'::text
                    WHEN b.tem_entrada THEN lower(b.entrada_canal)
                    ELSE NULL::text
                END AS plataforma,
                CASE
                    WHEN b.manual_id IS NOT NULL OR b.manual_nome IS NOT NULL THEN b.manual_id
                    WHEN b.entrada_canal = 'Meta Ads'::text THEN COALESCE(b.entrada_campanha_id, b.ad_campanha_id)
                    WHEN b.entrada_canal = 'Google Ads'::text THEN COALESCE(b.entrada_campanha_id, b.google_campanha_id)
                    ELSE NULL::text
                END AS campanha_id,
                CASE
                    WHEN b.manual_id IS NOT NULL OR b.manual_nome IS NOT NULL THEN 'manual'::text
                    WHEN b.entrada_campanha_id IS NOT NULL THEN 'entrada'::text
                    WHEN b.entrada_canal = 'Meta Ads'::text AND b.ad_campanha_id IS NOT NULL THEN 'meta_ad_id'::text
                    WHEN b.entrada_canal = 'Google Ads'::text AND b.google_campanha_id IS NOT NULL THEN 'utm_match'::text
                    WHEN b.entrada_canal = ANY (ARRAY['Meta Ads'::text, 'Google Ads'::text]) THEN 'nao_atribuido'::text
                    WHEN b.tem_entrada THEN 'sem_campanha'::text
                    ELSE NULL::text
                END AS atribuicao_fonte
           FROM base b
        )
 SELECT a.lead_id,
    a.created_at AS criado_em,
    a.entrada_em,
    (a.entrada_em AT TIME ZONE 'America/Sao_Paulo'::text)::date AS entrada_data,
        CASE
            WHEN a.tem_entrada THEN a.entrada_canal
            WHEN a.importado_bling THEN 'Bling'::text
            ELSE fn_lead_canal(a.gclid, a.fbclid, a.ctwa_clid, a.meta_ad_id, a.utm_source, a.utm_medium, a.traffic_type, a.gbraid, a.wbraid)
        END AS canal,
        CASE
            WHEN a.importado_bling THEN 'bling_import'::text
            WHEN a.entrada_canal = 'Meta Ads'::text THEN 'anuncio_meta'::text
            WHEN a.entrada_canal = 'Google Ads'::text THEN 'anuncio_google'::text
            WHEN a.entrada_canal = 'Orgânico'::text THEN 'organico'::text
            ELSE 'outro'::text
        END AS origem_cadastro,
    a.tem_entrada AND NOT a.importado_bling AND NOT a.ja_era_cliente AS eh_lead_marketing,
    a.importado_bling,
    a.ja_era_cliente,
    a.segmento,
    COALESCE(a.segmento = ANY (ARRAY['atacado'::text, 'private_label'::text]), false) OR sq.lead_id IS NOT NULL OR pb.lead_id IS NOT NULL OR cj.lead_id IS NOT NULL AS b2b,
        CASE
            WHEN a.segmento = ANY (ARRAY['atacado'::text, 'private_label'::text]) THEN 'segmento'::text
            WHEN sq.lead_id IS NOT NULL THEN 'score_atacado'::text
            WHEN pb.lead_id IS NOT NULL THEN 'pipeline'::text
            WHEN cj.lead_id IS NOT NULL THEN 'cnpj_bling'::text
            ELSE NULL::text
        END AS b2b_fonte,
    a.plataforma AS plataforma_primeiro_toque,
    a.campanha_id AS campanha_id_primeiro_toque,
        CASE
            WHEN a.plataforma = ANY (ARRAY['meta'::text, 'google'::text]) THEN COALESCE(c.campaign_name, a.manual_nome, a.entrada_campanha_nome,
            CASE
                WHEN a.campanha_id IS NOT NULL THEN a.campanha_id
                ELSE NULL::text
            END, '(não atribuído)'::text)
            WHEN a.plataforma IS NOT NULL THEN COALESCE(a.manual_nome, '(sem campanha)'::text)
            ELSE NULL::text
        END AS campanha_primeiro_toque,
    a.atribuicao_fonte,
        CASE
            WHEN a.entrada_ajustada THEN 'entrada gravada pelo backfill do botão WhatsApp do Google, usada a data de criação do lead'::text
            ELSE NULL::text
        END AS alerta_entrada,
    a.assigned_to AS vendedor_responsavel_id,
    dv.vendedor AS vendedor_responsavel
   FROM atrib a
     LEFT JOIN camp c ON c.platform = a.plataforma AND c.campaign_id = a.campanha_id
     LEFT JOIN pipe_b2b pb ON pb.lead_id = a.lead_id
     LEFT JOIN lead_qualification_scores sq ON sq.lead_id = a.lead_id
     LEFT JOIN cnpj cj ON cj.lead_id = a.lead_id
     LEFT JOIN ( SELECT DISTINCT ON (d.user_id) d.user_id,
            d.vendedor,
            d.vendedor_chave
           FROM analytics.dim_vendedor d
          WHERE d.user_id IS NOT NULL
          ORDER BY d.user_id, d.vendedor_chave) dv ON dv.user_id = a.assigned_to;

comment on view analytics.dim_lead is 'Auxiliar. Uma linha por lead (todos os contatos): entrada = primeiro evento entrada, atribuição de primeiro toque (manual > campanha da entrada > meta_ad_id > casamento do utm_campaign com o nome da campanha Google em ad_spend), origem do cadastro, D1 (lead de marketing), segmento (leads.stage válido, senão metadata.handoff.segmento) e D9 (B2B). Base de vw_leads, vw_repasses e fct_vendas.';
grant SELECT on analytics.dim_lead to consulta_ro;
