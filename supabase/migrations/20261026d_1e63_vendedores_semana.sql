-- supabase/migrations/20261026d_1e63_vendedores_semana.sql
--
-- Cartão 1e6381fe — spec docs/superpowers/specs/2026-10-26-vendas-receita-d7-design.md, 3.5 (D8).
--
-- analytics.vw_vendedores_semana com as MESMAS colunas, na mesma ordem e com os mesmos tipos.
-- Única mudança: pct_vendas_sem_vendedor_confiavel passa a tratar como confiável o vendedor
-- registrado no CRM (crm) E o vendedor do próprio pedido no Bling (bling_pedido). Com a nova
-- fct_vendas (20261026c), a venda Bling com vendedor no pedido sai como vendedor_fonte='bling_pedido';
-- sem este ajuste o indicador pioraria só pela troca de rótulo. bling_contato, lead_responsavel e sem
-- continuam "não confiáveis" (vendedor inferido ou ausente).
--
-- ORDEM: aplicar DEPOIS de 20261026c_1e63_fct_vendas.sql (os valores bling_pedido só aparecem nela).
-- Base: pg_get_viewdef de produção em 26/10/2026.
-- DONO: em produção a view é de supabase_admin (reloptions security_invoker=true, grant SELECT a
-- consulta_ro, que o CREATE OR REPLACE preserva). CREATE OR REPLACE exige o dono: aplicar como
-- supabase_admin (psql -U supabase_admin), não como postgres.
-- NÃO É APLICADA PELO DEPLOY. Reexecutar é seguro. Depois: SIGUSR1 no PostgREST.
--
-- ═══════════════════════════════ ROLLBACK ═══════════════════════════════════════════
-- Definição de produção em 26/10/2026 (pg_get_viewdef):
--
-- begin;
-- set local lock_timeout = '5s';
-- CREATE OR REPLACE VIEW analytics.vw_vendedores_semana WITH (security_invoker = true) AS
--  WITH rc AS (
--          SELECT r.lead_id,
--             r.repasse_em,
--             r.repasse_data,
--             r.vendedor,
--             r.vendedor_fonte,
--             r.segmento,
--             r.b2b,
--             r.conversation_id,
--             r.primeira_resposta_humana_em,
--             r.minutos_corridos,
--             r.minutos_uteis,
--             r.respondeu,
--             r.minutos_uteis_em_aberto,
--             r.horario_fonte,
--             r.alerta_cobertura,
--             date_trunc('week'::text, r.repasse_data::timestamp with time zone)::date AS semana,
--             (EXISTS ( SELECT 1
--                    FROM analytics.fct_vendas f
--                   WHERE f.lead_id = r.lead_id AND NOT f.cancelada AND f.venda_data >= r.repasse_data AND f.venda_data <= (r.repasse_data +
--                         CASE
--                             WHEN r.b2b THEN 90
--                             ELSE 30
--                         END))) AS virou_venda
--            FROM analytics.vw_resposta_closer r
--         ), u AS (
--          SELECT rc.semana,
--             COALESCE(rc.vendedor, '(sem vendedor)'::text) AS vendedor,
--             count(*) AS repasses_recebidos,
--             count(*) FILTER (WHERE rc.respondeu) AS respondidos,
--             percentile_cont(0.5::double precision) WITHIN GROUP (ORDER BY (rc.minutos_uteis::double precision)) FILTER (WHERE rc.respondeu) AS mediana_minutos_uteis,
--             count(*) FILTER (WHERE rc.virou_venda) AS repasses_com_venda,
--             0::bigint AS vendas,
--             0::numeric AS receita,
--             0::bigint AS vendas_sem_vendedor_confiavel
--            FROM rc
--           GROUP BY rc.semana, (COALESCE(rc.vendedor, '(sem vendedor)'::text))
--         UNION ALL
--          SELECT date_trunc('week'::text, f.venda_data::timestamp with time zone)::date AS date_trunc,
--             COALESCE(f.vendedor, '(sem vendedor)'::text) AS "coalesce",
--             0,
--             0,
--             NULL::double precision AS float8,
--             0,
--             count(*) AS count,
--             sum(f.receita) AS sum,
--             count(*) FILTER (WHERE f.vendedor_fonte <> 'crm'::text) AS count
--            FROM analytics.fct_vendas f
--           WHERE NOT f.cancelada
--           GROUP BY (date_trunc('week'::text, f.venda_data::timestamp with time zone)::date), (COALESCE(f.vendedor, '(sem vendedor)'::text))
--         )
--  SELECT semana,
--     vendedor,
--     sum(repasses_recebidos)::integer AS repasses_recebidos,
--     sum(respondidos)::integer AS respondidos,
--     round(max(mediana_minutos_uteis)::numeric, 1) AS mediana_minutos_uteis,
--     sum(vendas)::integer AS vendas,
--     sum(receita) AS receita,
--     round(sum(receita) / NULLIF(sum(vendas), 0::numeric), 2) AS ticket_medio,
--     round(100.0 * sum(repasses_com_venda) / NULLIF(sum(repasses_recebidos), 0::numeric), 1) AS conversao_repasse_venda,
--     round(100.0 * sum(vendas_sem_vendedor_confiavel) / NULLIF(sum(vendas), 0::numeric), 1) AS pct_vendas_sem_vendedor_confiavel
--    FROM u
--   GROUP BY semana, vendedor;
-- COMMENT ON VIEW analytics.vw_vendedores_semana IS 'Semana (segunda-feira, horário de Brasília) x vendedor. Repasses recebidos = primeiros repasses do lead na semana (D3); respondidos e mediana de minutos úteis vêm de vw_resposta_closer (D4); conversao_repasse_venda = % desses repasses que viraram venda não cancelada em até 30 dias (B2C) ou 90 dias (B2B). Vendas, receita sem frete e ticket vêm de fct_vendas pela data da venda e pelo vendedor da cascata D8; pct_vendas_sem_vendedor_confiavel = % das vendas cujo vendedor não foi registrado no CRM (alerta B1). "(sem vendedor)" agrupa o que não tem vendedor.';
-- commit;
-- ═════════════════════════════ FIM DO ROLLBACK ══════════════════════════════════════

begin;
set local lock_timeout = '5s';

CREATE OR REPLACE VIEW analytics.vw_vendedores_semana WITH (security_invoker = true) AS
 WITH rc AS (
         SELECT r.lead_id,
            r.repasse_em,
            r.repasse_data,
            r.vendedor,
            r.vendedor_fonte,
            r.segmento,
            r.b2b,
            r.conversation_id,
            r.primeira_resposta_humana_em,
            r.minutos_corridos,
            r.minutos_uteis,
            r.respondeu,
            r.minutos_uteis_em_aberto,
            r.horario_fonte,
            r.alerta_cobertura,
            date_trunc('week'::text, r.repasse_data::timestamp with time zone)::date AS semana,
            (EXISTS ( SELECT 1
                   FROM analytics.fct_vendas f
                  WHERE f.lead_id = r.lead_id AND NOT f.cancelada AND f.venda_data >= r.repasse_data AND f.venda_data <= (r.repasse_data +
                        CASE
                            WHEN r.b2b THEN 90
                            ELSE 30
                        END))) AS virou_venda
           FROM analytics.vw_resposta_closer r
        ), u AS (
         SELECT rc.semana,
            COALESCE(rc.vendedor, '(sem vendedor)'::text) AS vendedor,
            count(*) AS repasses_recebidos,
            count(*) FILTER (WHERE rc.respondeu) AS respondidos,
            percentile_cont(0.5::double precision) WITHIN GROUP (ORDER BY (rc.minutos_uteis::double precision)) FILTER (WHERE rc.respondeu) AS mediana_minutos_uteis,
            count(*) FILTER (WHERE rc.virou_venda) AS repasses_com_venda,
            0::bigint AS vendas,
            0::numeric AS receita,
            0::bigint AS vendas_sem_vendedor_confiavel
           FROM rc
          GROUP BY rc.semana, (COALESCE(rc.vendedor, '(sem vendedor)'::text))
        UNION ALL
         SELECT date_trunc('week'::text, f.venda_data::timestamp with time zone)::date AS date_trunc,
            COALESCE(f.vendedor, '(sem vendedor)'::text) AS "coalesce",
            0,
            0,
            NULL::double precision AS float8,
            0,
            count(*) AS count,
            sum(f.receita) AS sum,
            -- Confiável = registrado no CRM (crm) ou vendedor do próprio pedido no Bling (bling_pedido).
            count(*) FILTER (WHERE f.vendedor_fonte <> ALL (ARRAY['crm'::text, 'bling_pedido'::text])) AS count
           FROM analytics.fct_vendas f
          WHERE NOT f.cancelada
          GROUP BY (date_trunc('week'::text, f.venda_data::timestamp with time zone)::date), (COALESCE(f.vendedor, '(sem vendedor)'::text))
        )
 SELECT semana,
    vendedor,
    sum(repasses_recebidos)::integer AS repasses_recebidos,
    sum(respondidos)::integer AS respondidos,
    round(max(mediana_minutos_uteis)::numeric, 1) AS mediana_minutos_uteis,
    sum(vendas)::integer AS vendas,
    sum(receita) AS receita,
    round(sum(receita) / NULLIF(sum(vendas), 0::numeric), 2) AS ticket_medio,
    round(100.0 * sum(repasses_com_venda) / NULLIF(sum(repasses_recebidos), 0::numeric), 1) AS conversao_repasse_venda,
    round(100.0 * sum(vendas_sem_vendedor_confiavel) / NULLIF(sum(vendas), 0::numeric), 1) AS pct_vendas_sem_vendedor_confiavel
   FROM u
  GROUP BY semana, vendedor;

COMMENT ON VIEW analytics.vw_vendedores_semana IS 'Semana (segunda-feira, horário de Brasília) x vendedor. Repasses recebidos = primeiros repasses do lead na semana (D3); respondidos e mediana de minutos úteis vêm de vw_resposta_closer (D4); conversao_repasse_venda = % desses repasses que viraram venda não cancelada em até 30 dias (B2C) ou 90 dias (B2B). Vendas, receita sem frete e ticket vêm de fct_vendas pela data da venda e pelo vendedor da cascata D8; pct_vendas_sem_vendedor_confiavel = % das vendas cujo vendedor não é confiável, isto é, cujo vendedor_fonte não é crm (registrado no CRM) nem bling_pedido (vendedor do próprio pedido no Bling): bling_contato, lead_responsavel e sem contam como não confiáveis. "(sem vendedor)" agrupa o que não tem vendedor.';

commit;

NOTIFY pgrst, 'reload schema';
