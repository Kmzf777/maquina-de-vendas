-- scripts/leads_vendedor/rollback_migrations.sql — desfaz as migrations 20261022a..f (cartão b67f1c6b)
--
-- Ordem inversa: f, e, d1, d, c, b, a. As definições de antes são cópia LITERAL de
-- scripts/leads_vendedor/defs_antes/ (pg_get_functiondef / pg_get_viewdef de produção em 22/10/2026),
-- embutidas aqui para o arquivo rodar sozinho. Tudo numa transação: ou volta tudo, ou nada.
--
--   f  : DROP do CHECK leads_stage_fase_check (o default 'pending' de leads.stage já era o de antes).
--   e  : analytics.dim_vendedor, dim_lead e vw_leads (CREATE OR REPLACE mantém dono e dependentes;
--        comentário e grants de antes).
--   d1 : valeria_score_directory de antes (+ grants; sem comentário, como era).
--   d  : dashboard_kpis DROP + CREATE (12 colunas, sem contacts_new) com os grants de antes
--        (PUBLIC, anon, authenticated, service_role; sem consulta_ro); dashboard_funnel_conversion de antes.
--   c  : fn_lead_events_leads_entrada e fn_lead_entrada_metadata de antes; fn_lead_canal volta a ter
--        9 args (a de 10 é renomeada, a de 9 é recriada, analytics.dim_lead é religada nela e a de 10
--        é dropada — se algo ainda depender dela, o DROP falha e nada é desfeito);
--        DROP leads.origem_cadastro.
--   b  : DROP fn_lead_b2b, idx_leads_segmento e leads.segmento.
--   a  : DROP FK/índice de deals.assigned_to e volta a coluna para text (valores uuid viram texto;
--        rode o f6_rollback.sql antes para devolver NULL); DROP bling_seller_map.vendedor_id,
--        fn_vendedor_id e a tabela vendedores.
--
-- DADOS que somem: leads.segmento, leads.origem_cadastro, vendedores, bling_seller_map.vendedor_id.
-- Os backups backup_b67f_fN ficam (os de F2/F4 guardam segmento/origem anteriores). Os eventos
-- lead_events 'qualificado'/'entrada' gravados pelos backfills NÃO são apagados aqui
-- (f5_rollback.sql / f7_rollback.sql). O F3 (stage -> fase) também não: f3_rollback.sql.
--
-- PRODUÇÃO: rodar como supabase_admin (dono das views analytics; CREATE OR REPLACE exige o dono):
--   docker exec -i <supabase_db> psql -U supabase_admin -d postgres -X -v ON_ERROR_STOP=1 < rollback_migrations.sql
-- As funções recriadas recebem OWNER postgres explicitamente (o dono de antes) antes dos grants.
-- Depois: recarregar o PostgREST com SIGUSR1 (NOTIFY é ignorado na VPS). Reexecutar é seguro.
-- Testado no scratch: aplica a..f -> rollback -> md5(prosrc) de dashboard_kpis e fn_lead_canal igual
-- ao de produção -> reaplica a..f sem erro.

begin;
set local lock_timeout = '5s';
set local search_path = public, extensions;

-- ════ f ══════════════════════════════════════════════════════════════════════════════
alter table public.leads drop constraint if exists leads_stage_fase_check;

-- ════ e ══════════════════════════════════════════════════════════════════════════════
-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: supabase_admin; reloptions: security_invoker=true
-- acl: {supabase_admin=arwdDxtm/supabase_admin,consulta_ro=r/supabase_admin}

create or replace view analytics.dim_vendedor with (security_invoker=true) as
 WITH fontes AS (
         SELECT c.user_id,
            NULL::text AS email,
            c.display_name AS nome,
            1 AS prioridade
           FROM sla_seller_config c
        UNION ALL
         SELECT ch.owner_user_id,
            NULL::text AS text,
            initcap(lower(TRIM(BOTH FROM regexp_replace(ch.name, '^\s*n[uú]mero\s+'::text, ''::text, 'i'::text)))) AS initcap,
            2
           FROM channels ch
          WHERE ch.mode = 'human'::text AND ch.owner_user_id IS NOT NULL
        UNION ALL
         SELECT p.owner_user_id,
            NULL::text AS text,
            TRIM(BOTH FROM split_part(p.name, ' - '::text, 1)) AS btrim,
            3
           FROM pipelines p
          WHERE p.owner_user_id IS NOT NULL AND p.name ~~ '% - %'::text
        UNION ALL
         SELECT NULL::uuid AS uuid,
            lower(TRIM(BOTH FROM m.user_email)) AS lower,
            NULL::text AS text,
            4
           FROM bling_seller_map m
          WHERE NULLIF(TRIM(BOTH FROM m.user_email), ''::text) IS NOT NULL
        UNION ALL
         SELECT DISTINCT NULL::uuid AS uuid,
            lower(TRIM(BOTH FROM s.sold_by)) AS lower,
            NULL::text AS text,
            5
           FROM sales s
          WHERE NULLIF(TRIM(BOTH FROM s.sold_by), ''::text) IS NOT NULL
        UNION ALL
         SELECT DISTINCT NULL::uuid AS uuid,
            lower(TRIM(BOTH FROM q.created_by)) AS lower,
            NULL::text AS text,
            6
           FROM quotes q
          WHERE NULLIF(TRIM(BOTH FROM q.created_by), ''::text) IS NOT NULL
        ), chaves AS (
         SELECT f.user_id,
            f.email,
            f.nome,
            f.prioridade,
            lower(translate("substring"(TRIM(BOTH FROM COALESCE(f.nome, f.email)), '^[^\s@:._-]+'::text), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇáàâãäéèêëíìîïóòôõöúùûüç'::text, 'AAAAAEEEEIIIIOOOOOUUUUCaaaaaeeeeiiiiooooouuuuc'::text)) AS chave
           FROM fontes f
        )
 SELECT chave AS vendedor_chave,
    COALESCE((array_agg(nome ORDER BY prioridade) FILTER (WHERE nome IS NOT NULL))[1], initcap(chave)) AS vendedor,
    (array_agg(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL))[1] AS user_id,
    min(email) AS email,
    COALESCE(array_agg(DISTINCT email) FILTER (WHERE email IS NOT NULL), '{}'::text[]) AS emails,
    count(DISTINCT user_id) > 1 AS alerta_ambiguo
   FROM chaves
  WHERE COALESCE(chave, ''::text) <> ''::text
  GROUP BY chave;

comment on view analytics.dim_vendedor is 'Auxiliar. Cadastro de vendedores (chave, nome, user_id, e-mails) montado sem auth.users, juntando sla_seller_config, canais humanos, donos de pipeline, bling_seller_map, sales.sold_by e quotes.created_by pelo primeiro nome normalizado; contorno do bug B2 (não existe tabela de vendedores).';
grant SELECT on analytics.dim_vendedor to consulta_ro;

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

-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: supabase_admin; reloptions: security_invoker=true
-- acl: {supabase_admin=arwdDxtm/supabase_admin,consulta_ro=r/supabase_admin}

create or replace view analytics.vw_leads with (security_invoker=true) as
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
     LEFT JOIN score sc ON sc.lead_id = dl.lead_id;

comment on view analytics.vw_leads is 'Uma linha por lead (todos os contatos; filtre eh_lead_marketing para D1). Traz entrada (primeiro evento entrada, D10), canal, origem do cadastro, segmento (leads.stage quando é segmento válido; D11 ainda não existe), B2B (D9), campanha de primeiro toque, vendedor responsável, qualificado (D2: B2B = score final >= 5 não provisório ou repasse por qualificação; B2C = repasse; morno não conta) e repasse ao closer (D3).';
grant SELECT on analytics.vw_leads to consulta_ro;

-- ════ d1 ═════════════════════════════════════════════════════════════════════════════
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
comment on view public.valeria_score_directory is null;

-- ════ d ══════════════════════════════════════════════════════════════════════════════
drop function if exists public.dashboard_kpis(date, date, text);

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

alter function public.dashboard_kpis(date, date, text) owner to postgres;
grant execute on function public.dashboard_kpis(date, date, text) to public, anon, authenticated, service_role;

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

grant execute on function public.dashboard_funnel_conversion(date, date, text) to public, anon, authenticated, service_role;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'consulta_ro') then
    revoke execute on function public.dashboard_kpis(date, date, text) from consulta_ro;
    revoke execute on function public.dashboard_funnel_conversion(date, date, text) from consulta_ro;
  end if;
end $$;

-- ════ c ══════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.fn_lead_events_leads_entrada()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare
  v_meta jsonb;
  v_ultimo uuid;
begin
  -- Guardas baratas FORA do bloco com exception: ele abre subtransacao por linha.
  if not public.fn_lead_tem_rastreio(new.gclid, new.fbclid, new.ctwa_clid, new.meta_ad_id,
                                     new.utm_source, new.utm_campaign,
                                     new.gbraid, new.wbraid) then
    return new;
  end if;
  if tg_op = 'UPDATE' then
    if new.ctwa_clid is not distinct from old.ctwa_clid
       and new.gclid is not distinct from old.gclid
       and new.gbraid is not distinct from old.gbraid
       and new.wbraid is not distinct from old.wbraid
       and new.fbclid is not distinct from old.fbclid
       and new.meta_ad_id is not distinct from old.meta_ad_id
       and new.utm_source is not distinct from old.utm_source
       and new.utm_campaign is not distinct from old.utm_campaign then
      return new;
    end if;
  end if;
  begin
    v_meta := public.fn_lead_entrada_metadata(new.gclid, new.fbclid, new.ctwa_clid, new.meta_ad_id,
                                              new.utm_source, new.utm_medium, new.utm_campaign,
                                              new.traffic_type, new.gbraid, new.wbraid);

    -- so meta_ad_id mudou (ctwa_clid e o resto iguais): e ENRIQUECIMENTO da mesma entrada,
    -- nunca entrada nova. Acontece no webhook (meta_ad_id chega depois do ctwa_clid) e no
    -- scripts/trafego/recuperar_meta_ad_id.py do P2 (~687 leads antigos), que sem esta regra
    -- ganhariam entradas falsas datadas do dia do script. Atualiza a entrada mais recente com
    -- o MESMO ctwa_clid; nao havendo, nao faz nada.
    if tg_op = 'UPDATE'
       and new.ctwa_clid is not distinct from old.ctwa_clid
       and new.gclid is not distinct from old.gclid
       and new.gbraid is not distinct from old.gbraid
       and new.wbraid is not distinct from old.wbraid
       and new.fbclid is not distinct from old.fbclid
       and new.utm_source is not distinct from old.utm_source
       and new.utm_campaign is not distinct from old.utm_campaign then
      if public.fn_lead_txt(new.ctwa_clid) <> '' then
        update public.lead_events alvo
           set metadata = coalesce(alvo.metadata, '{}'::jsonb)
                          || jsonb_build_object('meta_ad_id', new.meta_ad_id)
                          || case when v_meta->>'campanha_id' is not null
                                  then jsonb_build_object('campanha_id', v_meta->'campanha_id',
                                                          'campanha_nome', v_meta->'campanha_nome')
                                  else '{}'::jsonb end
         where alvo.id = (select e.id from public.lead_events e
                           where e.lead_id = new.id and e.event_type = 'entrada'
                             and e.metadata->>'ctwa_clid' = new.ctwa_clid
                           order by e.occurred_at desc, e.created_at desc
                           limit 1);
      end if;
      return new;
    end if;

    if tg_op = 'UPDATE' then
      select e.id into v_ultimo
        from public.lead_events e
       where e.lead_id = new.id
         and e.event_type = 'entrada'
         and e.occurred_at >= now() - interval '30 minutes'
       order by e.occurred_at desc, e.created_at desc
       limit 1;
      if v_ultimo is not null then
        update public.lead_events
           set metadata = coalesce(metadata, '{}'::jsonb) || v_meta,
               new_value = v_meta->>'canal',
               source = public.fn_lead_entrada_source(v_meta)
         where id = v_ultimo;
        return new;
      end if;
    end if;

    insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
    values (new.id, 'entrada', v_meta->>'canal', v_meta,
            case when tg_op = 'INSERT' then coalesce(new.created_at, now()) else now() end,
            public.fn_lead_entrada_source(v_meta),
            case when tg_op = 'INSERT' then 'entrada:lead:' || new.id || ':inicial'
                 else 'entrada:lead:' || new.id || ':' || extract(epoch from now())::text end)
    on conflict (dedupe_key) where dedupe_key is not null do nothing;
  exception when others then
    raise warning 'fn_lead_events_leads_entrada: %', sqlerrm;
  end;
  return new;
end $function$
;
revoke execute on function public.fn_lead_events_leads_entrada() from public, anon, authenticated;

CREATE OR REPLACE FUNCTION public.fn_lead_entrada_metadata(p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text, p_utm_source text, p_utm_medium text, p_utm_campaign text, p_traffic_type text, p_gbraid text DEFAULT NULL::text, p_wbraid text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
AS $function$
  select jsonb_build_object(
    'canal', public.fn_lead_canal(p_gclid, p_fbclid, p_ctwa_clid, p_meta_ad_id,
                                  p_utm_source, p_utm_medium, p_traffic_type,
                                  p_gbraid, p_wbraid),
    'campanha_id', mac.campaign_id,
    'campanha_nome', nullif(mac.campaign_name, ''),
    'ctwa_clid', p_ctwa_clid,
    'meta_ad_id', p_meta_ad_id,
    'gclid', p_gclid,
    'gbraid', p_gbraid,
    'wbraid', p_wbraid,
    'fbclid', p_fbclid,
    'utm_source', p_utm_source,
    'utm_medium', p_utm_medium,
    'utm_campaign', p_utm_campaign)
  from (select 1) as um
  left join public.meta_ad_campaigns mac on mac.ad_id = nullif(btrim(p_meta_ad_id), '')
$function$
;

-- fn_lead_canal: tira a de 10 args do caminho (renomeia) e devolve a de 9.
do $$
begin
  if to_regprocedure('public.fn_lead_canal(text,text,text,text,text,text,text,text,text,text)') is not null then
    alter function public.fn_lead_canal(text,text,text,text,text,text,text,text,text,text)
      rename to fn_lead_canal_b67f_rollback;
  end if;
  -- só a 20261022c aplicada (sem a e): a de 9 args ainda existe como fn_lead_canal_legado_b67f
  if to_regprocedure('public.fn_lead_canal_legado_b67f(text,text,text,text,text,text,text,text,text)') is not null
     and to_regprocedure('public.fn_lead_canal(text,text,text,text,text,text,text,text,text)') is null then
    alter function public.fn_lead_canal_legado_b67f(text,text,text,text,text,text,text,text,text)
      rename to fn_lead_canal;
  end if;
end $$;

CREATE OR REPLACE FUNCTION public.fn_lead_canal(p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text, p_utm_source text, p_utm_medium text, p_traffic_type text, p_gbraid text DEFAULT NULL::text, p_wbraid text DEFAULT NULL::text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
AS $function$
  select case
    when public.fn_lead_txt(p_gclid) <> '' or public.fn_lead_txt(p_gbraid) <> ''
      or public.fn_lead_txt(p_wbraid) <> '' then 'Google Ads'
    when public.fn_lead_txt(p_fbclid) <> '' or public.fn_lead_txt(p_ctwa_clid) <> ''
      or public.fn_lead_txt(p_meta_ad_id) <> '' then 'Meta Ads'
    when public.fn_lead_txt(p_utm_source) = any (array['metaads', 'meta_ads', 'meta-ads', 'meta', 'facebook_ads', 'facebookads', 'fb_ads']) -- _META_AD_SOURCES
      then 'Meta Ads'
    when public.fn_lead_txt(p_utm_source) = any (array['google', 'googleads', 'google_ads', 'adwords']) -- _GOOGLE_AD_SOURCES
     and public.fn_lead_txt(p_utm_medium) = any (array['cpc', 'ppc', 'pmax', 'performance_max', 'paid', 'paid_search', 'paidsearch', 'display', 'cpm', 'paid_social', 'paidsocial']) -- _PAID_CHANNEL_MEDIUMS
      then 'Google Ads'
    when public.fn_lead_txt(p_traffic_type) = 'organic' or public.fn_lead_txt(p_utm_source) <> ''
      then 'Orgânico'
    else 'Sem rastreio'
  end
$function$
;

alter function public.fn_lead_canal(text,text,text,text,text,text,text,text,text) owner to postgres;
grant execute on function public.fn_lead_canal(text,text,text,text,text,text,text,text,text)
  to public, anon, authenticated, service_role;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'consulta_ro') then
    revoke execute on function public.fn_lead_canal(text,text,text,text,text,text,text,text,text) from consulta_ro;
  end if;
end $$;

-- religa analytics.dim_lead na fn_lead_canal de 9 args (mesma definição de antes, do bloco e)
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

drop function if exists public.fn_lead_canal_b67f_rollback(text,text,text,text,text,text,text,text,text,text);
drop function if exists public.fn_lead_canal_legado_b67f(text,text,text,text,text,text,text,text,text);

alter table public.leads drop constraint if exists leads_origem_cadastro_check;
alter table public.leads drop column if exists origem_cadastro;

-- ════ b ══════════════════════════════════════════════════════════════════════════════
drop function if exists public.fn_lead_b2b(uuid);
drop index if exists public.idx_leads_segmento;
alter table public.leads drop constraint if exists leads_segmento_check;
alter table public.leads drop column if exists segmento;

-- ════ a ══════════════════════════════════════════════════════════════════════════════
alter table public.deals drop constraint if exists deals_assigned_to_fkey;
drop index if exists public.idx_deals_assigned_to;
do $$
begin
  if (select data_type from information_schema.columns
       where table_schema = 'public' and table_name = 'deals' and column_name = 'assigned_to') = 'uuid' then
    alter table public.deals alter column assigned_to type text using assigned_to::text;
  end if;
end $$;
alter table public.bling_seller_map drop column if exists vendedor_id;
drop function if exists public.fn_vendedor_id(text);
drop table if exists public.vendedores;

-- conferência: nada do b67f sobrou
do $$
begin
  if to_regprocedure('public.fn_lead_canal(text,text,text,text,text,text,text,text,text)') is null
     or to_regprocedure('public.fn_lead_canal(text,text,text,text,text,text,text,text,text,text)') is not null
     or to_regclass('public.vendedores') is not null
     or exists (select 1 from information_schema.columns
                 where table_schema = 'public' and table_name = 'leads'
                   and column_name in ('segmento', 'origem_cadastro')) then
    raise exception 'rollback_migrations: estado final inesperado';
  end if;
  raise notice 'rollback_migrations: ok';
end $$;

commit;
