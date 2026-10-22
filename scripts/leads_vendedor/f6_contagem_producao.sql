-- scripts/leads_vendedor/f6_contagem_producao.sql — contagem prévia do F6 (cartão b67f1c6b), SÓ SELECT.
-- Roda em produção ANTES das migrations (sem public.vendedores nem fn_vendedor_id): simula os 4
-- vendedores do F1 (uuids + nome/apelidos normalizados) e o dono do funil do Arthur que o F1 grava.
-- Mesma regra de f6_vendedor.sql (deal sem dono de funil usa o assigned_to que o lead JÁ tinha
-- antes do F6, não o que o F6 grava). Uso: psql -X -tA -f f6_contagem_producao.sql
begin read only;

with vend(id, segmentos, chaves) as (values
  ('1c3c78ed-ef47-4dca-9a63-2052f28e8fd6'::uuid, array['atacado','private_label'],
     array['joao bras','joao - cafe canastra','joao']),
  ('c504390c-cdd3-46b8-acfc-13883fb40fe3'::uuid, array['exportacao'],
     array['arthur','arthur - cafe canastra','arthur silva boaventura']),
  ('39032499-c6b5-4531-9e41-d33ecae89e68'::uuid, array[]::text[], array['rafael']),
  ('7e5b4085-0819-484e-a566-f4cd194cf048'::uuid, array[]::text[], array['comercial 2','comercial'])
), lh as (
  select l.id, l.stage, l.assigned_to, l.metadata->'handoff' as h,
         lower(btrim(regexp_replace(extensions.unaccent(l.metadata->'handoff'->>'vendedor'), '\s+', ' ', 'g'))) as nome
    from public.leads l
   where l.assigned_to is null
     and jsonb_typeof(l.metadata->'handoff') = 'object'
     and nullif(l.metadata->'handoff'->>'vendedor_id', '') is null
), res as (
  select lh.*,
         (select case when count(*) = 1 then min(v.id::text)::uuid end
            from vend v where lh.nome = any(v.chaves)) as vendedor_id
    from lh
), cls as (
  select r.*,
         case
           when r.vendedor_id is null then 'ambiguo: nome nao resolve'
           when exists (select 1 from vend v, unnest(array[r.h->>'segmento', r.stage]) s
                         where v.id = r.vendedor_id
                           and s in ('consumo', 'secretaria', 'exportacao')
                           and not s = any(v.segmentos))
             then 'ambiguo: vendedor nao atende o segmento'
           else 'alvo'
         end as classe
    from res r
), owner_sim as (
  select p.id, case when p.id = '4a0c9f7f-47ac-45b1-a760-e2ffc976ccf9'
                    then coalesce(p.owner_user_id, 'c504390c-cdd3-46b8-acfc-13883fb40fe3'::uuid)
                    else p.owner_user_id end as owner
    from public.pipelines p
), deals_alvo as (
  select d.id,
         case when o.owner is not null then 'dono do funil' else 'assigned_to do lead' end as via,
         case when o.owner is not null then (select v.id from vend v where v.id = o.owner)
              else (select v.id from vend v where v.id = l.assigned_to) end as vendedor_id
    from public.deals d
    left join owner_sim o on o.id = d.pipeline_id
    left join public.leads l on l.id = d.lead_id
   where d.assigned_to is null
)
select 'leads', classe, coalesce(vendedor_id::text, '-'), count(*) from cls group by 2, 3
union all
select 'deals', via, vendedor_id::text, count(*) from deals_alvo where vendedor_id is not null group by 2, 3
order by 1, 2, 3;

rollback;
