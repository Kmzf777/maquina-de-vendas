-- scripts/leads_vendedor/f7_contagem_producao.sql — contagem prévia do F7 SÓ com SELECT (b67f1c6b)
--
-- Mesmo alvo de f7_qualificado.sql (leads distintos), sem as funções/colunas novas
-- (fn_vendedor_id, fn_lead_b2b, leads.segmento), que só mudam o conteúdo do metadata.
-- Uso: psql -tA < f7_contagem_producao.sql

begin read only;

with excl(x) as (
  values ('ia temporariamente indisponível'), ('bot de recuperação'), ('escalonamento')
), mk as (
  select m.id as message_id, m.lead_id, m.created_at, m.content
    from public.messages m
   where m.role = 'system'
     and m.content like '[encaminhar_humano] Lead encaminhado%'
     and m.lead_id is not null
), rep as (
  select distinct mk.lead_id
    from mk
    join public.leads l on l.id = mk.lead_id
    left join public.lead_events r
           on r.event_type = 'repasse' and r.dedupe_key = 'repasse:' || mk.message_id
   where not exists (
           select 1 from excl
            where strpos(lower(mk.content), excl.x) > 0
               or strpos(lower(coalesce(r.metadata->>'motivo', '')), excl.x) > 0
               or (strpos(lower(coalesce(l.metadata#>>'{handoff,motivo}', '')), excl.x) > 0
                   and abs(extract(epoch from (
                         case when l.metadata#>>'{handoff,at}' ~ '^\d{4}-\d{2}-\d{2}'
                              then (l.metadata#>>'{handoff,at}')::timestamptz end
                         - mk.created_at))) < 120))
), score as (
  select s.lead_id
    from public.lead_qualification_scores s
   where s.final_score >= 5 and s.is_provisional = false
     and not exists (select 1 from rep where rep.lead_id = s.lead_id)
)
select 'repasse' as criterio, count(*) from rep
 where not exists (select 1 from public.lead_events e where e.dedupe_key = 'qualificado:' || rep.lead_id)
union all
select 'score', count(*) from score
 where not exists (select 1 from public.lead_events e where e.dedupe_key = 'qualificado:' || score.lead_id)
union all
select 'eventos repasse (lead_events) usados como fonte', count(*)
  from public.lead_events r where r.event_type = 'repasse';

rollback;
