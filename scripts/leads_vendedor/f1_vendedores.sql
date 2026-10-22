-- scripts/leads_vendedor/f1_vendedores.sql — backfill F1 (cartão b67f1c6b)
--
-- 1. public.vendedores: 4 linhas a partir de auth.users (e-mail sempre em minúsculo):
--      João Brás (ativo, atacado/private_label), Arthur (ativo, exportacao, atende fora do CRM),
--      Rafael e Comercial 2 (inativos, sem segmento). Linha que já existe não é tocada.
-- 2. bling_seller_map.vendedor_id := vendedores.id por lower(user_email) = vendedores.email (só NULL).
-- 3. bling_seller_map: liga o Arthur ao vendedor Bling 5845108828 da conta 'default' (conferido em
--    produção em 22/10: bling_sellers(account='default', id=5845108828) = 'Arthur Silva Boaventura').
--    Se o vendedor Bling não existir, ou o Arthur já tiver linha na conta, não insere (notice).
-- 4. pipelines "Arthur - Exportação" (4a0c9f7f-…) .owner_user_id := Arthur, só se NULL.
--
-- Pré-requisito: migration 20261022a_vendedores.sql. Roda ANTES do push do código.
-- Uso: psql -X -v ON_ERROR_STOP=1 [-v teto=N] -f f1_vendedores.sql
-- Idempotente (2ª execução: alvo=0). Desfazer: f1_rollback.sql (antes, desfazer o F6).
-- Backup: public.backup_b67f_f1 (id text = '<tabela>:<chave>', valor_anterior jsonb).

\if :{?teto}
\else
\set teto 9
\endif

begin;
set local lock_timeout = '5s';
select set_config('b67f.teto', :'teto', true) \g /dev/null

create temp table _vend on commit drop as
select s.id, lower(u.email) as email, s.nome, s.apelidos, s.segmentos, s.atende_no_crm, s.ativo
  from (values
    ('1c3c78ed-ef47-4dca-9a63-2052f28e8fd6'::uuid, 'João Brás',
       array['Joao Bras', 'João - Café Canastra', 'Joao'], array['atacado', 'private_label'], true, true),
    ('c504390c-cdd3-46b8-acfc-13883fb40fe3'::uuid, 'Arthur',
       array['Arthur - Café Canastra', 'Arthur Silva Boaventura'], array['exportacao'], false, true),
    ('39032499-c6b5-4531-9e41-d33ecae89e68'::uuid, 'Rafael',
       array[]::text[], array[]::text[], true, false),
    ('7e5b4085-0819-484e-a566-f4cd194cf048'::uuid, 'Comercial 2',
       array[]::text[], array[]::text[], true, false)
  ) as s(id, nome, apelidos, segmentos, atende_no_crm, ativo)
  join auth.users u on u.id = s.id;

do $$
begin
  if (select count(*) from _vend) <> 4 then
    raise exception 'F1: esperava 4 vendedores em auth.users, achei %', (select count(*) from _vend);
  end if;
end $$;

-- Arthur no Bling: (account, id) conferidos em produção.
create temp table _arthur_bling on commit drop as
select 'arthur@cafecanastra.com'::text as user_email, s.account, s.id as bling_seller_id,
       'c504390c-cdd3-46b8-acfc-13883fb40fe3'::uuid as vendedor_id
  from public.bling_sellers s
 where s.account = 'default' and s.id = 5845108828
   and not exists (select 1 from public.bling_seller_map m
                    where lower(m.user_email) = 'arthur@cafecanastra.com' and m.account = s.account);

do $$
begin
  if not exists (select 1 from public.bling_sellers where account = 'default' and id = 5845108828) then
    raise notice 'F1: vendedor Bling 5845108828 (conta default) não existe em bling_sellers; mapa do Arthur NÃO inserido';
  end if;
end $$;

-- _alvo: tudo que o F1 vai gravar, com o valor anterior.
create temp table _alvo on commit drop as
select 'vendedores:' || v.id as chave, 'vendedores' as tabela,
       jsonb_build_object('tabela', 'vendedores', 'id', v.id, 'existia', false) as valor_anterior
  from _vend v
 where not exists (select 1 from public.vendedores x where x.id = v.id)
union all
select 'bling_seller_map:' || m.user_email || ':' || m.account, 'bling_seller_map.vendedor_id',
       jsonb_build_object('tabela', 'bling_seller_map', 'user_email', m.user_email, 'account', m.account,
                          'existia', true, 'vendedor_id', m.vendedor_id,
                          'novo', coalesce(x.id, v.id))
  from public.bling_seller_map m
  left join public.vendedores x on x.email = lower(m.user_email)
  left join _vend v on v.email = lower(m.user_email)
 where m.vendedor_id is null and coalesce(x.id, v.id) is not null
union all
select 'bling_seller_map:' || a.user_email || ':' || a.account, 'bling_seller_map (insert)',
       jsonb_build_object('tabela', 'bling_seller_map', 'user_email', a.user_email, 'account', a.account,
                          'existia', false)
  from _arthur_bling a
union all
select 'pipelines:' || p.id, 'pipelines.owner_user_id',
       jsonb_build_object('tabela', 'pipelines', 'id', p.id, 'owner_user_id', p.owner_user_id,
                          'novo', 'c504390c-cdd3-46b8-acfc-13883fb40fe3')
  from public.pipelines p
 where p.id = '4a0c9f7f-47ac-45b1-a760-e2ffc976ccf9' and p.owner_user_id is null;

do $$
declare
  n int := (select count(*) from _alvo);
  t int := current_setting('b67f.teto')::int;
  r record;
begin
  for r in select tabela, count(*) as n from _alvo group by 1 order by 1 loop
    raise notice 'F1   %: %', r.tabela, r.n;
  end loop;
  raise notice 'F1 alvo=% teto=%', n, t;
  if n > t then
    raise exception 'F1 acima do teto: % > %', n, t;
  end if;
end $$;

create table if not exists public.backup_b67f_f1 (
  id text primary key,
  valor_anterior jsonb not null,
  gravado_em timestamptz not null default now()
);
alter table public.backup_b67f_f1 enable row level security;
revoke all on public.backup_b67f_f1 from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on public.backup_b67f_f1 from anon, authenticated';
  end if;
end $$;

insert into public.backup_b67f_f1 (id, valor_anterior)
select chave, valor_anterior from _alvo
on conflict (id) do nothing;

-- 1. vendedores
insert into public.vendedores (id, email, nome, apelidos, segmentos, atende_no_crm, ativo)
select id, email, nome, apelidos, segmentos, atende_no_crm, ativo from _vend
on conflict (id) do nothing;

-- 2. bling_seller_map.vendedor_id (só NULL)
update public.bling_seller_map m
   set vendedor_id = v.id
  from public.vendedores v
 where v.email = lower(m.user_email)
   and m.vendedor_id is null;

-- 3. Arthur -> vendedor Bling 5845108828
insert into public.bling_seller_map (user_email, bling_seller_id, account, vendedor_id, updated_at)
select user_email, bling_seller_id, account, vendedor_id, now() from _arthur_bling
on conflict (user_email, account) do nothing;

-- 4. dono do funil "Arthur - Exportação" (só NULL)
update public.pipelines
   set owner_user_id = 'c504390c-cdd3-46b8-acfc-13883fb40fe3'
 where id = '4a0c9f7f-47ac-45b1-a760-e2ffc976ccf9'
   and owner_user_id is null;

select v.email, v.nome, v.ativo, v.segmentos,
       (select count(*) from public.bling_seller_map m where m.vendedor_id = v.id) as mapas_bling,
       (select count(*) from public.pipelines p where p.owner_user_id = v.id) as funis
  from public.vendedores v
 order by v.ativo desc, v.email;

commit;
