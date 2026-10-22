-- Cartão b67f1c6b (B2): cadastro único de vendedores.
--
--  * public.vendedores: 1 linha por vendedor, chave = auth.users.id. Sem linhas aqui;
--    quem popula é o backfill F1 (scripts/leads_vendedor/f1_vendedores.sql).
--  * fn_vendedor_id(text): uuid | e-mail | nome/apelido -> id. 0 ou >1 casando -> NULL.
--    Espelho de backend/app/vendedores/service.py:resolver_vendedor.
--  * bling_seller_map.vendedor_id -> vendedores(id).
--  * deals.assigned_to: text -> uuid FK vendedores(id). Hoje 0 linhas preenchidas;
--    se houver alguma, a migration aborta em vez de jogar dado fora.
--
-- Idempotente: aplicar 2x não muda nada na segunda.

begin;
set local lock_timeout = '5s';

create table if not exists public.vendedores (
  id            uuid primary key references auth.users(id) on delete restrict,
  email         text not null unique check (email = lower(email)),
  nome          text not null,
  apelidos      text[] not null default '{}',
  segmentos     text[] not null default '{}',
  atende_no_crm boolean not null default true,
  ativo         boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

comment on table public.vendedores is
  'Cadastro único de vendedores (b67f1c6b). segmentos: atacado/private_label/exportacao. '
  'atende_no_crm=false: atende fora do CRM (ex.: Arthur, pelo fixo) e fica fora do SLA do watchdog.';

create or replace trigger trg_vendedores_updated_at
  before update on public.vendedores
  for each row execute function public.set_updated_at();

-- RLS: leitura para quem está logado no CRM; escrita só service_role (bypassa RLS).
alter table public.vendedores enable row level security;
do $$
begin
  if not exists (select 1 from pg_policies
                 where schemaname = 'public' and tablename = 'vendedores'
                   and policyname = 'vendedores_select') then
    create policy vendedores_select on public.vendedores
      for select to authenticated using (true);
  end if;
end $$;

revoke all on public.vendedores from anon;
revoke insert, update, delete, truncate on public.vendedores from authenticated;
grant select on public.vendedores to authenticated, consulta_ro;
grant all on public.vendedores to service_role;

-- Resolvedor. Ordem: uuid existente, e-mail (minúsculo), nome/apelido sem acento
-- (comparado com o nome inteiro, com cada apelido e com o 1º token do nome).
create or replace function public.fn_vendedor_id(p text)
returns uuid
language plpgsql
stable
set search_path = public, extensions, pg_catalog
as $$
declare
  v_bruto text := nullif(btrim(p), '');
  v_nome  text;
  v_ids   uuid[];
begin
  if v_bruto is null then
    return null;
  end if;

  if v_bruto ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
    select array_agg(v.id) into v_ids from public.vendedores v where v.id = v_bruto::uuid;
  end if;

  if coalesce(cardinality(v_ids), 0) = 0 then
    select array_agg(v.id) into v_ids from public.vendedores v where v.email = lower(v_bruto);
  end if;

  if coalesce(cardinality(v_ids), 0) = 0 then
    v_nome := lower(btrim(regexp_replace(extensions.unaccent(v_bruto), '\s+', ' ', 'g')));
    select array_agg(v.id) into v_ids
      from public.vendedores v
     where split_part(lower(btrim(regexp_replace(extensions.unaccent(v.nome), '\s+', ' ', 'g'))), ' ', 1) = v_nome
        or exists (select 1 from unnest(v.apelidos || v.nome) a
                    where lower(btrim(regexp_replace(extensions.unaccent(a), '\s+', ' ', 'g'))) = v_nome);
  end if;

  return case when cardinality(v_ids) = 1 then v_ids[1] end;
end;
$$;

revoke all on function public.fn_vendedor_id(text) from public, anon;
grant execute on function public.fn_vendedor_id(text) to authenticated, service_role, consulta_ro;

-- Vendedor Bling -> vendedor do CRM (preenchido no F1).
alter table public.bling_seller_map
  add column if not exists vendedor_id uuid references public.vendedores(id);

-- deals.assigned_to: text (sempre NULL em produção) -> uuid FK.
do $$
begin
  if (select data_type from information_schema.columns
       where table_schema = 'public' and table_name = 'deals' and column_name = 'assigned_to') = 'text' then
    if exists (select 1 from public.deals where assigned_to is not null) then
      raise exception 'deals.assigned_to tem valores preenchidos: converter manualmente antes desta migration';
    end if;
    alter table public.deals alter column assigned_to type uuid using null;
  end if;

  if not exists (select 1 from pg_constraint
                  where conrelid = 'public.deals'::regclass and conname = 'deals_assigned_to_fkey') then
    alter table public.deals
      add constraint deals_assigned_to_fkey foreign key (assigned_to) references public.vendedores(id);
  end if;
end $$;

create index if not exists idx_deals_assigned_to on public.deals (assigned_to) where assigned_to is not null;

commit;
