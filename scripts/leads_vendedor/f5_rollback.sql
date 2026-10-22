-- scripts/leads_vendedor/f5_rollback.sql — desfaz o F5 (cartão b67f1c6b)
--
-- Apaga de lead_events SÓ as linhas cujo id está em public.backup_b67f_f5 (as `entrada`
-- inseridas pelo F5). Entradas gravadas depois pelo gatilho ou por outro caminho têm outro id e
-- ficam. Atenção: se o rastreio chegou depois do F5, o gatilho pode ter FUNDIDO o anúncio
-- nesta mesma linha (entrada "Orgânico" -> "Meta Ads"); o rollback apaga a linha mesmo assim
-- (o lead volta a ficar sem entrada, como antes do F5). Idempotente. Não apaga o backup.

begin;
set local lock_timeout = '5s';

do $$
declare
  n int;
begin
  if to_regclass('public.backup_b67f_f5') is null then
    raise notice 'F5 rollback: sem backup_b67f_f5, nada a fazer';
    return;
  end if;

  delete from public.lead_events e
   using public.backup_b67f_f5 b
   where e.id = b.id
     and e.event_type = 'entrada';
  get diagnostics n = row_count;

  raise notice 'F5 rollback apagados=%', n;
end $$;

commit;
