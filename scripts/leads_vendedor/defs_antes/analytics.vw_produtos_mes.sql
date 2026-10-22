-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: supabase_admin; reloptions: security_invoker=true
-- acl: {supabase_admin=arwdDxtm/supabase_admin,consulta_ro=r/supabase_admin}

create or replace view analytics.vw_produtos_mes with (security_invoker=true) as
 WITH it AS (
         SELECT date_trunc('month'::text, f.venda_data::timestamp with time zone)::date AS mes,
            COALESCE(NULLIF(TRIM(BOTH FROM i.codigo), ''::text), '(sem código) '::text || COALESCE(i.descricao, ''::text)) AS chave,
            NULLIF(TRIM(BOTH FROM i.codigo), ''::text) AS sku,
            COALESCE(bp.nome, i.descricao) AS produto,
            i.quantidade,
            i.total,
            i.sale_id
           FROM sale_items i
             JOIN analytics.fct_vendas f ON f.venda_id = i.sale_id AND NOT f.cancelada
             LEFT JOIN bling_products bp ON bp.id = i.bling_product_id AND bp.account = COALESCE(f.conta_bling, 'default'::text)
        ), agg AS (
         SELECT it.mes,
            it.chave,
            max(it.sku) AS sku,
            max(it.produto) AS produto,
            sum(it.quantidade) AS quantidade,
            sum(it.total) AS receita,
            count(DISTINCT it.sale_id) AS pedidos
           FROM it
          GROUP BY it.mes, it.chave
        ), acum AS (
         SELECT a.mes,
            a.chave,
            a.sku,
            a.produto,
            a.quantidade,
            a.receita,
            a.pedidos,
            sum(a.receita) OVER (PARTITION BY a.mes) AS receita_mes,
            COALESCE(sum(a.receita) OVER (PARTITION BY a.mes ORDER BY a.receita DESC, a.chave ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0::numeric) AS acumulado_anterior
           FROM agg a
        )
 SELECT mes,
    produto,
    sku,
    quantidade,
    receita,
    pedidos::integer AS pedidos,
    round(100.0 * receita / NULLIF(receita_mes, 0::numeric), 2) AS participacao_pct,
        CASE
            WHEN acumulado_anterior < (0.80 * receita_mes) THEN 'A'::text
            WHEN acumulado_anterior < (0.95 * receita_mes) THEN 'B'::text
            ELSE 'C'::text
        END AS curva_abc
   FROM acum x;

comment on view analytics.vw_produtos_mes is 'Produto x mês (data da venda, horário de Brasília), só vendas não canceladas que têm itens (sale_items, ou seja, pedidos ligados ao Bling; venda manual só tem texto e fica fora). receita = soma do total dos itens (sem frete). curva_abc no mês: A até 80% da receita acumulada, B até 95%, C o resto. Sem custo de produto: não há margem.';
grant SELECT on analytics.vw_produtos_mes to consulta_ro;
