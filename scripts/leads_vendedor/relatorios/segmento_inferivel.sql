-- scripts/leads_vendedor/relatorios/segmento_inferivel.sql — relatório (cartão b67f1c6b)
--
-- SÓ LEITURA. Leads em stage 'pending' sem segmento cujo segmento PODERIA ser inferido.
-- O F2 não infere nada disto: é para decisão humana (spec, tabela de backfills, F2).
-- Fontes:
--   funil    — deal em funil cujo nome indica o segmento (Atacado / Private Label /
--              Exportação / Consumo; Reativação, Recuperação, Leads Frios e Blacklist não indicam)
--   origem   — leads.metadata->>'origem': atacado e site-cafecanastra-atacado* -> atacado;
--              terceirizacao -> private_label
--   conversa — conversations.stage com valor de segmento (secretaria não conta)
-- 'sugestao' só sai quando todas as fontes que indicam algo concordam; 'conflito' quando não.
-- Requer a migration 20261022b (leads.segmento).
-- Uso: psql -X -f segmento_inferivel.sql   (pode rodar em begin read only)

with fontes as (
  select d.lead_id, 'funil'::text as fonte,
         case
           when p.name ~* 'private label' then 'private_label'
           when p.name ~* 'atacado'       then 'atacado'
           when p.name ~* 'exporta'       then 'exportacao'
           when p.name ~* 'consumo'       then 'consumo'
         end as segmento
    from public.deals d
    join public.pipelines p on p.id = d.pipeline_id
  union all
  select l.id, 'origem',
         case
           when l.metadata->>'origem' in ('atacado', 'site-cafecanastra-atacado',
                                          'site-cafecanastra-atacado-en') then 'atacado'
           when l.metadata->>'origem' = 'terceirizacao' then 'private_label'
         end
    from public.leads l
  union all
  select c.lead_id, 'conversa',
         case when c.stage in ('atacado', 'private_label', 'consumo', 'exportacao') then c.stage end
    from public.conversations c
),
por_lead as (
  select l.id, l.phone, l.name, l.created_at,
         string_agg(distinct f.segmento, ',') filter (where f.fonte = 'funil')    as por_funil,
         string_agg(distinct f.segmento, ',') filter (where f.fonte = 'origem')   as por_origem,
         string_agg(distinct f.segmento, ',') filter (where f.fonte = 'conversa') as por_conversa,
         count(distinct f.segmento) as n_segmentos,
         min(f.segmento) as unico
    from public.leads l
    join fontes f on f.lead_id = l.id and f.segmento is not null
   where l.stage = 'pending'
     and l.segmento is null
   group by l.id
)
select id, phone, name, created_at::date as criado_em,
       por_funil, por_origem, por_conversa,
       case when n_segmentos = 1 then unico end as sugestao,
       n_segmentos > 1 as conflito
  from por_lead
 order by conflito desc, sugestao nulls last, created_at;

-- Resumo
with fontes as (
  select d.lead_id,
         case
           when p.name ~* 'private label' then 'private_label'
           when p.name ~* 'atacado'       then 'atacado'
           when p.name ~* 'exporta'       then 'exportacao'
           when p.name ~* 'consumo'       then 'consumo'
         end as segmento
    from public.deals d join public.pipelines p on p.id = d.pipeline_id
  union all
  select l.id,
         case
           when l.metadata->>'origem' in ('atacado', 'site-cafecanastra-atacado',
                                          'site-cafecanastra-atacado-en') then 'atacado'
           when l.metadata->>'origem' = 'terceirizacao' then 'private_label'
         end
    from public.leads l
  union all
  select c.lead_id,
         case when c.stage in ('atacado', 'private_label', 'consumo', 'exportacao') then c.stage end
    from public.conversations c
),
por_lead as (
  select l.id, count(distinct f.segmento) as n, min(f.segmento) as unico
    from public.leads l
    join fontes f on f.lead_id = l.id and f.segmento is not null
   where l.stage = 'pending' and l.segmento is null
   group by l.id
)
select case when n > 1 then 'conflito' else unico end as sugestao, count(*) as leads
  from por_lead
 group by 1 order by 2 desc;
