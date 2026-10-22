-- scripts/leads_vendedor/f3_fase.sql — backfill F3 (cartão b67f1c6b)
--
-- leads.stage vira FASE:
--   atacado | private_label | consumo | exportacao  -> qualificando
--   secretaria                                      -> triagem
--   contato | negociacao | ja_chamado               -> qualificando
-- Fases válidas depois disto: pending, novo, triagem, qualificando, perdido.
--
-- Pré-requisito: F2 (confere: todo lead com stage-segmento tem segmento igual; senão aborta).
-- Depois: aplicar supabase/migrations/20261022f_stage_fase_check.sql (CHECK de fase).
-- Uso: psql -X -v ON_ERROR_STOP=1 [-v teto=N] -f f3_fase.sql
-- Idempotente. Desfazer: f3_rollback.sql (se a migration f já entrou, dropar o CHECK antes).
--
-- Gatilhos em leads (conferido em produção em 22/10/2026, pg_trigger):
--   trg_update_entered_stage_at (BEFORE UPDATE) faz entered_stage_at = now() quando stage muda.
--     Não grava evento nem move card, mas zeraria o relógio do gatilho de automação
--     stage_stagnation. Por isso a 2ª instrução devolve entered_stage_at ao valor de antes
--     (sem mudar stage, o gatilho não carimba de novo).
--   trg_lead_events_leads_entrada é AFTER INSERT OR UPDATE OF ctwa_clid, gclid, ... : não
--     dispara com stage/entered_stage_at.
-- É UPDATE direto: as automações stage_enter do Python NÃO rodam (de propósito).

\if :{?teto}
\else
\set teto 2616
\endif

begin;
set local lock_timeout = '5s';
select set_config('b67f.teto', :'teto', true) \g /dev/null

-- F2 rodou?
do $$
declare
  n int;
begin
  select count(*) into n
    from public.leads
   where stage in ('atacado', 'private_label', 'consumo', 'exportacao')
     and segmento is distinct from stage;
  if n > 0 then
    raise exception 'F3: % lead(s) com stage-segmento sem segmento igual — rodar F2 (f2_segmento.sql) antes', n;
  end if;
end $$;

create temp table _alvo on commit drop as
select l.id,
       l.stage,
       l.entered_stage_at,
       case when l.stage = 'secretaria' then 'triagem' else 'qualificando' end as fase
  from public.leads l
 where l.stage in ('atacado', 'private_label', 'consumo', 'exportacao',
                   'secretaria', 'contato', 'negociacao', 'ja_chamado');

do $$
declare
  n int := (select count(*) from _alvo);
  t int := current_setting('b67f.teto')::int;
begin
  raise notice 'F3 alvo=% teto=%', n, t;
  if n > t then
    raise exception 'F3 acima do teto: % > %', n, t;
  end if;
end $$;

create table if not exists public.backup_b67f_f3 (
  id uuid primary key,
  valor_anterior jsonb not null,
  gravado_em timestamptz not null default now()
);
alter table public.backup_b67f_f3 enable row level security;
revoke all on public.backup_b67f_f3 from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on public.backup_b67f_f3 from anon, authenticated';
  end if;
end $$;

insert into public.backup_b67f_f3 (id, valor_anterior)
select id, jsonb_build_object('stage', stage, 'entered_stage_at', entered_stage_at, 'fase', fase)
  from _alvo
on conflict (id) do nothing;

-- 1. a fase (o gatilho carimba entered_stage_at = now())
with u as (
  update public.leads l
     set stage = a.fase
    from _alvo a
   where l.id = a.id
     and l.stage = a.stage
  returning l.id
)
select set_config('b67f.alterados', count(*)::text, true) from u \g /dev/null

-- 2. devolve o relógio (stage não muda: o gatilho não age)
update public.leads l
   set entered_stage_at = a.entered_stage_at
  from _alvo a
 where l.id = a.id
   and l.stage = a.fase
   and l.entered_stage_at is distinct from a.entered_stage_at;

do $$
declare
  n int;
begin
  select count(*) into n
    from _alvo a join public.leads l on l.id = a.id
   where l.stage = a.fase and l.entered_stage_at is distinct from a.entered_stage_at;
  if n > 0 then
    raise exception 'F3: % lead(s) perderam entered_stage_at — o gatilho sobrescreveu', n;
  end if;
  raise notice 'F3 alterados=%', current_setting('b67f.alterados');
end $$;

select a.stage as stage_antigo, l.stage as fase, count(*) as leads
  from _alvo a join public.leads l on l.id = a.id
 group by 1, 2 order by 1;

-- O que ainda impede a migration f (deve sair vazio):
select coalesce(stage, 'NULL') as stage_fora_das_fases, count(*) as leads
  from public.leads
 where stage is null or stage not in ('pending', 'novo', 'triagem', 'qualificando', 'perdido')
 group by 1;

commit;
