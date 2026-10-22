-- scripts/leads_vendedor/f1_contagem_producao.sql — contagem prévia do F1 (cartão b67f1c6b), SÓ SELECT.
-- Roda em produção ANTES da migration 20261022a (não usa public.vendedores nem bling_seller_map.vendedor_id).
-- Uso: psql -X -tA -f f1_contagem_producao.sql
begin read only;

with v(id) as (values
  ('1c3c78ed-ef47-4dca-9a63-2052f28e8fd6'::uuid),
  ('c504390c-cdd3-46b8-acfc-13883fb40fe3'::uuid),
  ('39032499-c6b5-4531-9e41-d33ecae89e68'::uuid),
  ('7e5b4085-0819-484e-a566-f4cd194cf048'::uuid)
), vend as (
  select u.id, lower(u.email) as email from v join auth.users u on u.id = v.id
)
select 'vendedores' as parte, count(*) as alvo from vend
union all
select 'bling_seller_map.vendedor_id', count(*)
  from public.bling_seller_map m join vend on vend.email = lower(m.user_email)
union all
select 'bling_seller_map Arthur (insert)', count(*)
  from public.bling_sellers s
 where s.account = 'default' and s.id = 5845108828
   and not exists (select 1 from public.bling_seller_map m
                    where lower(m.user_email) = 'arthur@cafecanastra.com' and m.account = 'default')
union all
select 'pipelines Arthur - Exportação owner', count(*)
  from public.pipelines p
 where p.id = '4a0c9f7f-47ac-45b1-a760-e2ffc976ccf9' and p.owner_user_id is null;

rollback;
