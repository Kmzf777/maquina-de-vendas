-- scripts/leads_vendedor/relatorios/human_control_sem_repasse.sql — relatório (cartão b67f1c6b), SÓ SELECT.
--
-- Leads com human_control = true (IA desligada para o lead, atendimento humano) que NUNCA tiveram
-- repasse: nenhum marcador '[encaminhar_humano] Lead encaminhado%' (nem os excluídos) e nenhum
-- evento lead_events 'repasse'. Não ganham o evento 'qualificado' pelo F7; servem para decidir à
-- mão (vendedor assumiu direto, IA desligada por engano, importado etc.).
-- Colunas de apoio: há msg do vendedor (sent_by 'seller'), carimbo metadata.handoff, card
-- (deal) aberto e em que etapa, última mensagem do lead.
-- No fim, um resumo por canal e por "vendedor falou com o lead". Usa só colunas que já existem hoje.
-- Uso: psql -X -A -F '|' -f human_control_sem_repasse.sql

begin read only;

\echo '== Leads com human_control sem repasse =='
with alvo as (
  select l.*
    from public.leads l
   where l.human_control
     and not exists (select 1 from public.messages m
                      where m.lead_id = l.id and m.role = 'system'
                        and m.content like '[encaminhar_humano] Lead encaminhado%')
     and not exists (select 1 from public.lead_events e
                      where e.lead_id = l.id and e.event_type = 'repasse')
)
select a.id as lead_id, a.name, a.phone, a.stage, a.channel, a.metadata->>'origem' as origem,
       a.assigned_to, a.ai_enabled, a.created_at,
       a.metadata ? 'handoff' as tem_carimbo_handoff,
       a.metadata#>>'{handoff,vendedor}' as handoff_vendedor,
       (select count(*) from public.messages m where m.lead_id = a.id and m.sent_by = 'seller') as msgs_vendedor,
       (select max(m.created_at) from public.messages m where m.lead_id = a.id and m.role = 'user') as ultima_msg_lead,
       (select string_agg(p.name || ' / ' || coalesce(ps.key, d.stage, '-'), ' ; ')
          from public.deals d
          left join public.pipelines p on p.id = d.pipeline_id
          left join public.pipeline_stages ps on ps.id = d.stage_id
         where d.lead_id = a.id) as cards
  from alvo a
 order by a.created_at desc;

\echo '== Resumo =='
with alvo as (
  select l.*,
         exists (select 1 from public.messages m where m.lead_id = l.id and m.sent_by = 'seller') as vendedor_falou
    from public.leads l
   where l.human_control
     and not exists (select 1 from public.messages m
                      where m.lead_id = l.id and m.role = 'system'
                        and m.content like '[encaminhar_humano] Lead encaminhado%')
     and not exists (select 1 from public.lead_events e
                      where e.lead_id = l.id and e.event_type = 'repasse')
)
select coalesce(channel, '-') as canal, vendedor_falou, count(*) as leads
  from alvo
 group by rollup (1, 2)
 order by 1 nulls last, 2 nulls last;

rollback;
