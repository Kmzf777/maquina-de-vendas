-- scripts/leads_vendedor/f5_contagem_producao.sql — contagem prévia do F5 SÓ com SELECT (b67f1c6b)
--
-- Mesmo alvo de f5_entrada_organico.sql, mas com as colunas que existem HOJE em produção
-- (antes da migration 20261022c): origem_cadastro 'inbound' = NÃO é o que o F4 marca como
-- importado (channel 'bling' ou metadata.origem 'bling_webhook'/'reativacao_bling').
-- Uso: psql -tA < f5_contagem_producao.sql

begin read only;

with base as (
  select l.*
    from public.leads l
   where not exists (select 1 from public.lead_events e
                      where e.lead_id = l.id and e.event_type = 'entrada')
)
select 'organico' as grupo, count(*)
  from base b
 where b.created_at >= timestamptz '2026-07-01 00:00:00-03'
   and not (coalesce(b.channel, '') = 'bling'
            or coalesce(b.metadata->>'origem', '') in ('bling_webhook', 'reativacao_bling'))
   and not public.fn_lead_tem_rastreio(b.gclid, b.fbclid, b.ctwa_clid, b.meta_ad_id,
                                       b.utm_source, b.utm_campaign, b.gbraid, b.wbraid)
   and not coalesce(b.ja_era_cliente, false)
   and exists (select 1 from public.messages m where m.lead_id = b.id and m.role = 'user')
union all
select 'meta_ad_id', count(*)
  from base b
 where public.fn_lead_txt(b.meta_ad_id) <> '';

rollback;
