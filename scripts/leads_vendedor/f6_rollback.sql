-- scripts/leads_vendedor/f6_rollback.sql — desfaz o F6 (cartão b67f1c6b) a partir de public.backup_b67f_f6.
--
-- Só desfaz o que ainda está com o valor que o F6 gravou ('novo' no backup):
--   deals.assigned_to volta ao anterior; leads.assigned_to volta ao anterior e
--   metadata.handoff.vendedor_id volta ao que era (chave ausente -> removida; null -> null).
--   O resto do handoff (repasse posterior, motivo etc.) não é tocado.
-- Idempotente: 2ª execução não muda nada. A tabela de backup fica (evidência).
-- Rode ANTES do f1_rollback.sql.
-- Uso: psql -X -v ON_ERROR_STOP=1 -f f6_rollback.sql

begin;
set local lock_timeout = '5s';

create temp table _bk (id uuid, valor_anterior jsonb) on commit drop;
do $$
begin
  if to_regclass('public.backup_b67f_f6') is null then
    raise notice 'F6 rollback: sem public.backup_b67f_f6, nada a desfazer';
  else
    insert into _bk select id, valor_anterior from public.backup_b67f_f6;
  end if;
end $$;

update public.deals d
   set assigned_to = (b.valor_anterior->>'assigned_to')::uuid
  from _bk b
 where b.valor_anterior->>'tabela' = 'deals'
   and d.id = b.id
   and d.assigned_to = (b.valor_anterior->>'novo')::uuid;

update public.leads l
   set assigned_to = (b.valor_anterior->>'assigned_to')::uuid
  from _bk b
 where b.valor_anterior->>'tabela' = 'leads'
   and l.id = b.id
   and l.assigned_to = (b.valor_anterior->>'novo')::uuid;

update public.leads l
   set metadata = jsonb_set(
         l.metadata, '{handoff}',
         ((l.metadata->'handoff') - 'vendedor_id')
           || case when b.valor_anterior->'handoff' ? 'vendedor_id'
                   then jsonb_build_object('vendedor_id', b.valor_anterior->'handoff'->'vendedor_id')
                   else '{}'::jsonb end)
  from _bk b
 where b.valor_anterior->>'tabela' = 'leads'
   and l.id = b.id
   and l.metadata->'handoff'->>'vendedor_id' = b.valor_anterior->>'novo';

do $$
begin
  raise notice 'F6 rollback: deals com vendedor=%, leads com vendedor=%',
    (select count(*) from public.deals where assigned_to is not null),
    (select count(*) from public.leads where assigned_to is not null);
end $$;

commit;
