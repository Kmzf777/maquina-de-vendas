-- Scripts de dados do cartão 1e6381fe (spec 2026-10-26-vendas-receita-d7-design.md, seção 3.1).
-- Rodar à mão pelo psql do supabase_db, um bloco por vez, cada um com o OK do dono.
-- NUNCA mande o arquivo inteiro ao psql. Os blocos de escrita (P0 e ROLLBACK) estão comentados:
-- descomente só o bloco a rodar.
-- Nota 26/10: o P0 já rodou por engano em 26/10 16:56 UTC (1.175 linhas). Na publicação,
-- com o OK do dono, refazer a cópia (drop + create) logo antes do P2, para ela ser do momento do backfill.
-- Ordem: C0 (antes) -> P0 -> A1 -> P2 (comando no worker, fora deste arquivo) -> C1 (depois) -> TETO -> P3.
-- P1 (vendedor do contato) NÃO roda: em 26/10 o detalhe do contato veio com vendedor.id = 0
-- em contatos cujos pedidos têm vendedor. O degrau 2 da D8 fica indisponível na API.

-- ===================================================================
-- C0. Conferência ANTES (só leitura). Guardar a saída.
-- ===================================================================
select bling_account, bling_situacao_nome, status, count(*), round(sum(value)::numeric, 2) valor,
       round(sum(freight)::numeric, 2) frete
  from public.sales where bling_order_id is not null group by 1, 2, 3 order by 1, 4 desc;
-- esperado em 26/10: default/Cancelado/registrada = 47 (R$ 54.740,11)

select bling_account, count(*) total, count(*) filter (where discount is null) nunca_relidos,
       count(*) filter (where freight > 0) com_frete, count(*) filter (where sold_by is null) sem_vendedor
  from public.sales where bling_order_id is not null group by 1 order by 1;
-- esperado em 26/10: default 1.175 / 995 nunca relidos

-- ===================================================================
-- A1. Automações que reagem a venda (só leitura). O import do Bling não chama
-- fire_trigger (só o POST /api/sales chama sale_created), então a releitura não
-- inscreve ninguém. Esta consulta só confirma quais gatilhos ativos dependem de venda.
-- ===================================================================
select c.name, n.config->>'trigger_type' gatilho
  from public.campaign_nodes n join public.campaigns c on c.id = n.campaign_id
 where n.type = 'trigger' and c.status = 'active'
   and n.config->>'trigger_type' in ('sale_created', 'no_sale_in_stage', 'repurchase')
 order by 2, 1;

-- ===================================================================
-- P0. Cópia de segurança antes do backfill (escrita: cria 1 tabela).
-- ===================================================================
-- begin;
-- set local lock_timeout = '5s';
-- create table public.backup_1e63_vendas as
-- select id, status, bling_situacao_id, bling_situacao_nome, value, freight, freight_mode,
--        discount, sold_by, vendedor_fonte, devolucao_parcial, sold_at, now() as copiado_em
--   from public.sales where bling_account = 'default' and bling_order_id is not null;
-- do $$ declare n int; begin
--   select count(*) into n from public.backup_1e63_vendas;
--   if n < 1100 or n > 1300 then
--     raise exception 'backup_1e63_vendas: % linhas, esperado ~1.175', n;
--   end if;
-- end $$;
-- alter table public.backup_1e63_vendas enable row level security;
-- revoke all on public.backup_1e63_vendas from anon, authenticated;
-- commit;

-- ===================================================================
-- P2 (no worker, não é SQL; ver runbook-sync-bling.md seção 1 para $OPS):
--   sg docker -c "$OPS backfill --conta default --desde 2025-08-01 --ate 2026-10-13 --reiniciar --estimar"
--   sg docker -c "$OPS backfill --conta default --desde 2025-08-01 --ate 2026-10-13 --reiniciar" | tee ~/bling_1e63_backfill.log
-- ===================================================================

-- ===================================================================
-- C1. Conferência DEPOIS (só leitura).
-- ===================================================================
-- nenhuma situação de cancelamento com registrada
select bling_account, bling_situacao_nome, status, count(*)
  from public.sales where bling_order_id is not null
   and bling_situacao_nome ilike 'cancelad%' and status <> 'cancelada'
 group by 1, 2, 3;                                                        -- esperado: 0 linhas

-- o que mudou em relação à cópia
select count(*) filter (where s.status = 'cancelada' and b.status <> 'cancelada') viraram_cancelada,
       count(*) filter (where coalesce(s.freight, 0) <> coalesce(b.freight, 0)) frete_mudou,
       count(*) filter (where s.discount is not null and b.discount is null) relidos,
       count(*) filter (where s.sold_by is not null and b.sold_by is null) ganharam_vendedor,
       count(*) filter (where s.value <> b.value) valor_mudou
  from public.sales s join public.backup_1e63_vendas b using (id);

-- ===================================================================
-- TETO. Se passar de 80, PARAR e levar ao dono (e considerar o rollback abaixo).
-- ===================================================================
do $$ declare n int; begin
  select count(*) into n from public.sales s join public.backup_1e63_vendas b using (id)
   where s.status = 'cancelada' and b.status <> 'cancelada';
  if n > 80 then raise exception 'TETO: % vendas viraram cancelada (> 80). Parar e levar ao dono.', n; end if;
  raise notice 'viraram cancelada: %', n;
end $$;

-- ===================================================================
-- ROLLBACK do P2 (escrita; só com OK do dono). Volta as colunas que o
-- backfill mexe nas vendas que mudaram.
-- ===================================================================
-- begin;
-- set local lock_timeout = '5s';
-- update public.sales s set status = b.status, bling_situacao_id = b.bling_situacao_id,
--   bling_situacao_nome = b.bling_situacao_nome, value = b.value, freight = b.freight,
--   freight_mode = b.freight_mode, discount = b.discount, sold_by = b.sold_by,
--   vendedor_fonte = b.vendedor_fonte, devolucao_parcial = b.devolucao_parcial, sold_at = b.sold_at
--   from public.backup_1e63_vendas b
--  where b.id = s.id
--    and (s.status, s.value, s.freight, s.discount, s.sold_by, s.vendedor_fonte, s.sold_at)
--        is distinct from (b.status, b.value, b.freight, b.discount, b.sold_by, b.vendedor_fonte, b.sold_at);
-- commit;

-- ===================================================================
-- P3. Lista ao dono (só leitura): vendas válidas sem vendedor, por conta e motivo.
-- ===================================================================
select s.bling_account,
       case
         when s.sold_at < now() - interval '60 days' and s.vendedor_fonte is null
           then 'mais de 60 dias, sem vendedor no pedido'
         when s.discount is null then 'pedido nunca relido'
         else 'sem vendedor no pedido nem no lead'
       end motivo,
       count(*), round(sum(s.value - coalesce(s.freight, 0))::numeric, 2) receita
  from public.sales s
 where s.bling_order_id is not null and coalesce(s.status, '') <> 'cancelada' and s.sold_by is null
 group by 1, 2 order by 1, 3 desc;

-- vendedores do Bling sem mapa para usuário do CRM (o pedido traz o vendedor, mas ninguém casa)
select v.account, v.id bling_vendedor_id, v.nome, m.user_email
  from public.bling_sellers v
  left join public.bling_seller_map m on m.account = v.account and m.bling_seller_id = v.id
 order by 1, 2;
-- (se a tabela do espelho de vendedores tiver outro nome, conferir em backend/app/bling/sync.py: sync_sellers)
