-- scripts/leads_vendedor/f7_qualificado.sql — backfill F7 (cartão b67f1c6b)
--
-- Evento lead_events 'qualificado', 1 por lead (dedupe_key 'qualificado:<lead_id>'), no mesmo
-- formato de backend/app/leads/qualificado.py:registrar_qualificado:
--   metadata = {criterio, segmento, b2b, motivo, vendedor_id}
--
--   A. criterio 'repasse': o 1º repasse NÃO excluído de cada lead. Repasse = mensagem system
--      '[encaminhar_humano] Lead encaminhado%' (marcador; um por repasse). Excluído quando o
--      motivo contém um dos MOTIVOS_EXCLUIDOS de app/leads/qualificado.py (mesmo texto de
--      conversions/eligibility.py) — olhando o texto do marcador, o motivo do evento
--      lead_events 'repasse' do mesmo marcador e o metadata.handoff.motivo do lead quando o
--      carimbo (handoff.at) é desse mesmo repasse (até 2 min de diferença).
--      Quando existe o evento lead_events 'repasse' do marcador (dedupe 'repasse:<message_id>',
--      B3/7b143561), ele é a fonte preferida de source, motivo, segmento e vendedor_id.
--      Sem ele: source 'button_flow' se o motivo é do bot de botões, senão 'ia'; motivo = texto
--      depois de "para <vendedor>: "; vendedor_id = fn_vendedor_id(<vendedor do marcador>)
--      (ambíguo como "Vendedor" -> NULL). occurred_at = created_at do marcador.
--   B. criterio 'score': lead_qualification_scores com final_score >= 5 e is_provisional = false
--      de lead SEM repasse qualificado (A). source 'score', occurred_at = updated_at do score,
--      motivo NULL, vendedor_id NULL.
--   segmento: o do evento de repasse se for um segmento válido, senão leads.segmento (F2).
--   b2b: fn_lead_b2b(lead) no momento do backfill.
--
-- Pré-requisitos: migrations 20261022a/b (vendedores, fn_vendedor_id, leads.segmento,
-- fn_lead_b2b) e, de preferência, F1 (vendedores) e F2 (segmento) já rodados.
-- Uso: psql -X -v ON_ERROR_STOP=1 [-v teto=N] -f f7_qualificado.sql
-- Idempotente (lead que já tem 'qualificado:<id>' sai do alvo). Desfazer: f7_rollback.sql.

\if :{?teto}
\else
\set teto 1419
\endif

begin;
set local lock_timeout = '5s';
select set_config('b67f.teto', :'teto', true) \g /dev/null

create temp table _alvo on commit drop as
with excl(x) as (
  values ('ia temporariamente indisponível'), ('bot de recuperação'), ('escalonamento')
), mk as (
  select m.id as message_id, m.lead_id, m.created_at, m.content,
         substring(m.content from '^\[encaminhar_humano\] Lead encaminhado para ([^:]*):') as vendedor_txt,
         nullif(regexp_replace(m.content, '^\[encaminhar_humano\] Lead encaminhado para [^:]*: ?', ''), m.content) as motivo_txt
    from public.messages m
   where m.role = 'system'
     and m.content like '[encaminhar_humano] Lead encaminhado%'
     and m.lead_id is not null
), rep as (
  select distinct on (mk.lead_id)
         mk.lead_id, mk.message_id, mk.created_at, mk.vendedor_txt,
         coalesce(nullif(r.metadata->>'motivo', ''), mk.motivo_txt) as motivo,
         coalesce(r.source,
                  case when lower(coalesce(mk.motivo_txt, '')) like 'bot de botões%' then 'button_flow'
                       else 'ia' end) as source,
         r.metadata->>'segmento' as segmento_evento,
         coalesce(public.fn_vendedor_id(r.metadata->>'vendedor_id'),
                  public.fn_vendedor_id(r.metadata->>'vendedor'),
                  public.fn_vendedor_id(mk.vendedor_txt)) as vendedor_id
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
   order by mk.lead_id, mk.created_at, mk.message_id
), score as (
  select s.lead_id, s.updated_at
    from public.lead_qualification_scores s
   where s.final_score >= 5
     and s.is_provisional = false
     and not exists (select 1 from rep where rep.lead_id = s.lead_id)
), cand as (
  select rep.lead_id, 'repasse'::text as criterio, rep.source, rep.created_at as occurred_at,
         rep.segmento_evento, rep.motivo, rep.vendedor_id
    from rep
  union all
  select score.lead_id, 'score', 'score', score.updated_at, null, null, null::uuid
    from score
)
select gen_random_uuid() as id, c.lead_id, c.criterio, c.source, c.occurred_at,
       jsonb_build_object(
         'criterio', c.criterio,
         'segmento', case when c.segmento_evento in ('atacado','private_label','consumo','exportacao')
                          then c.segmento_evento else l.segmento end,
         'b2b', public.fn_lead_b2b(c.lead_id),
         'motivo', c.motivo,
         'vendedor_id', c.vendedor_id) as metadata,
       'qualificado:' || c.lead_id as dedupe_key
  from cand c
  join public.leads l on l.id = c.lead_id
 where not exists (select 1 from public.lead_events e
                    where e.dedupe_key = 'qualificado:' || c.lead_id);

do $$
declare
  n int := (select count(*) from _alvo);
  t int := current_setting('b67f.teto')::int;
begin
  raise notice 'F7 alvo=% (repasse=%, score=%) teto=%', n,
    (select count(*) from _alvo where criterio = 'repasse'),
    (select count(*) from _alvo where criterio = 'score'), t;
  if n > t then
    raise exception 'F7 acima do teto: % > %', n, t;
  end if;
end $$;

create table if not exists public.backup_b67f_f7 (
  id uuid primary key,              -- lead_events.id inserido pelo F7
  valor_anterior jsonb,             -- sempre NULL: antes não havia linha
  gravado_em timestamptz not null default now()
);
alter table public.backup_b67f_f7 enable row level security;
revoke all on public.backup_b67f_f7 from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on public.backup_b67f_f7 from anon, authenticated';
  end if;
end $$;

with ins as (
  insert into public.lead_events (id, lead_id, event_type, metadata, occurred_at, source, dedupe_key)
  select a.id, a.lead_id, 'qualificado', a.metadata, a.occurred_at, a.source, a.dedupe_key
    from _alvo a
  on conflict (dedupe_key) where dedupe_key is not null do nothing
  returning id
), bk as (
  insert into public.backup_b67f_f7 (id, valor_anterior)
  select id, null from ins
  on conflict (id) do nothing
  returning id
)
select set_config('b67f.alterados', count(*)::text, true) from bk \g /dev/null

do $$ begin raise notice 'F7 alterados=%', current_setting('b67f.alterados'); end $$;

select a.criterio, e.source, e.metadata->>'segmento' as segmento, (e.metadata->>'b2b')::boolean as b2b,
       (e.metadata->>'vendedor_id') is not null as tem_vendedor, count(*) as eventos
  from _alvo a join public.lead_events e on e.id = a.id
 group by 1, 2, 3, 4, 5 order by 1, 2, 3, 4, 5;

commit;
