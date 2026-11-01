-- Cartão 4e0494e0 — spec docs/superpowers/specs/2026-10-31-sync-publicos-pl-atacado-design.md.
-- Sincronização diária dos públicos PL/Atacado (Meta e Google). audience_sync_runs registra cada
-- execução por público; audience_sync_members guarda quem já foi enviado (para remover quem saiu);
-- audience_contact_details é o cache dos detalhes de contato do Bling. audience_sync_facts() devolve
-- todo comprador com venda registrada e seus sinais de segmento (o corte de 365 dias é em Python).
-- Só cria objetos. Reexecutar é seguro. Depois: SIGUSR1 no PostgREST.
-- ROLLBACK: drop function if exists public.audience_sync_facts();
--           drop table if exists public.audience_contact_details;
--           drop table if exists public.audience_sync_members;
--           drop table if exists public.audience_sync_runs;
create table if not exists public.audience_sync_runs (
  id bigserial primary key,
  run_id uuid not null,
  trigger text not null check (trigger in ('automatica','manual')),
  dry_run boolean not null,
  audience_key text not null,
  platform text not null,
  audience_id text not null,
  pessoas int not null default 0,
  com_celular int not null default 0,
  com_email int not null default 0,
  linhas_enviadas int not null default 0,
  removidos int not null default 0,
  api_response jsonb,
  erro text,
  iniciado_em timestamptz not null default now(),
  terminado_em timestamptz
);
create index if not exists audience_sync_runs_iniciado_idx on public.audience_sync_runs (iniciado_em desc);

create table if not exists public.audience_sync_members (
  audience_key text not null,
  ident_hash text not null,
  ident jsonb not null,
  lead_id uuid,
  primeiro_envio timestamptz not null default now(),
  ultimo_envio timestamptz not null default now(),
  removido_em timestamptz,
  primary key (audience_key, ident_hash)
);

create table if not exists public.audience_contact_details (
  account text not null,
  bling_contact_id bigint not null,
  email text,
  municipio text,
  uf text,
  cep text,
  buscado_em timestamptz not null default now(),
  primary key (account, bling_contact_id)
);

alter table public.audience_sync_runs enable row level security;
alter table public.audience_sync_members enable row level security;
alter table public.audience_contact_details enable row level security;

grant select, insert, update on public.audience_sync_runs to service_role;
grant select, insert, update on public.audience_sync_members to service_role;
grant select, insert, update on public.audience_contact_details to service_role;
grant usage, select on sequence public.audience_sync_runs_id_seq to service_role;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'consulta_ro') then
    grant select on public.audience_sync_runs to consulta_ro;
  end if;
end $$;

create or replace function public.audience_sync_facts()
returns jsonb
language sql
stable
security definer
set search_path = public, analytics
as $fn$
select coalesce(jsonb_agg(to_jsonb(x)), '[]'::jsonb) from (
with compradores as (
  select lead_id, max(sold_at) ultima_compra,
         sum(coalesce(value,0)) filter (where sold_at >= now() - interval '365 days') receita_365
  from public.sales where status = 'registrada' and lead_id is not null group by lead_id
),
pip as (
  select d.lead_id, bool_or(p.name ilike '%private label%') pl, bool_or(p.name ilike '%atacado%') at
  from public.deals d join public.pipelines p on p.id = d.pipeline_id group by d.lead_id
),
tg as (
  select lt.lead_id, bool_or(t.name = 'Marca Própria') pl, bool_or(t.name = 'Revenda') at
  from public.lead_tags lt join public.tags t on t.id = lt.tag_id group by lt.lead_id
),
it as (
  select s.lead_id, bool_or(si.descricao ilike '%fotolito%') foto
  from public.sales s join public.sale_items si on si.sale_id = s.id where s.status='registrada' group by s.lead_id
),
pr as (select lead_id, bool_or(product = 'PL') pl from public.sales where status='registrada' group by lead_id),
bc as (
  select l.lead_id,
    array_agg(distinct c.doc_digits) filter (where c.doc_digits is not null) docs,
    array_agg(distinct p) filter (where p is not null) fones,
    array_agg(distinct c.email) filter (where c.email is not null and c.email <> '') emails,
    jsonb_agg(distinct jsonb_build_object('account', l.account, 'id', l.bling_contact_id)) contatos
  from public.lead_bling_contacts l
  join public.bling_contacts c on c.id = l.bling_contact_id and c.account = l.account
  left join lateral unnest(array[c.celular_e164, c.telefone_e164]) p on true
  group by l.lead_id
)
select c.lead_id, c.ultima_compra, coalesce(c.receita_365,0) receita_365, ld.name nome, ld.phone lead_phone, ld.email lead_email,
  coalesce(pip.pl,false) pipeline_pl, coalesce(pip.at,false) pipeline_atacado,
  coalesce(tg.pl,false) tag_pl, coalesce(tg.at,false) tag_atacado,
  coalesce(it.foto,false) fotolito, coalesce(pr.pl,false) produto_pl,
  vc.segmento, coalesce(bc.docs,'{}') docs, coalesce(bc.fones,'{}') fones_bling,
  coalesce(bc.emails,'{}') emails_bling, coalesce(bc.contatos,'[]'::jsonb) contatos_bling
from compradores c join public.leads ld on ld.id = c.lead_id
left join pip using (lead_id) left join tg using (lead_id) left join it using (lead_id)
left join pr using (lead_id) left join analytics.vw_clientes vc using (lead_id) left join bc using (lead_id)
) x
$fn$;

revoke all on function public.audience_sync_facts() from public, anon, authenticated;
grant execute on function public.audience_sync_facts() to service_role;
