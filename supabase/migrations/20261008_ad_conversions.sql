-- 20261008_ad_conversions.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. Roda a mao, DEPOIS da 20261006b_lead_timeline_triggers.sql.
--    Idempotente: pode rodar de novo sem efeito colateral.
--
-- Devolucao de conversoes para Meta e Google Ads (spec
-- docs/superpowers/specs/2026-10-08-conversoes-ads-design.md).
--   1. ad_conversions        fila + registro do que foi enviado (dedupe_key UNIQUE)
--   2. ad_conversion_values  valor estimado por segmento x etapa (aprovado a mao)
--   3. leads.gbraid/wbraid   cliques de iOS do Google
--   4. trigger de entrada    passa a considerar gbraid/wbraid
-- conversion_events (vazia) NAO e dropada: scripts/bling/mesclar_leads_duplicados.py a referencia.

begin;

create table if not exists public.ad_conversions (
  id              uuid primary key default gen_random_uuid(),
  lead_id         uuid not null references public.leads(id) on delete cascade,
  platform        text not null check (platform in ('meta','google')),
  stage           text not null check (stage in ('lead','qualified','opportunity','purchase')),
  sale_id         uuid null references public.sales(id) on delete set null,
  click_id        text not null,
  click_id_type   text not null check (click_id_type in ('ctwa_clid','gclid','gbraid','wbraid')),
  click_at        timestamptz not null,
  campaign_name   text null,
  dedupe_key      text not null unique,
  event_at        timestamptz not null,
  event_id        text not null,
  segment         text not null check (segment in ('atacado','private_label','geral')),
  value           numeric null,
  currency        text not null default 'BRL',
  status          text not null default 'pendente'
                  check (status in ('pendente','enviado','erro','fora_da_janela','ignorado')),
  attempts        int not null default 0,
  next_attempt_at timestamptz not null default now(),
  claimed_at      timestamptz null,
  last_error      text null,
  last_response   jsonb null,
  sent_at         timestamptz null,
  created_at      timestamptz not null default now()
);

create index if not exists ad_conversions_due_idx
  on public.ad_conversions (next_attempt_at) where status = 'pendente';
create index if not exists ad_conversions_event_at_idx
  on public.ad_conversions (event_at desc);
create index if not exists ad_conversions_lead_idx
  on public.ad_conversions (lead_id);

comment on table public.ad_conversions is
  'Fila + auditoria das conversoes devolvidas a Meta/Google. Gravada pela varredura do worker '
  '(app/conversions/sweep.py); enviada por app/conversions/sender.py. Sem PII: o hash e feito no envio.';

alter table public.ad_conversions enable row level security;

create table if not exists public.ad_conversion_values (
  segment     text not null check (segment in ('atacado','private_label','geral')),
  stage       text not null check (stage in ('lead','qualified','opportunity')),
  value       numeric not null check (value >= 0),
  updated_at  timestamptz not null default now(),
  updated_by  text not null,
  primary key (segment, stage)
);

comment on table public.ad_conversion_values is
  'Valor estimado (BRL) por segmento x etapa. Calculado por backend/scripts/conversoes/calcular_valores.py '
  'e gravado so depois de aprovado. Mudar valor reinicia o aprendizado das campanhas.';

alter table public.ad_conversion_values enable row level security;

alter table public.leads add column if not exists gbraid text;
alter table public.leads add column if not exists wbraid text;

-- ── Trigger de entrada da linha do tempo com gbraid/wbraid ─────────────────────────────
-- Recria as funcoes da 20261006b que precisam enxergar gbraid/wbraid (clique de iOS do
-- Google): sem isso, um lead que chega so com gbraid/wbraid seria "Sem rastreio" e nao
-- ganharia entrada, e a varredura de conversoes nao teria de onde tirar o clique.
-- Parametros novos NO FIM, com default null: chamadas antigas (backfill, testes) seguem
-- valendo. Como a assinatura muda, as antigas sao dropadas ANTES — senao ficariam duas
-- sobrecargas e uma chamada com 7/8 argumentos viraria "function is not unique".
-- As listas de canal (_META_AD_SOURCES etc.) sao as mesmas da 20261006b e continuam
-- espelhando traffic_report.py (testadas em test_cs_p3_timeline_migration.py).
drop function if exists public.fn_lead_canal(text, text, text, text, text, text, text);
drop function if exists public.fn_lead_tem_rastreio(text, text, text, text, text, text);
drop function if exists public.fn_lead_entrada_metadata(text, text, text, text, text, text, text, text);

create or replace function public.fn_lead_canal(
  p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text,
  p_utm_source text, p_utm_medium text, p_traffic_type text,
  p_gbraid text default null, p_wbraid text default null
) returns text language sql immutable as $$
  select case
    when public.fn_lead_txt(p_gclid) <> '' or public.fn_lead_txt(p_gbraid) <> ''
      or public.fn_lead_txt(p_wbraid) <> '' then 'Google Ads'
    when public.fn_lead_txt(p_fbclid) <> '' or public.fn_lead_txt(p_ctwa_clid) <> ''
      or public.fn_lead_txt(p_meta_ad_id) <> '' then 'Meta Ads'
    when public.fn_lead_txt(p_utm_source) = any (array['metaads', 'meta_ads', 'meta-ads', 'meta', 'facebook_ads', 'facebookads', 'fb_ads']) -- _META_AD_SOURCES
      then 'Meta Ads'
    when public.fn_lead_txt(p_utm_source) = any (array['google', 'googleads', 'google_ads', 'adwords']) -- _GOOGLE_AD_SOURCES
     and public.fn_lead_txt(p_utm_medium) = any (array['cpc', 'ppc', 'pmax', 'performance_max', 'paid', 'paid_search', 'paidsearch', 'display', 'cpm', 'paid_social', 'paidsocial']) -- _PAID_CHANNEL_MEDIUMS
      then 'Google Ads'
    when public.fn_lead_txt(p_traffic_type) = 'organic' or public.fn_lead_txt(p_utm_source) <> ''
      then 'Orgânico'
    else 'Sem rastreio'
  end
$$;

create or replace function public.fn_lead_tem_rastreio(
  p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text,
  p_utm_source text, p_utm_campaign text,
  p_gbraid text default null, p_wbraid text default null
) returns boolean language sql immutable as $$
  select public.fn_lead_txt(p_gclid) <> '' or public.fn_lead_txt(p_fbclid) <> ''
      or public.fn_lead_txt(p_ctwa_clid) <> '' or public.fn_lead_txt(p_meta_ad_id) <> ''
      or public.fn_lead_txt(p_utm_source) <> '' or public.fn_lead_txt(p_utm_campaign) <> ''
      or public.fn_lead_txt(p_gbraid) <> '' or public.fn_lead_txt(p_wbraid) <> ''
$$;

-- entrada: {canal, campanha_id, campanha_nome, ctwa_clid, meta_ad_id, gclid, gbraid, wbraid,
--           fbclid, utm_source, utm_medium, utm_campaign}.
create or replace function public.fn_lead_entrada_metadata(
  p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text,
  p_utm_source text, p_utm_medium text, p_utm_campaign text, p_traffic_type text,
  p_gbraid text default null, p_wbraid text default null
) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'canal', public.fn_lead_canal(p_gclid, p_fbclid, p_ctwa_clid, p_meta_ad_id,
                                  p_utm_source, p_utm_medium, p_traffic_type,
                                  p_gbraid, p_wbraid),
    'campanha_id', mac.campaign_id,
    'campanha_nome', nullif(mac.campaign_name, ''),
    'ctwa_clid', p_ctwa_clid,
    'meta_ad_id', p_meta_ad_id,
    'gclid', p_gclid,
    'gbraid', p_gbraid,
    'wbraid', p_wbraid,
    'fbclid', p_fbclid,
    'utm_source', p_utm_source,
    'utm_medium', p_utm_medium,
    'utm_campaign', p_utm_campaign)
  from (select 1) as um
  left join public.meta_ad_campaigns mac on mac.ad_id = nullif(btrim(p_meta_ad_id), '')
$$;

-- Funcao do trigger de leads: corpo da 20261006b + gbraid/wbraid nas guardas e nas chamadas.
create or replace function public.fn_lead_events_leads_entrada()
returns trigger language plpgsql security definer set search_path = public, pg_temp as $$
declare
  v_meta jsonb;
  v_ultimo uuid;
begin
  -- Guardas baratas FORA do bloco com exception: ele abre subtransacao por linha.
  if not public.fn_lead_tem_rastreio(new.gclid, new.fbclid, new.ctwa_clid, new.meta_ad_id,
                                     new.utm_source, new.utm_campaign,
                                     new.gbraid, new.wbraid) then
    return new;
  end if;
  if tg_op = 'UPDATE' then
    if new.ctwa_clid is not distinct from old.ctwa_clid
       and new.gclid is not distinct from old.gclid
       and new.gbraid is not distinct from old.gbraid
       and new.wbraid is not distinct from old.wbraid
       and new.fbclid is not distinct from old.fbclid
       and new.meta_ad_id is not distinct from old.meta_ad_id
       and new.utm_source is not distinct from old.utm_source
       and new.utm_campaign is not distinct from old.utm_campaign then
      return new;
    end if;
  end if;
  begin
    v_meta := public.fn_lead_entrada_metadata(new.gclid, new.fbclid, new.ctwa_clid, new.meta_ad_id,
                                              new.utm_source, new.utm_medium, new.utm_campaign,
                                              new.traffic_type, new.gbraid, new.wbraid);

    -- so meta_ad_id mudou (ctwa_clid e o resto iguais): e ENRIQUECIMENTO da mesma entrada,
    -- nunca entrada nova. Acontece no webhook (meta_ad_id chega depois do ctwa_clid) e no
    -- scripts/trafego/recuperar_meta_ad_id.py do P2 (~687 leads antigos), que sem esta regra
    -- ganhariam entradas falsas datadas do dia do script. Atualiza a entrada mais recente com
    -- o MESMO ctwa_clid; nao havendo, nao faz nada.
    if tg_op = 'UPDATE'
       and new.ctwa_clid is not distinct from old.ctwa_clid
       and new.gclid is not distinct from old.gclid
       and new.gbraid is not distinct from old.gbraid
       and new.wbraid is not distinct from old.wbraid
       and new.fbclid is not distinct from old.fbclid
       and new.utm_source is not distinct from old.utm_source
       and new.utm_campaign is not distinct from old.utm_campaign then
      if public.fn_lead_txt(new.ctwa_clid) <> '' then
        update public.lead_events alvo
           set metadata = coalesce(alvo.metadata, '{}'::jsonb)
                          || jsonb_build_object('meta_ad_id', new.meta_ad_id)
                          || case when v_meta->>'campanha_id' is not null
                                  then jsonb_build_object('campanha_id', v_meta->'campanha_id',
                                                          'campanha_nome', v_meta->'campanha_nome')
                                  else '{}'::jsonb end
         where alvo.id = (select e.id from public.lead_events e
                           where e.lead_id = new.id and e.event_type = 'entrada'
                             and e.metadata->>'ctwa_clid' = new.ctwa_clid
                           order by e.occurred_at desc, e.created_at desc
                           limit 1);
      end if;
      return new;
    end if;

    if tg_op = 'UPDATE' then
      select e.id into v_ultimo
        from public.lead_events e
       where e.lead_id = new.id
         and e.event_type = 'entrada'
         and e.occurred_at >= now() - interval '30 minutes'
       order by e.occurred_at desc, e.created_at desc
       limit 1;
      if v_ultimo is not null then
        update public.lead_events
           set metadata = coalesce(metadata, '{}'::jsonb) || v_meta,
               new_value = v_meta->>'canal',
               source = public.fn_lead_entrada_source(v_meta)
         where id = v_ultimo;
        return new;
      end if;
    end if;

    insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
    values (new.id, 'entrada', v_meta->>'canal', v_meta,
            case when tg_op = 'INSERT' then coalesce(new.created_at, now()) else now() end,
            public.fn_lead_entrada_source(v_meta),
            case when tg_op = 'INSERT' then 'entrada:lead:' || new.id || ':inicial'
                 else 'entrada:lead:' || new.id || ':' || extract(epoch from now())::text end)
    on conflict (dedupe_key) where dedupe_key is not null do nothing;
  exception when others then
    raise warning 'fn_lead_events_leads_entrada: %', sqlerrm;
  end;
  return new;
end $$;

revoke execute on function public.fn_lead_events_leads_entrada() from public, anon, authenticated;

drop trigger if exists trg_lead_events_leads_entrada on public.leads;
create trigger trg_lead_events_leads_entrada
  after insert or update of ctwa_clid, gclid, gbraid, wbraid, fbclid, meta_ad_id, utm_source, utm_campaign
  on public.leads
  for each row execute function public.fn_lead_events_leads_entrada();

commit;
