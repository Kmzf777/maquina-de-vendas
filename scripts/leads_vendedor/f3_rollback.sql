-- scripts/leads_vendedor/f3_rollback.sql — desfaz o F3 (cartão b67f1c6b)
--
-- Volta leads.stage e leads.entered_stage_at ao valor de public.backup_b67f_f3, só onde o lead
-- ainda está na fase que o F3 gravou (lead que andou depois não é mexido). Idempotente.
-- Se a migration 20261022f já entrou, o CHECK de fase impede: dropar antes com
--   ALTER TABLE public.leads DROP CONSTRAINT IF EXISTS leads_stage_fase_check;
-- Não apaga o backup.

begin;
set local lock_timeout = '5s';

do $$
declare
  n int;
begin
  if to_regclass('public.backup_b67f_f3') is null then
    raise notice 'F3 rollback: sem backup_b67f_f3, nada a fazer';
    return;
  end if;
  if exists (select 1 from pg_constraint
              where conrelid = 'public.leads'::regclass and conname = 'leads_stage_fase_check') then
    raise exception 'F3 rollback: o CHECK leads_stage_fase_check (migration 20261022f) existe — dropar antes';
  end if;

  -- 1. stage (o gatilho carimba entered_stage_at = now())
  update public.leads l
     set stage = b.valor_anterior->>'stage'
    from public.backup_b67f_f3 b
   where l.id = b.id
     and l.stage = b.valor_anterior->>'fase';
  get diagnostics n = row_count;

  -- 2. relógio de volta
  update public.leads l
     set entered_stage_at = (b.valor_anterior->>'entered_stage_at')::timestamptz
    from public.backup_b67f_f3 b
   where l.id = b.id
     and l.stage = b.valor_anterior->>'stage'
     and l.entered_stage_at is distinct from (b.valor_anterior->>'entered_stage_at')::timestamptz;

  raise notice 'F3 rollback alterados=%', n;
end $$;

commit;
