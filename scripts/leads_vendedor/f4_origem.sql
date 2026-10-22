-- scripts/leads_vendedor/f4_origem.sql — backfill F4 (cartão b67f1c6b)
--
-- leads.origem_cadastro, só onde ainda está no padrão 'inbound':
--   channel = 'bling' ou metadata->>'origem' = 'bling_webhook'  -> 'bling_import'
--   metadata->>'origem' = 'reativacao_bling'                    -> 'reativacao_import'
-- leads.status 'ativo' (grafia do Bling antigo) -> 'active'.
--
-- Pré-requisito: migration 20261022c_origem_cadastro.sql. Roda DEPOIS do push (ordem da spec).
-- Uso: psql -X -v ON_ERROR_STOP=1 [-v teto=N] -f f4_origem.sql
-- Idempotente. Desfazer: f4_rollback.sql.
-- O gatilho de entrada é AFTER ... UPDATE OF ctwa_clid, gclid, ...: não reage a estas colunas.

\if :{?teto}
\else
\set teto 1533
\endif

begin;
set local lock_timeout = '5s';
select set_config('b67f.teto', :'teto', true) \g /dev/null

create temp table _alvo on commit drop as
select x.*
  from (
    select l.id,
           l.origem_cadastro,
           l.status,
           case
             when l.origem_cadastro = 'inbound'
                  and (l.channel = 'bling' or l.metadata->>'origem' = 'bling_webhook') then 'bling_import'
             when l.origem_cadastro = 'inbound'
                  and l.metadata->>'origem' = 'reativacao_bling' then 'reativacao_import'
             else l.origem_cadastro
           end as nova_origem,
           case when l.status = 'ativo' then 'active' else l.status end as novo_status
      from public.leads l
  ) x
 where x.nova_origem is distinct from x.origem_cadastro
    or x.novo_status is distinct from x.status;

do $$
declare
  n int := (select count(*) from _alvo);
  t int := current_setting('b67f.teto')::int;
begin
  raise notice 'F4 alvo=% teto=%', n, t;
  if n > t then
    raise exception 'F4 acima do teto: % > %', n, t;
  end if;
end $$;

create table if not exists public.backup_b67f_f4 (
  id uuid primary key,
  valor_anterior jsonb not null,
  gravado_em timestamptz not null default now()
);
alter table public.backup_b67f_f4 enable row level security;
revoke all on public.backup_b67f_f4 from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on public.backup_b67f_f4 from anon, authenticated';
  end if;
end $$;

insert into public.backup_b67f_f4 (id, valor_anterior)
select id, jsonb_build_object('origem_cadastro', origem_cadastro, 'status', status,
                              'nova_origem', nova_origem, 'novo_status', novo_status)
  from _alvo
on conflict (id) do nothing;

with u as (
  update public.leads l
     set origem_cadastro = a.nova_origem,
         status = a.novo_status
    from _alvo a
   where l.id = a.id
     and l.origem_cadastro = a.origem_cadastro
     and l.status is not distinct from a.status
  returning l.id
)
select set_config('b67f.alterados', count(*)::text, true) from u \g /dev/null

do $$ begin raise notice 'F4 alterados=%', current_setting('b67f.alterados'); end $$;

select a.origem_cadastro || ' -> ' || l.origem_cadastro as origem,
       a.status || ' -> ' || l.status as status,
       count(*) as leads
  from _alvo a join public.leads l on l.id = a.id
 group by 1, 2 order by 1, 2;

commit;
