-- scripts/leads_vendedor/f2_segmento.sql — backfill F2 (cartão b67f1c6b)
--
-- leads.segmento := leads.stage quando o stage é um segmento (atacado, private_label, consumo,
-- exportacao) e o segmento ainda é NULL. Nada mais é inferido (funil, metadata.origem e
-- conversations.stage ficam no relatório relatorios/segmento_inferivel.sql).
--
-- Pré-requisito: migration 20261022b_segmento.sql. Roda ANTES do F3 e antes do push do código.
-- Uso: psql -X -v ON_ERROR_STOP=1 [-v teto=N] -f f2_segmento.sql
-- Idempotente (2ª execução: alterados=0). Desfazer: f2_rollback.sql (antes, desfazer o F3).
-- Só toca leads.segmento: nenhum gatilho reage (trg_update_entered_stage_at só olha stage).

\if :{?teto}
\else
\set teto 2145
\endif

begin;
set local lock_timeout = '5s';
select set_config('b67f.teto', :'teto', true) \g /dev/null

create temp table _alvo on commit drop as
select l.id, l.stage, l.segmento
  from public.leads l
 where l.stage in ('atacado', 'private_label', 'consumo', 'exportacao')
   and l.segmento is null;

do $$
declare
  n int := (select count(*) from _alvo);
  t int := current_setting('b67f.teto')::int;
begin
  raise notice 'F2 alvo=% teto=%', n, t;
  if n > t then
    raise exception 'F2 acima do teto: % > %', n, t;
  end if;
end $$;

create table if not exists public.backup_b67f_f2 (
  id uuid primary key,
  valor_anterior jsonb not null,
  gravado_em timestamptz not null default now()
);
alter table public.backup_b67f_f2 enable row level security;
revoke all on public.backup_b67f_f2 from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on public.backup_b67f_f2 from anon, authenticated';
  end if;
end $$;

insert into public.backup_b67f_f2 (id, valor_anterior)
select id, jsonb_build_object('segmento', segmento, 'stage', stage)
  from _alvo
on conflict (id) do nothing;

with u as (
  update public.leads l
     set segmento = l.stage
    from _alvo a
   where l.id = a.id
     and l.segmento is null
     and l.stage in ('atacado', 'private_label', 'consumo', 'exportacao')
  returning l.segmento
)
select set_config('b67f.alterados', count(*)::text, true) from u \g /dev/null

do $$ begin raise notice 'F2 alterados=%', current_setting('b67f.alterados'); end $$;

select segmento, count(*) as leads
  from public.leads
 where id in (select id from _alvo)
 group by 1 order by 1;

commit;
