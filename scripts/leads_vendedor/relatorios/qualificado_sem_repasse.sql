-- scripts/leads_vendedor/relatorios/qualificado_sem_repasse.sql — relatório (cartão b67f1c6b), SÓ SELECT.
--
-- Parte 1. Cards (deals) na etapa 'qualificado' (pipeline_stages.key) cujo lead NÃO tem repasse
--          qualificado: nenhum marcador '[encaminhar_humano] Lead encaminhado%' com motivo fora
--          dos MOTIVOS_EXCLUIDOS de backend/app/leads/qualificado.py. Mesma regra de repasse do
--          f7_qualificado.sql: esses cards não ganham o evento 'qualificado' pelo critério repasse.
-- Parte 2. Leads que só têm o marcador '[qualificar_lead]' (âncoras de qualificação gravadas pela
--          IA) e nenhum repasse qualificado.
-- No fim, um resumo. Usa só colunas que já existem antes das migrations 20261022*.
-- Uso: psql -X -A -F '|' -f qualificado_sem_repasse.sql

begin read only;

\echo '== Parte 1: cards em qualificado sem repasse =='
with marcador as (
  select m.lead_id,
         lower(m.content) like any (array['%ia temporariamente indisponível%',
                                          '%bot de recuperação%', '%escalonamento%']) as excluido
    from public.messages m
   where m.role = 'system'
     and m.content like '[encaminhar_humano] Lead encaminhado%'
     and m.lead_id is not null
), repasse as (
  select lead_id, bool_or(not excluido) as tem_ok, count(*) filter (where excluido) as n_excluidos
    from marcador group by lead_id
), qualificar as (
  select m.lead_id, count(*) as n, min(m.created_at) as primeiro, max(m.created_at) as ultimo,
         (array_agg(m.content order by m.created_at desc))[1] as ultimo_texto
    from public.messages m
   where m.content like '[qualificar_lead]%'
     and m.lead_id is not null
   group by m.lead_id
)
select d.id as deal_id, p.name as funil, d.entered_stage_at as no_qualificado_desde,
       l.id as lead_id, l.name, l.phone, l.stage as lead_stage, l.human_control,
       coalesce(r.n_excluidos, 0) as marcadores_excluidos,
       coalesce(q.n, 0) as marcadores_qualificar_lead,
       s.final_score, s.is_provisional
  from public.deals d
  join public.pipeline_stages ps on ps.id = d.stage_id
  join public.pipelines p on p.id = d.pipeline_id
  left join public.leads l on l.id = d.lead_id
  left join repasse r on r.lead_id = d.lead_id
  left join qualificar q on q.lead_id = d.lead_id
  left join public.lead_qualification_scores s on s.lead_id = d.lead_id
 where ps.key = 'qualificado'
   and not coalesce(r.tem_ok, false)
 order by p.name, d.entered_stage_at;

\echo '== Parte 2: leads so com [qualificar_lead], sem repasse qualificado =='
with marcador as (
  select m.lead_id,
         lower(m.content) like any (array['%ia temporariamente indisponível%',
                                          '%bot de recuperação%', '%escalonamento%']) as excluido
    from public.messages m
   where m.role = 'system'
     and m.content like '[encaminhar_humano] Lead encaminhado%'
     and m.lead_id is not null
), repasse as (
  select lead_id, bool_or(not excluido) as tem_ok, count(*) filter (where excluido) as n_excluidos
    from marcador group by lead_id
), qualificar as (
  select m.lead_id, count(*) as n, min(m.created_at) as primeiro, max(m.created_at) as ultimo,
         (array_agg(m.content order by m.created_at desc))[1] as ultimo_texto
    from public.messages m
   where m.content like '[qualificar_lead]%'
     and m.lead_id is not null
   group by m.lead_id
)
select q.lead_id, l.name, l.phone, l.stage, l.human_control, q.n as marcadores,
       q.primeiro, q.ultimo, left(q.ultimo_texto, 200) as ultimo_marcador,
       coalesce(r.n_excluidos, 0) as marcadores_repasse_excluidos,
       s.final_score, s.is_provisional
  from qualificar q
  join public.leads l on l.id = q.lead_id
  left join repasse r on r.lead_id = q.lead_id
  left join public.lead_qualification_scores s on s.lead_id = q.lead_id
 where not coalesce(r.tem_ok, false)
 order by q.ultimo desc;

\echo '== Resumo =='
with marcador as (
  select m.lead_id,
         lower(m.content) like any (array['%ia temporariamente indisponível%',
                                          '%bot de recuperação%', '%escalonamento%']) as excluido
    from public.messages m
   where m.role = 'system'
     and m.content like '[encaminhar_humano] Lead encaminhado%'
     and m.lead_id is not null
), repasse as (
  select lead_id, bool_or(not excluido) as tem_ok, count(*) filter (where excluido) as n_excluidos
    from marcador group by lead_id
), qualificar as (
  select m.lead_id, count(*) as n, min(m.created_at) as primeiro, max(m.created_at) as ultimo,
         (array_agg(m.content order by m.created_at desc))[1] as ultimo_texto
    from public.messages m
   where m.content like '[qualificar_lead]%'
     and m.lead_id is not null
   group by m.lead_id
)
select 'cards em qualificado (total)' as item, count(*) as n
  from public.deals d join public.pipeline_stages ps on ps.id = d.stage_id
 where ps.key = 'qualificado'
union all
select 'cards em qualificado sem repasse qualificado', count(*)
  from public.deals d join public.pipeline_stages ps on ps.id = d.stage_id
  left join repasse r on r.lead_id = d.lead_id
 where ps.key = 'qualificado' and not coalesce(r.tem_ok, false)
union all
select 'leads com [qualificar_lead] sem repasse qualificado', count(*)
  from qualificar q left join repasse r on r.lead_id = q.lead_id
 where not coalesce(r.tem_ok, false);

rollback;
