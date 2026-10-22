-- scripts/leads_vendedor/f5_entrada_organico.sql — backfill F5 (cartão b67f1c6b)
--
-- Grava a `entrada` que o gatilho novo (migration 20261022c, fn_lead_events_leads_entrada)
-- teria gravado no cadastro, para quem ficou sem nenhuma:
--   A. Orgânico: lead criado desde 01/07/2026 (BRT), origem_cadastro 'inbound', sem rastreio
--      (fn_lead_tem_rastreio falso), sem nenhuma `entrada`, não ja_era_cliente e com pelo
--      menos 1 mensagem do lead (messages.role = 'user'). Mesma linha do gatilho:
--      new_value 'Orgânico', metadata {canal: 'Orgânico', sem_rastreio: true}, source 'inbound'.
--   B. meta_ad_id sem `entrada` (qualquer data): mesma linha do ramo "UPDATE só de meta_ad_id,
--      lead sem entrada" do gatilho: metadata = fn_lead_entrada_metadata(...) com canal de
--      fn_lead_canal(..., origem_cadastro), source fn_lead_entrada_source(metadata).
-- Nos dois: occurred_at = leads.created_at, dedupe_key 'entrada:lead:<id>:inicial'
-- (on conflict do nothing no índice parcial lead_events_dedupe_key_uidx).
--
-- Pré-requisitos: migration 20261022c e o backfill F4 (origem_cadastro) JÁ rodados.
-- Uso: psql -X -v ON_ERROR_STOP=1 [-v teto=N] -f f5_entrada_organico.sql
-- Idempotente (2ª execução: alvo=0). Desfazer: f5_rollback.sql (apaga só os ids do backup).

\if :{?teto}
\else
\set teto 197
\endif

begin;
set local lock_timeout = '5s';
select set_config('b67f.teto', :'teto', true) \g /dev/null

create temp table _alvo on commit drop as
with base as (
  select l.*
    from public.leads l
   where not exists (select 1 from public.lead_events e
                      where e.lead_id = l.id and e.event_type = 'entrada')
     and not exists (select 1 from public.lead_events e
                      where e.dedupe_key = 'entrada:lead:' || l.id || ':inicial')
), organico as (
  select b.id as lead_id, 'organico'::text as grupo,
         jsonb_build_object('canal', 'Orgânico', 'sem_rastreio', true) as metadata,
         b.created_at
    from base b
   where b.created_at >= timestamptz '2026-07-01 00:00:00-03'
     and b.origem_cadastro = 'inbound'
     and not public.fn_lead_tem_rastreio(b.gclid, b.fbclid, b.ctwa_clid, b.meta_ad_id,
                                         b.utm_source, b.utm_campaign, b.gbraid, b.wbraid)
     and not coalesce(b.ja_era_cliente, false)
     and exists (select 1 from public.messages m where m.lead_id = b.id and m.role = 'user')
), meta_ad as (
  select b.id as lead_id, 'meta_ad_id'::text as grupo,
         public.fn_lead_entrada_metadata(b.gclid, b.fbclid, b.ctwa_clid, b.meta_ad_id,
                                         b.utm_source, b.utm_medium, b.utm_campaign,
                                         b.traffic_type, b.gbraid, b.wbraid)
         || jsonb_build_object('canal',
              public.fn_lead_canal(b.gclid, b.fbclid, b.ctwa_clid, b.meta_ad_id,
                                   b.utm_source, b.utm_medium, b.traffic_type,
                                   b.gbraid, b.wbraid, b.origem_cadastro)) as metadata,
         b.created_at
    from base b
   where public.fn_lead_txt(b.meta_ad_id) <> ''
)
select gen_random_uuid() as id, x.lead_id, x.grupo, x.metadata,
       x.metadata->>'canal' as new_value,
       case when x.grupo = 'organico' then 'inbound'
            else public.fn_lead_entrada_source(x.metadata) end as source,
       coalesce(x.created_at, now()) as occurred_at,
       'entrada:lead:' || x.lead_id || ':inicial' as dedupe_key
  from (select * from organico union all select * from meta_ad) x;

do $$
declare
  n int := (select count(*) from _alvo);
  t int := current_setting('b67f.teto')::int;
begin
  raise notice 'F5 alvo=% (organico=%, meta_ad_id=%) teto=%', n,
    (select count(*) from _alvo where grupo = 'organico'),
    (select count(*) from _alvo where grupo = 'meta_ad_id'), t;
  if n > t then
    raise exception 'F5 acima do teto: % > %', n, t;
  end if;
end $$;

create table if not exists public.backup_b67f_f5 (
  id uuid primary key,              -- lead_events.id inserido pelo F5
  valor_anterior jsonb,             -- sempre NULL: antes não havia linha
  gravado_em timestamptz not null default now()
);
alter table public.backup_b67f_f5 enable row level security;
revoke all on public.backup_b67f_f5 from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on public.backup_b67f_f5 from anon, authenticated';
  end if;
end $$;

with ins as (
  insert into public.lead_events (id, lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
  select a.id, a.lead_id, 'entrada', a.new_value, a.metadata, a.occurred_at, a.source, a.dedupe_key
    from _alvo a
  on conflict (dedupe_key) where dedupe_key is not null do nothing
  returning id
), bk as (
  insert into public.backup_b67f_f5 (id, valor_anterior)
  select id, null from ins
  on conflict (id) do nothing
  returning id
)
select set_config('b67f.alterados', count(*)::text, true) from bk \g /dev/null

do $$ begin raise notice 'F5 alterados=%', current_setting('b67f.alterados'); end $$;

select a.grupo, e.new_value as canal, e.source, count(*) as entradas
  from _alvo a join public.lead_events e on e.id = a.id
 group by 1, 2, 3 order by 1, 2, 3;

commit;
