-- scripts/leads_vendedor/f7_rollback.sql — desfaz o F7 (cartão b67f1c6b)
--
-- Apaga de lead_events SÓ as linhas cujo id está em public.backup_b67f_f7 (os eventos
-- 'qualificado' inseridos pelo F7). Eventos gravados depois pelo backend (registrar_qualificado)
-- têm outro id e ficam. Depois do rollback, um repasse novo do lead volta a gravar o
-- 'qualificado' normalmente (o dedupe 'qualificado:<lead_id>' fica livre). Idempotente.
-- Não apaga o backup.

begin;
set local lock_timeout = '5s';

do $$
declare
  n int;
begin
  if to_regclass('public.backup_b67f_f7') is null then
    raise notice 'F7 rollback: sem backup_b67f_f7, nada a fazer';
    return;
  end if;

  delete from public.lead_events e
   using public.backup_b67f_f7 b
   where e.id = b.id
     and e.event_type = 'qualificado';
  get diagnostics n = row_count;

  raise notice 'F7 rollback apagados=%', n;
end $$;

commit;
