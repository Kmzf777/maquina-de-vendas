-- scripts/leads_vendedor/f1_rollback.sql — desfaz o F1 (cartão b67f1c6b) a partir de public.backup_b67f_f1.
--
-- Ordem: dono do funil -> bling_seller_map -> vendedores. Só desfaz o que ainda está com o valor que
-- o F1 gravou (se alguém mudou depois, fica). Vendedor criado pelo F1 só é apagado se nada mais o
-- referencia: rode ANTES o f6_rollback.sql (deals.assigned_to aponta para vendedores).
-- Idempotente: 2ª execução não muda nada. A tabela de backup fica (evidência).
-- Uso: psql -X -v ON_ERROR_STOP=1 -f f1_rollback.sql

begin;
set local lock_timeout = '5s';

create temp table _bk (id text, valor_anterior jsonb) on commit drop;
do $$
begin
  if to_regclass('public.backup_b67f_f1') is null then
    raise notice 'F1 rollback: sem public.backup_b67f_f1, nada a desfazer';
  else
    insert into _bk select id, valor_anterior from public.backup_b67f_f1;
  end if;
end $$;

-- dono do funil
update public.pipelines p
   set owner_user_id = (b.valor_anterior->>'owner_user_id')::uuid
  from _bk b
 where b.valor_anterior->>'tabela' = 'pipelines'
   and p.id = (b.valor_anterior->>'id')::uuid
   and p.owner_user_id = (b.valor_anterior->>'novo')::uuid;

-- mapa Bling: linha inserida pelo F1 sai; vendedor_id preenchido volta ao anterior
delete from public.bling_seller_map m
 using _bk b
 where b.valor_anterior->>'tabela' = 'bling_seller_map'
   and (b.valor_anterior->>'existia')::boolean = false
   and m.user_email = b.valor_anterior->>'user_email'
   and m.account = b.valor_anterior->>'account';

update public.bling_seller_map m
   set vendedor_id = (b.valor_anterior->>'vendedor_id')::uuid
  from _bk b
 where b.valor_anterior->>'tabela' = 'bling_seller_map'
   and (b.valor_anterior->>'existia')::boolean
   and m.user_email = b.valor_anterior->>'user_email'
   and m.account = b.valor_anterior->>'account'
   and m.vendedor_id = (b.valor_anterior->>'novo')::uuid;

-- vendedores criados pelo F1 (FK de deals/bling_seller_map aborta aqui se ainda houver referência)
delete from public.vendedores v
 using _bk b
 where b.valor_anterior->>'tabela' = 'vendedores'
   and (b.valor_anterior->>'existia')::boolean = false
   and v.id = (b.valor_anterior->>'id')::uuid;

do $$
begin
  raise notice 'F1 rollback: vendedores restantes=%', (select count(*) from public.vendedores);
end $$;

commit;
