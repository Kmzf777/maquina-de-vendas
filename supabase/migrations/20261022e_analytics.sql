-- supabase/migrations/20261022e_analytics.sql
--
-- Cartão b67f1c6b — spec docs/superpowers/specs/2026-10-22-crm-leads-vendedor-design.md, item 6.
--
-- O schema analytics não era versionado. As definições vigentes em 22/10 (pg_get_viewdef, com
-- owner, reloptions, comentário e grants) estão em scripts/leads_vendedor/defs_antes/analytics.*.sql
-- e são o rollback desta migration (aplicar dim_vendedor, dim_lead e vw_leads de lá).
--
--   1. analytics.dim_vendedor vira view sobre public.vendedores (B2), com as MESMAS colunas:
--      vendedor_chave = 1º token do nome, sem acento e minúsculo (o que vw_repasses casa com o
--      nome citado no repasse); user_id = vendedores.id; emails = e-mail do cadastro + e-mails
--      do bling_seller_map ligados por vendedor_id (fct_vendas casa sold_by/bling por e-mail);
--      alerta_ambiguo = dois vendedores com a mesma chave (a linha fica com o ativo).
--   2. analytics.dim_lead: segmento = leads.segmento (D11; antes vinha de leads.stage ou de
--      metadata.handoff.segmento, e 'secretaria' contava como segmento); b2b = fn_lead_b2b (D9:
--      ter score NÃO basta mais); b2b_fonte = 'segmento' | 'pipeline' | 'cnpj' (antes também
--      'score_atacado', e 'cnpj_bling' virou 'cnpj'). Resto literal.
--   3. analytics.vw_leads: definição literal (versionada aqui); só o comentário muda.
--
-- Mesmas colunas, mesma ordem, mesmos tipos: CREATE OR REPLACE não derruba as dependentes
-- (fct_vendas, vw_repasses, vw_clientes, vw_disparos, vw_produtos_mes, vw_resposta_closer,
-- vw_campanhas_dia, vw_funil_mes, vw_vendedores_semana, valeria_score_*) nem os grants.
--
-- Depende de 20261022a (vendedores) e 20261022b (leads.segmento, fn_lead_b2b). Se a 20261022c
-- já rodou, fn_lead_canal(9 args) resolve para a nova (p_origem default NULL) e a legada
-- fn_lead_canal_legado_b67f é dropada no fim (se nada mais depender dela).
--
-- ORDEM EM PRODUÇÃO: aplicar DEPOIS dos backfills F1 (vendedores) e F2 (segmento). Antes disso
-- dim_vendedor sai vazia (repasses e vendas sem vendedor) e dim_lead.segmento sai NULL.
-- DONO: em produção as views analytics são de supabase_admin; CREATE OR REPLACE exige o dono.
-- Aplicar como supabase_admin (psql -U supabase_admin), não como postgres.
--
-- NÃO É APLICADA PELO DEPLOY. Reexecutar é seguro. Depois: SIGUSR1 no PostgREST.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL search_path = public, extensions;

-- ── 1. dim_vendedor ────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW analytics.dim_vendedor WITH (security_invoker = true) AS
 WITH v AS (
         SELECT v_1.id,
            v_1.email,
            v_1.nome,
            v_1.ativo,
            lower(translate("substring"(TRIM(BOTH FROM v_1.nome), '^[^\s@:._-]+'::text), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇáàâãäéèêëíìîïóòôõöúùûüç'::text, 'AAAAAEEEEIIIIOOOOOUUUUCaaaaaeeeeiiiiooooouuuuc'::text)) AS chave
           FROM public.vendedores v_1
        ), emails AS (
         SELECT v_1.id,
            lower(TRIM(BOTH FROM v_1.email)) AS email
           FROM v v_1
        UNION
         SELECT m.vendedor_id,
            lower(TRIM(BOTH FROM m.user_email)) AS lower
           FROM public.bling_seller_map m
          WHERE m.vendedor_id IS NOT NULL AND NULLIF(TRIM(BOTH FROM m.user_email), ''::text) IS NOT NULL
        )
 SELECT v.chave AS vendedor_chave,
    (array_agg(v.nome ORDER BY v.ativo DESC, v.nome, v.id))[1] AS vendedor,
    (array_agg(v.id ORDER BY v.ativo DESC, v.nome, v.id))[1] AS user_id,
    (array_agg(v.email ORDER BY v.ativo DESC, v.nome, v.id))[1] AS email,
    COALESCE(( SELECT array_agg(DISTINCT e.email ORDER BY e.email) AS array_agg
           FROM emails e
          WHERE e.id = ANY (array_agg(v.id))), '{}'::text[]) AS emails,
    count(*) > 1 AS alerta_ambiguo
   FROM v
  WHERE COALESCE(v.chave, ''::text) <> ''::text
  GROUP BY v.chave;

COMMENT ON VIEW analytics.dim_vendedor IS
  'Auxiliar. Um vendedor por chave, lido do cadastro único public.vendedores (b67f1c6b, B2): vendedor_chave = primeiro nome sem acento e minúsculo (casa com o nome citado no repasse), vendedor = nome, user_id = vendedores.id, email = e-mail do cadastro, emails = e-mail do cadastro + e-mails do bling_seller_map ligados por vendedor_id. Inclui inativos (Rafael, Comercial 2), que só resolvem o histórico. alerta_ambiguo = dois vendedores com a mesma chave (a linha mostra o ativo).';

-- ── 2. dim_lead ────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW analytics.dim_lead WITH (security_invoker = true) AS
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
            l.segmento,
            COALESCE(fn_lead_b2b(l.id), false) AS b2b,
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
            b.b2b,
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
    a.b2b,
        CASE
            WHEN NOT a.b2b THEN NULL::text
            WHEN a.segmento = ANY (ARRAY['atacado'::text, 'private_label'::text]) THEN 'segmento'::text
            WHEN pb.lead_id IS NOT NULL THEN 'pipeline'::text
            ELSE 'cnpj'::text
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
     LEFT JOIN ( SELECT DISTINCT ON (d.user_id) d.user_id,
            d.vendedor,
            d.vendedor_chave
           FROM analytics.dim_vendedor d
          WHERE d.user_id IS NOT NULL
          ORDER BY d.user_id, d.vendedor_chave) dv ON dv.user_id = a.assigned_to;;

COMMENT ON VIEW analytics.dim_lead IS
  'Auxiliar. Uma linha por lead (todos os contatos): entrada = primeiro evento entrada, atribuição de primeiro toque (manual > campanha da entrada > meta_ad_id > casamento do utm_campaign com o nome da campanha Google em ad_spend), origem do cadastro, D1 (lead de marketing), segmento (leads.segmento: atacado, private_label, consumo, exportacao ou NULL = ainda não sabe; D11) e D9 (b2b = fn_lead_b2b: segmento atacado/private_label, deal em funil Atacado/Private Label ou CNPJ no Bling; ter score não basta). b2b_fonte: segmento | pipeline | cnpj. Base de vw_leads, vw_repasses e fct_vendas.';

-- ── 3. vw_leads (literal; versionada aqui) ─────────────────────────────────────────
CREATE OR REPLACE VIEW analytics.vw_leads WITH (security_invoker = true) AS
 WITH rep AS (
         SELECT r_1.lead_id,
            min(r_1.repasse_em) AS primeiro_repasse_em,
            min(r_1.repasse_em) FILTER (WHERE r_1.por_qualificacao) AS primeiro_repasse_qualif_em,
            count(*) AS qtd_repasses
           FROM analytics.vw_repasses r_1
          GROUP BY r_1.lead_id
        ), score AS (
         SELECT s.lead_id,
            s.updated_at AS score_em,
            s.final_score
           FROM lead_qualification_scores s
          WHERE s.final_score >= 5 AND NOT COALESCE(s.is_provisional, true)
        )
 SELECT dl.lead_id,
    dl.criado_em,
    dl.entrada_em,
    dl.entrada_data,
    dl.canal,
    dl.origem_cadastro,
    dl.eh_lead_marketing,
    dl.importado_bling,
    dl.segmento,
    dl.b2b,
    dl.b2b_fonte,
    dl.plataforma_primeiro_toque,
    dl.campanha_id_primeiro_toque,
    dl.campanha_primeiro_toque,
    dl.atribuicao_fonte,
    dl.alerta_entrada,
    dl.ja_era_cliente,
    dl.vendedor_responsavel,
        CASE
            WHEN dl.b2b THEN sc.lead_id IS NOT NULL OR r.primeiro_repasse_qualif_em IS NOT NULL
            ELSE r.lead_id IS NOT NULL
        END AS qualificado,
        CASE
            WHEN dl.b2b THEN LEAST(sc.score_em, r.primeiro_repasse_qualif_em)
            ELSE r.primeiro_repasse_em
        END AS qualificado_em,
        CASE
            WHEN dl.b2b AND sc.lead_id IS NOT NULL AND r.primeiro_repasse_qualif_em IS NOT NULL THEN 'score_e_repasse'::text
            WHEN dl.b2b AND sc.lead_id IS NOT NULL THEN 'score'::text
            WHEN dl.b2b AND r.primeiro_repasse_qualif_em IS NOT NULL THEN 'repasse'::text
            WHEN NOT dl.b2b AND r.lead_id IS NOT NULL THEN 'repasse'::text
            ELSE NULL::text
        END AS criterio_qualificacao,
    sc.final_score AS score_final,
    r.lead_id IS NOT NULL AS repassado,
    r.primeiro_repasse_em,
    (r.primeiro_repasse_em AT TIME ZONE 'America/Sao_Paulo'::text)::date AS primeiro_repasse_data,
    COALESCE(r.qtd_repasses, 0::bigint) AS qtd_repasses
   FROM analytics.dim_lead dl
     LEFT JOIN rep r ON r.lead_id = dl.lead_id
     LEFT JOIN score sc ON sc.lead_id = dl.lead_id;;

COMMENT ON VIEW analytics.vw_leads IS
  'Uma linha por lead (todos os contatos; filtre eh_lead_marketing para D1). Traz entrada (primeiro evento entrada, D10), canal, origem do cadastro, segmento (leads.segmento, D11), B2B (D9, fn_lead_b2b), campanha de primeiro toque, vendedor responsável, qualificado (D2: B2B = score final >= 5 não provisório ou repasse por qualificação; B2C = repasse; morno não conta) e repasse ao closer (D3). O evento lead_events ''qualificado'' (b67f1c6b) é a fonte do dashboard; esta coluna continua calculada.';

GRANT SELECT ON analytics.dim_vendedor, analytics.dim_lead, analytics.vw_leads TO consulta_ro;

-- ── 4. fn_lead_canal legada (20261022c) ────────────────────────────────────────────
-- dim_lead agora chama fn_lead_canal pelo nome; se a legada sobrou só por causa dela, sai.
DO $$
BEGIN
  IF to_regprocedure('public.fn_lead_canal_legado_b67f(text,text,text,text,text,text,text,text,text)') IS NOT NULL THEN
    BEGIN
      DROP FUNCTION public.fn_lead_canal_legado_b67f(text,text,text,text,text,text,text,text,text);
    EXCEPTION WHEN dependent_objects_still_exist THEN
      RAISE NOTICE 'fn_lead_canal_legado_b67f mantida: ainda há dependentes';
    END;
  END IF;
END $$;

COMMIT;
