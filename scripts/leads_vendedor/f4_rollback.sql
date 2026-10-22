-- scripts/leads_vendedor/f4_rollback.sql — desfaz o F4 (cartão b67f1c6b)
--
-- Volta leads.origem_cadastro e leads.status ao valor de public.backup_b67f_f4, coluna a coluna,
-- só onde o valor ainda é o que o F4 gravou. Idempotente. Não apaga o backup.

begin;
set local lock_timeout = '5s';

do $$
declare
  n_origem int;
  n_status int;
begin
  if to_regclass('public.backup_b67f_f4') is null then
    raise notice 'F4 rollback: sem backup_b67f_f4, nada a fazer';
    return;
  end if;

  update public.leads l
     set origem_cadastro = b.valor_anterior->>'origem_cadastro'
    from public.backup_b67f_f4 b
   where l.id = b.id
     and l.origem_cadastro = b.valor_anterior->>'nova_origem'
     and l.origem_cadastro is distinct from b.valor_anterior->>'origem_cadastro';
  get diagnostics n_origem = row_count;

  update public.leads l
     set status = b.valor_anterior->>'status'
    from public.backup_b67f_f4 b
   where l.id = b.id
     and l.status is not distinct from b.valor_anterior->>'novo_status'
     and l.status is distinct from b.valor_anterior->>'status';
  get diagnostics n_status = row_count;

  raise notice 'F4 rollback alterados origem=% status=%', n_origem, n_status;
end $$;

commit;
