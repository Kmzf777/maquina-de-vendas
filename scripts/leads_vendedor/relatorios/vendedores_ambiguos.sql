-- scripts/leads_vendedor/relatorios/vendedores_ambiguos.sql — relatório (cartão b67f1c6b), SÓ SELECT.
--
-- Leads com repasse (metadata.handoff) sem vendedor_id e sem assigned_to que o F6 NÃO preenche:
--   * 'nome nao resolve'               — fn_vendedor_id(handoff.vendedor) devolve NULL ("Vendedor",
--                                          nome desconhecido ou que casa com mais de um vendedor);
--   * 'vendedor nao atende o segmento' — o nome resolve, mas o segmento conhecido do lead
--                                          (leads.segmento, handoff.segmento ou leads.stage) é
--                                          consumo/secretaria/exportacao e não está em vendedores.segmentos
--                                          (o "Joao Bras" fixo de reserva).
-- Mesma regra de f6_vendedor.sql. Precisa da migration 20261022a e do F1 (vendedores).
-- Saída: lead_id | nome | phone | stage | segmento | handoff.segmento | handoff.vendedor |
--        vendedor resolvido | motivo | handoff.at | handoff.motivo
-- No fim, um resumo por motivo e nome. Uso: psql -X -A -F '|' -f vendedores_ambiguos.sql

begin read only;

with base as (
  select l.id, l.name, l.phone, l.stage, l.segmento, l.metadata->'handoff' as handoff,
         public.fn_vendedor_id(l.metadata->'handoff'->>'vendedor') as vendedor_id
    from public.leads l
   where l.assigned_to is null
     and jsonb_typeof(l.metadata->'handoff') = 'object'
     and nullif(l.metadata->'handoff'->>'vendedor_id', '') is null
), cls as (
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
         end as motivo
    from base b
)
select c.id as lead_id, c.name, c.phone, c.stage, c.segmento,
       c.handoff->>'segmento' as handoff_segmento,
       c.handoff->>'vendedor' as handoff_vendedor,
       v.nome as vendedor_resolvido,
       c.motivo,
       c.handoff->>'at' as handoff_at,
       c.handoff->>'motivo' as handoff_motivo
  from cls c
  left join public.vendedores v on v.id = c.vendedor_id
 where c.motivo is not null
 order by c.motivo, c.handoff->>'vendedor', c.handoff->>'at';

with base as (
  select l.stage, l.segmento, l.metadata->'handoff' as handoff,
         public.fn_vendedor_id(l.metadata->'handoff'->>'vendedor') as vendedor_id
    from public.leads l
   where l.assigned_to is null
     and jsonb_typeof(l.metadata->'handoff') = 'object'
     and nullif(l.metadata->'handoff'->>'vendedor_id', '') is null
)
select 'resumo' as tipo,
       case
         when b.vendedor_id is null then 'nome nao resolve'
         when exists (select 1
                        from public.vendedores v,
                             unnest(array[b.segmento, b.handoff->>'segmento', b.stage]) s
                       where v.id = b.vendedor_id
                         and s in ('consumo', 'secretaria', 'exportacao')
                         and not s = any(v.segmentos))
           then 'vendedor nao atende o segmento'
         else 'F6 preenche'
       end as motivo,
       b.handoff->>'vendedor' as handoff_vendedor,
       count(*) as leads
  from base b
 group by 2, 3
 order by 2, 3;

rollback;
