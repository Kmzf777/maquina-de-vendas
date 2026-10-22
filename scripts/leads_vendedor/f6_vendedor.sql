-- scripts/leads_vendedor/f6_vendedor.sql — backfill F6 (cartão b67f1c6b)
--
-- Leads (só lead SEM assigned_to e com metadata.handoff.vendedor_id ausente/nulo):
--   leads.assigned_to e metadata.handoff.vendedor_id := fn_vendedor_id(metadata.handoff.vendedor),
--   só quando inequívoco. Ficam de fora (vão para relatorios/vendedores_ambiguos.sql):
--     * nome que não resolve ou resolve para mais de um ("Vendedor");
--     * vendedor que não atende o segmento conhecido do lead (leads.segmento, handoff.segmento ou
--       leads.stage em consumo/secretaria/exportacao fora de vendedores.segmentos) — é o "Joao Bras"
--       fixo de reserva em lead de consumo/secretaria/exportacao.
-- Deals (só assigned_to NULL):
--   * funil com dono: pipelines.owner_user_id (se ele está em vendedores);
--   * funil sem dono: leads.assigned_to do lead, se está em vendedores e NÃO foi gravado por este F6
--     (é o vendedor que o lead já tinha; assim a 2ª execução não acha nada novo).
--   * funil "Blacklist": nunca (nem pelo dono do funil) — vai para o relatório vendedores_ambiguos.sql.
--
-- Pré-requisitos: migrations 20261022a/b e o F1 (vendedores + dono do funil do Arthur).
-- Roda DEPOIS do push do código (F4–F7). Só UPDATE de assigned_to/metadata: nenhum gatilho reage
-- (trg_lead_events_* olham stage_id/ctwa/utm; trg_update_*entered_stage_at só olham stage).
-- Uso: psql -X -v ON_ERROR_STOP=1 [-v teto_deals=N] [-v teto_leads=N] -f f6_vendedor.sql
-- Idempotente (2ª execução: alvo=0). Desfazer: f6_rollback.sql.
-- Backup: public.backup_b67f_f6 (id do lead ou do deal, valor_anterior jsonb com 'tabela').

\if :{?teto_deals}
\else
\set teto_deals 3633
\endif
\if :{?teto_leads}
\else
\set teto_leads 599
\endif

begin;
set local lock_timeout = '5s';
select set_config('b67f.teto_deals', :'teto_deals', true) \g /dev/null
select set_config('b67f.teto_leads', :'teto_leads', true) \g /dev/null

create table if not exists public.backup_b67f_f6 (
  id uuid primary key,
  valor_anterior jsonb not null,
  gravado_em timestamptz not null default now()
);
alter table public.backup_b67f_f6 enable row level security;
revoke all on public.backup_b67f_f6 from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on public.backup_b67f_f6 from anon, authenticated';
  end if;
end $$;

-- Leads com repasse sem vendedor_id e sem assigned_to, classificados (mesma regra do relatório).
create temp table _leads_cls on commit drop as
with base as (
  select l.id, l.stage, l.segmento, l.metadata->'handoff' as handoff,
         public.fn_vendedor_id(l.metadata->'handoff'->>'vendedor') as vendedor_id
    from public.leads l
   where l.assigned_to is null
     and jsonb_typeof(l.metadata->'handoff') = 'object'
     and nullif(l.metadata->'handoff'->>'vendedor_id', '') is null
)
select b.*,
       case
         when b.vendedor_id is null then 'nome nao resolve'
         when exists (select 1
                        from public.vendedores v,
                             unnest(array[b.segmento, b.handoff->>'segmento', b.stage]) s
                       where v.id = b.vendedor_id
                         and s in ('consumo', 'secretaria', 'exportacao')
                         and not s = any(v.segmentos))
           then 'vendedor nao atende o segmento'
       end as ambiguo
  from base b;

create temp table _alvo_leads on commit drop as
select id, vendedor_id, handoff from _leads_cls where ambiguo is null;

create temp table _alvo_deals on commit drop as
select d.id,
       case when p.owner_user_id is not null then vp.id else vl.id end as vendedor_id,
       case when p.owner_user_id is not null then 'dono do funil' else 'assigned_to do lead' end as via
  from public.deals d
  left join public.pipelines p on p.id = d.pipeline_id
  left join public.vendedores vp on vp.id = p.owner_user_id
  left join public.leads l on l.id = d.lead_id
  left join public.vendedores vl on vl.id = l.assigned_to
       and not exists (select 1 from public.backup_b67f_f6 b
                        where b.id = l.id and b.valor_anterior->>'tabela' = 'leads')
 where d.assigned_to is null
   and (p.id is null or lower(btrim(p.name)) <> 'blacklist')
   and case when p.owner_user_id is not null then vp.id else vl.id end is not null;

do $$
declare
  nl int := (select count(*) from _alvo_leads);
  nd int := (select count(*) from _alvo_deals);
  tl int := current_setting('b67f.teto_leads')::int;
  td int := current_setting('b67f.teto_deals')::int;
  r record;
begin
  for r in select v.nome, count(*) as n from _alvo_leads a join public.vendedores v on v.id = a.vendedor_id
            group by 1 order by 1 loop
    raise notice 'F6   leads %: %', r.nome, r.n;
  end loop;
  for r in select ambiguo, count(*) as n from _leads_cls where ambiguo is not null group by 1 order by 1 loop
    raise notice 'F6   leads fora (relatório) %: %', r.ambiguo, r.n;
  end loop;
  for r in select a.via, v.nome, count(*) as n from _alvo_deals a join public.vendedores v on v.id = a.vendedor_id
            group by 1, 2 order by 1, 2 loop
    raise notice 'F6   deals % %: %', r.via, r.nome, r.n;
  end loop;
  raise notice 'F6 leads alvo=% teto=%', nl, tl;
  raise notice 'F6 deals alvo=% teto=%', nd, td;
  if nl > tl then
    raise exception 'F6 leads acima do teto: % > %', nl, tl;
  end if;
  if nd > td then
    raise exception 'F6 deals acima do teto: % > %', nd, td;
  end if;
end $$;

insert into public.backup_b67f_f6 (id, valor_anterior)
select l.id, jsonb_build_object('tabela', 'leads', 'assigned_to', l.assigned_to,
                                'handoff', l.metadata->'handoff', 'novo', a.vendedor_id)
  from _alvo_leads a join public.leads l on l.id = a.id
on conflict (id) do nothing;

insert into public.backup_b67f_f6 (id, valor_anterior)
select d.id, jsonb_build_object('tabela', 'deals', 'assigned_to', d.assigned_to,
                                'novo', a.vendedor_id, 'via', a.via)
  from _alvo_deals a join public.deals d on d.id = a.id
on conflict (id) do nothing;

update public.leads l
   set assigned_to = a.vendedor_id,
       metadata = jsonb_set(l.metadata, '{handoff,vendedor_id}', to_jsonb(a.vendedor_id::text), true)
  from _alvo_leads a
 where l.id = a.id
   and l.assigned_to is null
   and nullif(l.metadata->'handoff'->>'vendedor_id', '') is null;

update public.deals d
   set assigned_to = a.vendedor_id
  from _alvo_deals a
 where d.id = a.id
   and d.assigned_to is null;

select 'leads' as tabela, v.nome, count(*) from _alvo_leads a join public.vendedores v on v.id = a.vendedor_id group by 1, 2
union all
select 'deals', v.nome, count(*) from _alvo_deals a join public.vendedores v on v.id = a.vendedor_id group by 1, 2
order by 1, 2;

commit;
