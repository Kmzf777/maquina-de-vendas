-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: supabase_admin; reloptions: security_invoker=true
-- acl: {supabase_admin=arwdDxtm/supabase_admin,consulta_ro=r/supabase_admin}

create or replace view analytics.vw_clientes with (security_invoker=true) as
 WITH v AS (
         SELECT f.lead_id,
            f.venda_data,
            f.receita
           FROM analytics.fct_vendas f
          WHERE NOT f.cancelada
        ), agg AS (
         SELECT v.lead_id,
            min(v.venda_data) AS primeira_compra,
            max(v.venda_data) AS ultima_compra,
            count(*) AS pedidos,
            sum(v.receita) AS receita_total
           FROM v
          GROUP BY v.lead_id
        ), intervalos AS (
         SELECT d.lead_id,
            d.venda_data - lag(d.venda_data) OVER (PARTITION BY d.lead_id ORDER BY d.venda_data) AS intervalo
           FROM ( SELECT DISTINCT v.lead_id,
                    v.venda_data
                   FROM v) d
        ), ciclo AS (
         SELECT i.lead_id,
            percentile_cont(0.5::double precision) WITHIN GROUP (ORDER BY (i.intervalo::double precision)) AS ciclo
           FROM intervalos i
          WHERE i.intervalo IS NOT NULL
          GROUP BY i.lead_id
        ), base AS (
         SELECT a.lead_id,
            a.primeira_compra,
            a.ultima_compra,
            a.pedidos,
            a.receita_total,
            COALESCE(dl.b2b, false) AS b2b,
            dl.segmento,
            dl.vendedor_responsavel,
            (now() AT TIME ZONE 'America/Sao_Paulo'::text)::date - a.ultima_compra AS dias_desde_ultima,
            round(c.ciclo::numeric, 1) AS ciclo_mediano_dias
           FROM agg a
             LEFT JOIN ciclo c ON c.lead_id = a.lead_id
             LEFT JOIN analytics.dim_lead dl ON dl.lead_id = a.lead_id
        ), rfm AS (
         SELECT b.lead_id,
            b.primeira_compra,
            b.ultima_compra,
            b.pedidos,
            b.receita_total,
            b.b2b,
            b.segmento,
            b.vendedor_responsavel,
            b.dias_desde_ultima,
            b.ciclo_mediano_dias,
            LEAST(5::double precision, 1::double precision + floor(percent_rank() OVER (PARTITION BY b.b2b ORDER BY b.dias_desde_ultima DESC) * 5::double precision))::integer AS rfm_r,
            LEAST(5::double precision, 1::double precision + floor(percent_rank() OVER (PARTITION BY b.b2b ORDER BY b.pedidos) * 5::double precision))::integer AS rfm_f,
            LEAST(5::double precision, 1::double precision + floor(percent_rank() OVER (PARTITION BY b.b2b ORDER BY b.receita_total) * 5::double precision))::integer AS rfm_m
           FROM base b
        )
 SELECT lead_id,
    b2b,
    segmento,
    vendedor_responsavel,
    primeira_compra,
    ultima_compra,
    pedidos::integer AS pedidos,
    receita_total,
    round(receita_total / NULLIF(pedidos, 0)::numeric, 2) AS ticket_medio,
    dias_desde_ultima,
    ciclo_mediano_dias,
    rfm_r,
    rfm_f,
    rfm_m,
        CASE
            WHEN rfm_r >= 4 AND rfm_f >= 4 THEN 'campeao'::text
            WHEN rfm_r >= 3 AND rfm_f >= 3 THEN 'fiel'::text
            WHEN rfm_r >= 4 THEN 'recente'::text
            WHEN rfm_r <= 2 AND rfm_f >= 3 THEN 'em_risco'::text
            WHEN rfm_r <= 2 THEN 'hibernando'::text
            ELSE 'precisa_atencao'::text
        END AS rfm_segmento,
        CASE
            WHEN NOT b2b THEN NULL::text
            WHEN pedidos >= 3 AND ciclo_mediano_dias IS NOT NULL THEN
            CASE
                WHEN dias_desde_ultima::numeric <= (2::numeric * ciclo_mediano_dias) THEN 'ativo'::text
                WHEN dias_desde_ultima::numeric <= GREATEST(4::numeric * ciclo_mediano_dias, 180::numeric) THEN 'em_risco'::text
                ELSE 'inativo'::text
            END
            ELSE
            CASE
                WHEN dias_desde_ultima <= 60 THEN 'ativo'::text
                WHEN dias_desde_ultima <= 180 THEN 'em_risco'::text
                ELSE 'inativo'::text
            END
        END AS status_b2b,
        CASE
            WHEN NOT b2b THEN NULL::text
            WHEN pedidos >= 3 AND ciclo_mediano_dias IS NOT NULL THEN 'ciclo_proprio'::text
            ELSE 'regra_fixa_60_180'::text
        END AS status_b2b_regra
   FROM rfm r;

comment on view analytics.vw_clientes is 'Um cliente (lead com ao menos uma venda não cancelada) por linha: primeira e última compra, pedidos, receita sem frete, ticket, dias desde a última compra, ciclo mediano de recompra (mediana dos dias entre datas de compra distintas), RFM em quintis 1-5 calculados separadamente para B2B e B2C (5 = melhor) e status_b2b (só B2B): com 3+ pedidos, ativo até 2x o ciclo mediano, em_risco acima disso e inativo acima de max(4x o ciclo, 180 dias); com menos de 3 pedidos, ativo até 60 dias, em_risco até 180, inativo depois. Histórico do Bling: 12 meses, só a conta default.';
grant SELECT on analytics.vw_clientes to consulta_ro;
