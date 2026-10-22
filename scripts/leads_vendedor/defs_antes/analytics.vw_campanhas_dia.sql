-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: supabase_admin; reloptions: security_invoker=true
-- acl: {supabase_admin=arwdDxtm/supabase_admin,consulta_ro=r/supabase_admin}

create or replace view analytics.vw_campanhas_dia with (security_invoker=true) as
 WITH u AS (
         SELECT a.date AS data,
            a.platform AS plataforma,
            a.campaign_id AS campanha_id,
            a.campaign_name AS campanha,
            1 AS prio,
            a.cost AS gasto,
            0 AS leads,
            0 AS repasses,
            0 AS vendas,
            0::numeric AS receita
           FROM ad_spend a
        UNION ALL
         SELECT l.entrada_data,
            l.plataforma_primeiro_toque,
            l.campanha_id_primeiro_toque,
            l.campanha_primeiro_toque,
            2,
            0,
            1,
            0,
            0,
            0
           FROM analytics.vw_leads l
          WHERE l.eh_lead_marketing
        UNION ALL
         SELECT r.repasse_data,
            l.plataforma_primeiro_toque,
            l.campanha_id_primeiro_toque,
            l.campanha_primeiro_toque,
            2,
            0,
            0,
            1,
            0,
            0
           FROM analytics.vw_repasses r
             JOIN analytics.vw_leads l ON l.lead_id = r.lead_id
          WHERE r.ordem = 1 AND l.eh_lead_marketing
        UNION ALL
         SELECT v.venda_data,
            v.plataforma_primeiro_toque,
            v.campanha_id_primeiro_toque,
            v.campanha_primeiro_toque,
            2,
            0,
            0,
            0,
            1,
            v.receita
           FROM analytics.fct_vendas v
          WHERE NOT v.cancelada AND v.dentro_janela_atribuicao AND v.eh_lead_marketing
        )
 SELECT data,
    plataforma,
    campanha_id,
    COALESCE((array_agg(campanha ORDER BY prio) FILTER (WHERE campanha IS NOT NULL))[1],
        CASE
            WHEN plataforma = ANY (ARRAY['meta'::text, 'google'::text]) THEN '(não atribuído)'::text
            ELSE '(sem campanha)'::text
        END) AS campanha,
    sum(gasto) AS gasto,
    sum(leads)::integer AS leads_marketing,
    sum(repasses)::integer AS repasses,
    sum(vendas)::integer AS vendas,
    sum(receita) AS receita,
    round(sum(gasto) / NULLIF(sum(leads), 0)::numeric, 2) AS cpl,
    round(sum(gasto) / NULLIF(sum(repasses), 0)::numeric, 2) AS custo_por_repasse,
    round(sum(receita) / NULLIF(sum(gasto), 0::numeric), 2) AS roas
   FROM u
  GROUP BY data, plataforma, campanha_id;

comment on view analytics.vw_campanhas_dia is 'Uma linha por plataforma x campanha x data: gasto (ad_spend, BRL), leads de marketing (D1, pela data da entrada), primeiros repasses ao closer (D3, pela data do repasse), vendas e receita sem frete (D7) atribuídas pelo primeiro toque dentro da janela D10, pela data da venda. Só leads de marketing contam (importados do Bling e quem já era cliente ficam fora). Para períodos, some gasto/leads/receita e recalcule CPL e ROAS (não faça média das taxas diárias). campanha "(não atribuído)" = lead pago cuja campanha não foi identificada.';
grant SELECT on analytics.vw_campanhas_dia to consulta_ro;
