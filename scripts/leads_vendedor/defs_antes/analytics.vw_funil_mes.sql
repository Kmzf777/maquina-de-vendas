-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: supabase_admin; reloptions: security_invoker=true
-- acl: {supabase_admin=arwdDxtm/supabase_admin,consulta_ro=r/supabase_admin}

create or replace view analytics.vw_funil_mes with (security_invoker=true) as
 WITH v AS (
         SELECT f.lead_id,
            bool_or(f.tem_deal) AS com_deal,
            sum(f.receita) AS receita
           FROM analytics.fct_vendas f
          WHERE NOT f.cancelada AND f.dentro_janela_atribuicao
          GROUP BY f.lead_id
        )
 SELECT date_trunc('month'::text, l.entrada_data::timestamp with time zone)::date AS mes,
    l.b2b,
    count(*)::integer AS leads_marketing,
    count(*) FILTER (WHERE l.qualificado)::integer AS qualificados,
    count(*) FILTER (WHERE l.repassado)::integer AS repassados,
    count(*) FILTER (WHERE v.com_deal)::integer AS com_venda,
    count(v.lead_id)::integer AS com_venda_qualquer,
    COALESCE(sum(v.receita), 0::numeric) AS receita,
    round(100.0 * count(*) FILTER (WHERE l.qualificado)::numeric / NULLIF(count(*), 0)::numeric, 1) AS taxa_qualificacao_pct,
    round(100.0 * count(*) FILTER (WHERE l.repassado)::numeric / NULLIF(count(*), 0)::numeric, 1) AS taxa_repasse_pct,
    round(100.0 * count(*) FILTER (WHERE v.com_deal AND l.repassado)::numeric / NULLIF(count(*) FILTER (WHERE l.repassado), 0)::numeric, 1) AS taxa_venda_sobre_repasse_pct,
    round(100.0 * count(*) FILTER (WHERE v.com_deal)::numeric / NULLIF(count(*), 0)::numeric, 1) AS taxa_venda_sobre_lead_pct
   FROM analytics.vw_leads l
     LEFT JOIN v ON v.lead_id = l.lead_id
  WHERE l.eh_lead_marketing
  GROUP BY (date_trunc('month'::text, l.entrada_data::timestamp with time zone)::date), l.b2b;

comment on view analytics.vw_funil_mes is 'Funil por coorte: mês da entrada x B2B/B2C, só leads de marketing (D1). Conta quantos desses leads foram qualificados (D2), repassados ao closer (D3) e compraram dentro da janela D10. com_venda segue D7 (só venda ligada a card/deal conta na conversão do funil); com_venda_qualquer inclui vendas sem deal (ex.: pedidos do Bling). receita = receita sem frete das vendas na janela, com ou sem deal. Taxas em %. Meses recentes ainda estão amadurecendo.';
grant SELECT on analytics.vw_funil_mes to consulta_ro;
