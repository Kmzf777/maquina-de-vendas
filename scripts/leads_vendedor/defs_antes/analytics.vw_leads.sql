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
