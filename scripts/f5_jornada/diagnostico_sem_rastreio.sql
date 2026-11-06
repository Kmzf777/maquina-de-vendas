-- scripts/f5_jornada/diagnostico_sem_rastreio.sql
--
-- Passo 0 do cartão C ("Sem rastreio"), só leitura. Roda com o consulta_ro ANTES da migração
-- 20261106 (usa só o que já existe em produção: fn_lead_canal de 10 args da 20261022c).
-- Cada bloco é uma consulta independente. Janela: vendas de 15 a 21/10/2026 (dia de Brasília).
--   psql -h 127.0.0.1 -U consulta_ro -d postgres -f diagnostico_sem_rastreio.sql

-- ── 1. Vendas da semana, uma por linha, com tudo o que explica a origem ──────────────────
with vendas as (
  select s.id, s.lead_id, s.sold_at, s.value
    from public.sales s
   where (s.sold_at at time zone 'America/Sao_Paulo')::date between date '2026-10-15' and date '2026-10-21'
     and coalesce(lower(btrim(s.status)), '') not like 'cancel%'
), primeira_conv as (
  select distinct on (c.lead_id) c.lead_id, ch.name as canal_wa, ch.provider
    from public.conversations c left join public.channels ch on ch.id = c.channel_id
   order by c.lead_id, c.created_at, c.id
)
select v.sold_at::date as venda, l.id as lead, l.created_at::date as cadastro, l.origem_cadastro,
       l.channel as lead_channel,
       (coalesce(l.gclid, l.gbraid, l.wbraid) is not null) as tem_gclid,
       l.ctwa_clid is not null as tem_ctwa, l.meta_ad_id is not null as tem_ad, l.utm_source,
       public.fn_lead_canal(l.gclid, l.fbclid, l.ctwa_clid, l.meta_ad_id, l.utm_source, l.utm_medium,
                            l.traffic_type, l.gbraid, l.wbraid, l.origem_cadastro) as canal,
       (select count(*) from public.lead_events e where e.lead_id = l.id and e.event_type = 'entrada') as entradas,
       (select e.new_value from public.lead_events e where e.lead_id = l.id and e.event_type = 'entrada'
         order by e.occurred_at limit 1) as primeira_entrada,
       (select e.new_value from public.lead_events e where e.lead_id = l.id and e.event_type = 'entrada'
         order by e.occurred_at desc limit 1) as ultima_entrada,
       pc.canal_wa, pc.provider,
       (l.last_customer_message_at is not null) as ja_escreveu,
       coalesce(l.ja_era_cliente, false) as ja_era_cliente,
       exists (select 1 from public.sales s2 where s2.lead_id = l.id
                and (s2.sold_at at time zone 'America/Sao_Paulo')::date
                    < (l.created_at at time zone 'America/Sao_Paulo')::date) as venda_antes_do_cadastro,
       exists (select 1 from public.broadcast_leads b where b.lead_id = l.id
                and b.sent_at is not null and b.sent_at < v.sold_at) as disparo_antes
  from vendas v
  join public.leads l on l.id = v.lead_id
  left join primeira_conv pc on pc.lead_id = l.id
 order by (public.fn_lead_canal(l.gclid, l.fbclid, l.ctwa_clid, l.meta_ad_id, l.utm_source, l.utm_medium,
                                l.traffic_type, l.gbraid, l.wbraid, l.origem_cadastro) = 'Sem rastreio') desc,
          v.sold_at;

-- ── 2. Os "Sem rastreio" agrupados pela fonte provável (a ordem é a da F5) ────────────────
with vendas as (
  select distinct s.lead_id, min(s.sold_at) over (partition by s.lead_id) as sold_at
    from public.sales s
   where (s.sold_at at time zone 'America/Sao_Paulo')::date between date '2026-10-15' and date '2026-10-21'
     and coalesce(lower(btrim(s.status)), '') not like 'cancel%'
), primeira_conv as (
  select distinct on (c.lead_id) c.lead_id, c.channel_id, ch.provider
    from public.conversations c left join public.channels ch on ch.id = c.channel_id
   order by c.lead_id, c.created_at, c.id
), canais_anuncio as (
  select distinct pc.channel_id from primeira_conv pc join public.leads la on la.id = pc.lead_id
   where coalesce(la.ctwa_clid, la.meta_ad_id) is not null
), sr as (
  select l.*, v.sold_at, pc.channel_id as canal_1a_conversa, pc.provider
    from vendas v join public.leads l on l.id = v.lead_id
    left join primeira_conv pc on pc.lead_id = l.id
   where public.fn_lead_canal(l.gclid, l.fbclid, l.ctwa_clid, l.meta_ad_id, l.utm_source, l.utm_medium,
                              l.traffic_type, l.gbraid, l.wbraid, l.origem_cadastro) = 'Sem rastreio'
)
select case
         when coalesce(sr.ja_era_cliente, false)
           or exists (select 1 from public.sales s2 where s2.lead_id = sr.id
                       and (s2.sold_at at time zone 'America/Sao_Paulo')::date
                           < (sr.created_at at time zone 'America/Sao_Paulo')::date)
           then '4. cliente antigo (Bling)'
         when sr.canal_1a_conversa is not null
          and (sr.provider = 'evolution' or sr.canal_1a_conversa not in (select channel_id from canais_anuncio))
           then '5. outro número de WhatsApp'
         when sr.origem_cadastro = 'manual' or sr.channel in ('manual', 'campaign')
           or exists (select 1 from public.broadcast_leads b where b.lead_id = sr.id
                       and b.sent_at is not null and b.sent_at < sr.sold_at)
           then '2. cadastro manual / disparo'
         when sr.origem_cadastro = 'csv_import' then '3. CSV'
         when sr.origem_cadastro = 'inbound' and (sr.last_customer_message_at is not null
              or exists (select 1 from public.conversations c where c.lead_id = sr.id
                          and c.last_customer_message_at is not null))
           then '1. inbound sem anúncio'
         else '6. não se encaixa'
       end as grupo,
       count(*) as leads
  from sr
 group by 1
 order by 1;

-- ── 3. Leads dos últimos 60 dias com entradas de mais de um canal ────────────────────────
with toques as (
  select e.lead_id, e.occurred_at,
         coalesce(nullif(e.metadata->>'canal', ''), e.new_value) as canal
    from public.lead_events e
   where e.event_type = 'entrada'
     and e.lead_id in (select id from public.leads where created_at >= now() - interval '60 days')
), multi as (
  select lead_id from toques group by lead_id having count(distinct canal) >= 2
)
select (select count(*) from multi) as leads_multicanal,
       t.lead_id,
       string_agg(t.canal || ' (' || to_char(t.occurred_at at time zone 'America/Sao_Paulo', 'DD/MM HH24:MI') || ')',
                  ' → ' order by t.occurred_at) as sequencia
  from toques t
 where t.lead_id in (select lead_id from multi)
 group by t.lead_id
 order by max(t.occurred_at) desc
 limit 10;

-- ── 4. Meta → Google que hoje se perde: lead com anúncio do Meta que depois mandou o texto do Google
select count(distinct l.id) as leads
  from public.leads l
  join public.messages m on m.lead_id = l.id
 where l.created_at >= now() - interval '60 days'
   and coalesce(l.ctwa_clid, l.meta_ad_id) is not null
   and m.role = 'user'
   and translate(lower(m.content), 'êéáãç', 'eeaac') like '%encontrei voces pelo google%';
