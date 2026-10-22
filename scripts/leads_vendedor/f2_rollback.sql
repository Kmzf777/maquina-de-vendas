-- scripts/leads_vendedor/f2_rollback.sql — desfaz o F2 (cartão b67f1c6b)
--
-- Volta leads.segmento ao valor de public.backup_b67f_f2, só onde o segmento ainda é o que o
-- F2 gravou (= stage da época). Recusa se o F3 já rodou e não foi desfeito (sem o stage-segmento
-- e sem o segmento, o lead perderia a informação). Idempotente. Não apaga o backup.

begin;
set local lock_timeout = '5s';

do $$
declare
  n int;
begin
  if to_regclass('public.backup_b67f_f2') is null then
    raise notice 'F2 rollback: sem backup_b67f_f2, nada a fazer';
    return;
  end if;
  if to_regclass('public.backup_b67f_f3') is not null then
    select count(*) into n
      from public.backup_b67f_f3 b
      join public.leads l on l.id = b.id
     where l.stage = b.valor_anterior->>'fase';
    if n > 0 then
      raise exception 'F2 rollback: % lead(s) ainda com a fase do F3 — rodar f3_rollback.sql antes', n;
    end if;
  end if;

  update public.leads l
     set segmento = b.valor_anterior->>'segmento'
    from public.backup_b67f_f2 b
   where l.id = b.id
     and l.segmento is not distinct from b.valor_anterior->>'stage'
     and l.segmento is distinct from b.valor_anterior->>'segmento';
  get diagnostics n = row_count;
  raise notice 'F2 rollback alterados=%', n;
end $$;

commit;
