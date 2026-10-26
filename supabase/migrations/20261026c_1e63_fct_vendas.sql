-- supabase/migrations/20261026c_1e63_fct_vendas.sql
--
-- Cartão 1e6381fe — spec docs/superpowers/specs/2026-10-26-vendas-receita-d7-design.md, 3.5 (D7, D8).
--
-- analytics.fct_vendas com as MESMAS colunas, na mesma ordem e com os mesmos tipos (CREATE OR REPLACE
-- VIEW não derruba vw_vendedores_semana, vw_clientes, vw_funil_mes, vw_produtos_mes, vw_campanhas_dia,
-- vw_disparos nem o grant de consulta_ro). Não lê tabela nova: não precisa de GRANT novo.
--   - cancelada = coalesce(status,'') = 'cancelada'. Sai o contorno por nome de situação do Bling:
--     "Em devolução" deixa de ser cancelada (D7; a venda segue com devolucao_parcial).
--   - vendedor = sold_by -> dim_vendedor (e-mail). vendedor_fonte = sales.vendedor_fonte gravado
--     (bling_pedido, bling_contato; lead_assigned vira lead_responsavel; crm/manual viram crm), ou
--     crm quando há sold_by sem fonte (vendas crm/manual), ou sem quando não há vendedor.
--     Saem o LATERAL pelo vendedor do contato e o responsável do lead sem o limite de 60 dias (a
--     cascata D8 já roda no import e grava sold_by + vendedor_fonte).
--   - alerta_frete só para pedido Bling nunca relido (origin='bling' and discount is null): o código
--     novo sempre grava discount, então frete 0 com discount gravado é frete 0 de verdade.
--   - alerta_vendedor com os textos novos; COMMENT atualizado.
--   - dim_lead continua no join (b2b, segmento, marketing, entrada, primeiro toque).
--
-- Base: pg_get_viewdef de produção em 26/10 (igual a central-claude/sql/analytics/001_analytics.sql:467).
-- DONO: em produção a view é de supabase_admin; CREATE OR REPLACE exige o dono. Aplicar como
-- supabase_admin (psql -U supabase_admin), não como postgres.
-- NÃO É APLICADA PELO DEPLOY. Reexecutar é seguro. Depois: SIGUSR1 no PostgREST.
--
-- ═══════════════════════════════ ROLLBACK ═══════════════════════════════════════════
-- Definição de produção em 26/10/2026 (pg_get_viewdef, reloptions security_invoker=true, dono
-- supabase_admin, grant SELECT a consulta_ro, que o CREATE OR REPLACE preserva):
--
-- begin;
-- set local lock_timeout = '5s';
-- CREATE OR REPLACE VIEW analytics.fct_vendas WITH (security_invoker = true) AS
--  WITH s AS (
--          SELECT s.id,
--             s.lead_id,
--             s.sold_at,
--             s.value,
--             s.product,
--             s.sold_by,
--             s.deal_id,
--             s.conversation_id,
--             s.notes,
--             s.created_at,
--             s.bling_order_id,
--             s.bling_order_number,
--             s.bling_situacao_id,
--             s.bling_situacao_nome,
--             s.bling_event_date,
--             s.origin,
--             s.status,
--             s.payment_method_id,
--             s.payment_terms,
--             s.bling_divergent,
--             s.bling_divergence,
--             s.sold_by_source,
--             s.sold_by_anterior,
--             s.bling_account,
--             s.freight,
--             s.freight_mode,
--             COALESCE(s.status, ''::text) = 'cancelada'::text OR COALESCE(s.bling_situacao_nome, ''::text) ~~* 'cancelad%'::text OR COALESCE(s.bling_situacao_nome, ''::text) ~~* '%devolu%'::text AS cancelada,
--             (s.sold_at AT TIME ZONE 'America/Sao_Paulo'::text)::date AS venda_data
--            FROM sales s
--         ), v AS (
--          SELECT s.id,
--             s.lead_id,
--             s.sold_at,
--             s.value,
--             s.product,
--             s.sold_by,
--             s.deal_id,
--             s.conversation_id,
--             s.notes,
--             s.created_at,
--             s.bling_order_id,
--             s.bling_order_number,
--             s.bling_situacao_id,
--             s.bling_situacao_nome,
--             s.bling_event_date,
--             s.origin,
--             s.status,
--             s.payment_method_id,
--             s.payment_terms,
--             s.bling_divergent,
--             s.bling_divergence,
--             s.sold_by_source,
--             s.sold_by_anterior,
--             s.bling_account,
--             s.freight,
--             s.freight_mode,
--             s.cancelada,
--             s.venda_data,
--             dvc.vendedor AS vendedor_crm,
--             bc.vendedor AS vendedor_contato,
--             dl.vendedor_responsavel,
--             dl.b2b,
--             dl.segmento,
--             dl.eh_lead_marketing,
--             dl.entrada_em,
--             dl.entrada_data,
--             dl.plataforma_primeiro_toque,
--             dl.campanha_id_primeiro_toque,
--             dl.campanha_primeiro_toque
--            FROM s
--              LEFT JOIN analytics.dim_lead dl ON dl.lead_id = s.lead_id
--              LEFT JOIN analytics.dim_vendedor dvc ON NULLIF(TRIM(BOTH FROM s.sold_by), ''::text) IS NOT NULL AND (lower(TRIM(BOTH FROM s.sold_by)) = ANY (dvc.emails))
--              LEFT JOIN LATERAL ( SELECT dv.vendedor
--                    FROM ( SELECT c0.id,
--                             c0.account,
--                             c0.vendedor_id,
--                             1 AS prio
--                            FROM leads l0
--                              JOIN bling_contacts c0 ON c0.id = l0.bling_contact_id
--                           WHERE l0.id = s.lead_id
--                         UNION ALL
--                          SELECT c1.id,
--                             c1.account,
--                             c1.vendedor_id,
--                             2
--                            FROM lead_bling_contacts lbc
--                              JOIN bling_contacts c1 ON c1.id = lbc.bling_contact_id AND c1.account = lbc.account
--                           WHERE lbc.lead_id = s.lead_id) c
--                      JOIN bling_seller_map sm ON sm.bling_seller_id = c.vendedor_id AND sm.account = c.account
--                      JOIN analytics.dim_vendedor dv ON lower(TRIM(BOTH FROM sm.user_email)) = ANY (dv.emails)
--                   WHERE c.account = COALESCE(s.bling_account, 'default'::text)
--                   ORDER BY c.prio, c.id DESC, dv.vendedor_chave
--                  LIMIT 1) bc ON true
--         )
--  SELECT id AS venda_id,
--     lead_id,
--     sold_at AS vendida_em,
--     venda_data,
--     origin AS origem,
--     bling_account AS conta_bling,
--     status,
--     bling_situacao_nome AS situacao_bling,
--     cancelada,
--     value AS valor_bruto,
--     COALESCE(freight, 0::numeric) AS frete,
--         CASE
--             WHEN cancelada THEN 0::numeric
--             ELSE value - COALESCE(freight, 0::numeric)
--         END AS receita,
--     COALESCE(vendedor_crm, vendedor_contato, vendedor_responsavel) AS vendedor,
--         CASE
--             WHEN vendedor_crm IS NOT NULL THEN 'crm'::text
--             WHEN vendedor_contato IS NOT NULL THEN 'bling_contato'::text
--             WHEN vendedor_responsavel IS NOT NULL THEN 'lead_responsavel'::text
--             ELSE 'sem'::text
--         END AS vendedor_fonte,
--     COALESCE(b2b, false) AS b2b,
--     segmento,
--     COALESCE(eh_lead_marketing, false) AS eh_lead_marketing,
--     plataforma_primeiro_toque,
--     campanha_id_primeiro_toque,
--     campanha_primeiro_toque,
--     COALESCE(entrada_data IS NOT NULL AND venda_data >= entrada_data AND venda_data <= (entrada_data +
--         CASE
--             WHEN b2b THEN 90
--             ELSE 30
--         END), false) AS dentro_janela_atribuicao,
--         CASE
--             WHEN entrada_data IS NOT NULL THEN venda_data - entrada_data
--             ELSE NULL::integer
--         END AS dias_desde_entrada,
--     (EXISTS ( SELECT 1
--            FROM sale_items i
--           WHERE i.sale_id = v.id)) AS tem_itens,
--     deal_id IS NOT NULL AS tem_deal,
--         CASE
--             WHEN NOT cancelada THEN row_number() OVER (PARTITION BY lead_id, cancelada ORDER BY sold_at, id)::integer
--             ELSE NULL::integer
--         END AS numero_compra,
--         CASE
--             WHEN origin = 'bling'::text AND COALESCE(freight, 0::numeric) = 0::numeric THEN 'venda Bling sem frete registrado: a receita pode incluir o frete'::text
--             ELSE NULL::text
--         END AS alerta_frete,
--         CASE
--             WHEN vendedor_crm IS NOT NULL THEN NULL::text
--             WHEN vendedor_contato IS NOT NULL THEN 'vendedor inferido pelo vendedor do contato no Bling'::text
--             WHEN vendedor_responsavel IS NOT NULL THEN 'vendedor inferido pelo responsável atual do lead'::text
--             ELSE 'venda sem vendedor: o import do Bling não grava o vendedor do pedido'::text
--         END AS alerta_vendedor
--    FROM v;
-- COMMENT ON VIEW analytics.fct_vendas IS 'Uma linha por venda (inclusive canceladas; filtre NOT cancelada). D7: receita = valor - frete, zero se cancelada; cancelada = status cancelada OU situação Bling de cancelamento/devolução (contorno do B10). D8: vendedor por sold_by (crm) > vendedor do contato no Bling via bling_seller_map (bling_contato) > responsável do lead (lead_responsavel) > sem; o vendedor do pedido Bling não é gravado (B1). D10: dentro_janela_atribuicao = venda entre a entrada e 30 dias (B2C) ou 90 dias (B2B) depois. Alertas: alerta_frete (venda Bling sem frete registrado) e alerta_vendedor (vendedor não registrado na venda).';
-- commit;
-- ═════════════════════════════ FIM DO ROLLBACK ══════════════════════════════════════

begin;
set local lock_timeout = '5s';

CREATE OR REPLACE VIEW analytics.fct_vendas WITH (security_invoker = true) AS
 WITH s AS (
         SELECT s.id,
            s.lead_id,
            s.sold_at,
            s.value,
            s.sold_by,
            s.deal_id,
            s.bling_situacao_nome,
            s.origin,
            s.status,
            s.bling_account,
            s.freight,
            s.discount,
            s.vendedor_fonte AS fonte_gravada,
            -- D7: só o status. "Em devolução" segue venda (devolucao_parcial).
            COALESCE(s.status, ''::text) = 'cancelada'::text AS cancelada,
            (s.sold_at AT TIME ZONE 'America/Sao_Paulo'::text)::date AS venda_data
           FROM public.sales s
        ), v AS (
         SELECT s.*,
            dv.vendedor,
            NULLIF(TRIM(BOTH FROM s.sold_by), ''::text) IS NOT NULL AS tem_sold_by,
            dl.b2b,
            dl.segmento,
            dl.eh_lead_marketing,
            dl.entrada_data,
            dl.plataforma_primeiro_toque,
            dl.campanha_id_primeiro_toque,
            dl.campanha_primeiro_toque
           FROM s
             LEFT JOIN analytics.dim_lead dl ON dl.lead_id = s.lead_id
             -- D8: o vendedor é o sold_by gravado pela cascata no import (ou pelo CRM).
             LEFT JOIN analytics.dim_vendedor dv ON NULLIF(TRIM(BOTH FROM s.sold_by), ''::text) IS NOT NULL
                   AND lower(TRIM(BOTH FROM s.sold_by)) = ANY (dv.emails)
        )
 SELECT id AS venda_id,
    lead_id,
    sold_at AS vendida_em,
    venda_data,
    origin AS origem,
    bling_account AS conta_bling,
    status,
    bling_situacao_nome AS situacao_bling,
    cancelada,
    value AS valor_bruto,
    COALESCE(freight, 0::numeric) AS frete,
        CASE
            WHEN cancelada THEN 0::numeric
            ELSE value - COALESCE(freight, 0::numeric)
        END AS receita,
    vendedor,
        CASE
            WHEN vendedor IS NULL THEN 'sem'::text
            WHEN fonte_gravada = 'lead_assigned'::text THEN 'lead_responsavel'::text
            WHEN fonte_gravada IN ('bling_pedido'::text, 'bling_contato'::text) THEN fonte_gravada
            -- crm/manual gravados, ou sold_by sem fonte (vendas crm/manual): registrado no CRM.
            ELSE 'crm'::text
        END AS vendedor_fonte,
    COALESCE(b2b, false) AS b2b,
    segmento,
    COALESCE(eh_lead_marketing, false) AS eh_lead_marketing,
    plataforma_primeiro_toque,
    campanha_id_primeiro_toque,
    campanha_primeiro_toque,
    COALESCE(entrada_data IS NOT NULL AND venda_data >= entrada_data AND venda_data <= (entrada_data +
        CASE
            WHEN b2b THEN 90
            ELSE 30
        END), false) AS dentro_janela_atribuicao,
        CASE
            WHEN entrada_data IS NOT NULL THEN venda_data - entrada_data
            ELSE NULL::integer
        END AS dias_desde_entrada,
    (EXISTS ( SELECT 1
           FROM public.sale_items i
          WHERE i.sale_id = v.id)) AS tem_itens,
    deal_id IS NOT NULL AS tem_deal,
        CASE
            WHEN NOT cancelada THEN row_number() OVER (PARTITION BY lead_id, cancelada ORDER BY sold_at, id)::integer
            ELSE NULL::integer
        END AS numero_compra,
        CASE
            -- O import novo sempre grava discount: nulo = pedido Bling nunca relido.
            WHEN origin = 'bling'::text AND discount IS NULL THEN 'pedido Bling nunca relido (desconto e frete não gravados): a receita pode incluir o frete'::text
            ELSE NULL::text
        END AS alerta_frete,
        CASE
            WHEN vendedor IS NULL AND tem_sold_by THEN 'sold_by sem vendedor cadastrado (vendedores/bling_seller_map)'::text
            WHEN vendedor IS NULL THEN 'pedido sem vendedor no Bling e sem fonte na cascata D8'::text
            WHEN fonte_gravada = 'lead_assigned'::text THEN 'vendedor pelo responsável do lead (cascata D8, lead_assigned)'::text
            WHEN fonte_gravada = 'bling_contato'::text THEN 'vendedor pelo vendedor do contato no Bling (cascata D8)'::text
            ELSE NULL::text
        END AS alerta_vendedor
   FROM v;

COMMENT ON VIEW analytics.fct_vendas IS 'Uma linha por venda (inclusive canceladas; filtre NOT cancelada). D7: receita = valor - frete, zero se cancelada; cancelada = status cancelada (situação Cancelado do Bling); "Em devolução" continua venda. venda_data = dia em Brasília. D8: vendedor = sold_by casado com dim_vendedor por e-mail; vendedor_fonte = a fonte gravada na venda pela cascata do import: bling_pedido (vendedor do pedido no Bling), bling_contato (vendedor do contato), lead_responsavel (responsável do lead, até 60 dias), crm (registrado no CRM) ou sem. D10: dentro_janela_atribuicao = venda entre a entrada e 30 dias (B2C) ou 90 dias (B2B) depois. Alertas: alerta_frete (pedido Bling nunca relido, sem desconto/frete gravados) e alerta_vendedor (vendedor inferido ou ausente).';

commit;

NOTIFY pgrst, 'reload schema';
