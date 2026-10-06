-- 20261006b_lead_timeline_triggers.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. Roda a mao, DEPOIS da 20261006_call_semanal_base.sql (P0).
--    Idempotente: pode rodar de novo sem efeito colateral.
--
-- Linha do tempo do lead (spec docs/superpowers/specs/2026-10-06-call-semanal-0110-design.md,
-- pacote P3). Captura por trigger, num lugar so, o que hoje esta espalhado:
--   entrada          leads: insert com rastreio, ou update que MUDA ctwa_clid/gclid/fbclid/
--                    meta_ad_id/utm_source/utm_campaign. Reentrada com rastreio identico nao
--                    gera evento (limitacao aceita).
--   etapa            deals: insert e update de stage_id.
--   venda            sales: insert. metadata.kit vem de sale_items (descricao ~ 'kit degust'),
--                    recalculado pelo trigger de sale_items porque os itens chegam DEPOIS.
--   venda_cancelada  sales: status passa a 'cancelada'.
--   disparo          broadcast_leads: sent_at passa a ter valor.
-- mesclagem e atribuicao_manual sao gravados pelo codigo do P1/P2.
--
-- dedupe_key deterministica: scripts/timeline/backfill_lead_events.py gera AS MESMAS chaves,
-- entao o backfill nao duplica o que o trigger ja gravou (e vice-versa).
-- Nenhum trigger derruba a escrita original: corpo em begin ... exception when others then
-- raise warning ... end.

-- ── 0. CANAL — espelho de backend/app/campaigns/traffic_report.py:derive_channel ──────
-- As tres listas abaixo sao testadas contra as constantes do Python
-- (backend/tests/test_cs_p3_timeline_migration.py). Mudou la, muda aqui.
create or replace function public.fn_lead_txt(p text)
returns text language sql immutable as $$
  select lower(btrim(coalesce(p, ''), E' \t\r\n\f'))
$$;

create or replace function public.fn_lead_canal(
  p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text,
  p_utm_source text, p_utm_medium text, p_traffic_type text
) returns text language sql immutable as $$
  select case
    when public.fn_lead_txt(p_gclid) <> '' then 'Google Ads'
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
  p_utm_source text, p_utm_campaign text
) returns boolean language sql immutable as $$
  select public.fn_lead_txt(p_gclid) <> '' or public.fn_lead_txt(p_fbclid) <> ''
      or public.fn_lead_txt(p_ctwa_clid) <> '' or public.fn_lead_txt(p_meta_ad_id) <> ''
      or public.fn_lead_txt(p_utm_source) <> '' or public.fn_lead_txt(p_utm_campaign) <> ''
$$;

-- ── 1. METADATA (contratos do P0; o backfill usa as mesmas funcoes) ───────────────────
-- entrada: {canal, campanha_id, campanha_nome, ctwa_clid, meta_ad_id, gclid, fbclid,
--           utm_source, utm_medium, utm_campaign}. campanha_* so via meta_ad_campaigns:
-- slug de utm NAO e nome de campanha (o P2 casa o Google pelo ad_spend).
create or replace function public.fn_lead_entrada_metadata(
  p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text,
  p_utm_source text, p_utm_medium text, p_utm_campaign text, p_traffic_type text
) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'canal', public.fn_lead_canal(p_gclid, p_fbclid, p_ctwa_clid, p_meta_ad_id,
                                  p_utm_source, p_utm_medium, p_traffic_type),
    'campanha_id', mac.campaign_id,
    'campanha_nome', nullif(mac.campaign_name, ''),
    'ctwa_clid', p_ctwa_clid,
    'meta_ad_id', p_meta_ad_id,
    'gclid', p_gclid,
    'fbclid', p_fbclid,
    'utm_source', p_utm_source,
    'utm_medium', p_utm_medium,
    'utm_campaign', p_utm_campaign)
  from (select 1) as um
  left join public.meta_ad_campaigns mac on mac.ad_id = nullif(btrim(p_meta_ad_id), '')
$$;

-- lead_events.source da entrada: google | ctwa | lp.
create or replace function public.fn_lead_entrada_source(p_meta jsonb)
returns text language sql immutable as $$
  select case
    when p_meta->>'canal' = 'Google Ads' then 'google'
    when coalesce(p_meta->>'ctwa_clid', '') <> '' or coalesce(p_meta->>'meta_ad_id', '') <> '' then 'ctwa'
    else 'lp'
  end
$$;

-- venda: sold_by/origin vao junto porque a rota aplica o escopo de vendas do vendedor.
create or replace function public.fn_lead_events_venda_metadata(p_sale public.sales)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'sale_id', p_sale.id,
    'valor', p_sale.value,
    'produto', p_sale.product,
    'origin', p_sale.origin,
    'status', p_sale.status,
    'sold_by', p_sale.sold_by,
    'bling_account', p_sale.bling_account,
    'bling_order_number', p_sale.bling_order_number,
    'deal_id', p_sale.deal_id,
    'kit', exists (select 1 from public.sale_items i
                    where i.sale_id = p_sale.id and i.descricao ilike '%kit degust%'))
$$;

create or replace function public.fn_lead_events_etapa_metadata(
  p_deal_id uuid, p_pipeline_id uuid, p_de uuid, p_para uuid
) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'deal_id', p_deal_id,
    'pipeline_id', p_pipeline_id,
    'pipeline_nome', p.name,
    'de_stage_id', p_de,
    'de_label', sd.label,
    'de_key', sd.key,
    'para_stage_id', p_para,
    'para_label', sp.label,
    'para_key', sp.key)
  from (select 1) as um
  left join public.pipelines p on p.id = p_pipeline_id
  left join public.pipeline_stages sd on sd.id = p_de
  left join public.pipeline_stages sp on sp.id = p_para
$$;

create or replace function public.fn_lead_events_disparo_metadata(p_bl public.broadcast_leads)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'broadcast_lead_id', p_bl.id,
    'broadcast_id', p_bl.broadcast_id,
    'broadcast_nome', b.name,
    'template_name', b.template_name)
  from (select 1) as um
  left join public.broadcasts b on b.id = p_bl.broadcast_id
$$;

-- ── 2. ENTRADA (leads) ─────────────────────────────────────────────────────────────────
-- O webhook CTWA cria o lead com ctwa_clid e grava meta_ad_id num UPDATE separado
-- (meta_router._register_lead). Update de rastreio a menos de 30 min da ultima entrada
-- FUNDE o snapshot nela em vez de criar outra.
create or replace function public.fn_lead_events_leads_entrada()
returns trigger language plpgsql as $$
declare
  v_meta jsonb;
  v_ultimo uuid;
begin
  begin
    if not public.fn_lead_tem_rastreio(new.gclid, new.fbclid, new.ctwa_clid, new.meta_ad_id,
                                       new.utm_source, new.utm_campaign) then
      return new;
    end if;
    if tg_op = 'UPDATE' then
      if new.ctwa_clid is not distinct from old.ctwa_clid
         and new.gclid is not distinct from old.gclid
         and new.fbclid is not distinct from old.fbclid
         and new.meta_ad_id is not distinct from old.meta_ad_id
         and new.utm_source is not distinct from old.utm_source
         and new.utm_campaign is not distinct from old.utm_campaign then
        return new;
      end if;
    end if;

    v_meta := public.fn_lead_entrada_metadata(new.gclid, new.fbclid, new.ctwa_clid, new.meta_ad_id,
                                              new.utm_source, new.utm_medium, new.utm_campaign,
                                              new.traffic_type);

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

drop trigger if exists trg_lead_events_leads_entrada on public.leads;
create trigger trg_lead_events_leads_entrada
  after insert or update of ctwa_clid, gclid, fbclid, meta_ad_id, utm_source, utm_campaign
  on public.leads
  for each row execute function public.fn_lead_events_leads_entrada();

-- ── 3. ETAPA (deals) ───────────────────────────────────────────────────────────────────
-- O BEFORE trigger update_deal_entered_stage_at ja carimbou entered_stage_at = now() na
-- mudanca: a chave usa esse instante, e o backfill acha a mesma para a etapa atual.
create or replace function public.fn_lead_events_deals_etapa()
returns trigger language plpgsql as $$
declare
  v_de uuid;
  v_meta jsonb;
  v_quando timestamptz;
begin
  begin
    if new.lead_id is null or new.stage_id is null then
      return new;
    end if;
    if tg_op = 'UPDATE' then
      if new.stage_id is not distinct from old.stage_id then
        return new;
      end if;
      v_de := old.stage_id;
    end if;

    v_meta := public.fn_lead_events_etapa_metadata(new.id, new.pipeline_id, v_de, new.stage_id);

    if tg_op = 'INSERT' then
      insert into public.lead_events (lead_id, event_type, old_value, new_value, metadata, occurred_at, source, dedupe_key)
      values (new.lead_id, 'etapa', null, v_meta->>'para_label', v_meta,
              coalesce(new.created_at, now()), 'crm',
              'etapa:' || new.id || ':criado')
      on conflict (dedupe_key) where dedupe_key is not null do nothing;
    else
      v_quando := coalesce(new.entered_stage_at, now());
      insert into public.lead_events (lead_id, event_type, old_value, new_value, metadata, occurred_at, source, dedupe_key)
      values (new.lead_id, 'etapa', v_meta->>'de_label', v_meta->>'para_label', v_meta,
              v_quando, 'crm',
              'etapa:' || new.id || ':' || new.stage_id || ':' || extract(epoch from v_quando)::text)
      on conflict (dedupe_key) where dedupe_key is not null do nothing;
    end if;
  exception when others then
    raise warning 'fn_lead_events_deals_etapa: %', sqlerrm;
  end;
  return new;
end $$;

drop trigger if exists trg_lead_events_deals_etapa on public.deals;
create trigger trg_lead_events_deals_etapa
  after insert or update of stage_id
  on public.deals
  for each row execute function public.fn_lead_events_deals_etapa();

-- ── 4. VENDA / VENDA_CANCELADA (sales) ─────────────────────────────────────────────────
create or replace function public.fn_lead_events_sales_venda()
returns trigger language plpgsql as $$
declare
  v_meta jsonb;
  v_source text;
  v_cancelou boolean;
begin
  begin
    if new.lead_id is null then
      return new;
    end if;
    v_meta := public.fn_lead_events_venda_metadata(new);
    v_source := case when new.origin = 'bling' then 'bling' else 'crm' end;

    if tg_op = 'INSERT' then
      insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
      values (new.lead_id, 'venda', new.value::text, v_meta, new.sold_at, v_source,
              'venda:' || new.id)
      on conflict (dedupe_key) where dedupe_key is not null do nothing;
      v_cancelou := new.status = 'cancelada';
    else
      update public.lead_events
         set metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object('status', new.status)
       where dedupe_key = 'venda:' || new.id;
      v_cancelou := new.status = 'cancelada' and old.status is distinct from 'cancelada';
    end if;

    if v_cancelou then
      insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
      values (new.lead_id, 'venda_cancelada', new.value::text, v_meta,
              case when tg_op = 'INSERT' then coalesce(new.bling_event_date, new.sold_at) else now() end,
              v_source, 'venda_cancelada:' || new.id)
      on conflict (dedupe_key) where dedupe_key is not null do nothing;
    end if;
  exception when others then
    raise warning 'fn_lead_events_sales_venda: %', sqlerrm;
  end;
  return new;
end $$;

drop trigger if exists trg_lead_events_sales_venda on public.sales;
create trigger trg_lead_events_sales_venda
  after insert or update of status
  on public.sales
  for each row execute function public.fn_lead_events_sales_venda();

-- Os itens chegam depois da venda (orders.py grava sales e depois sale_items; no update do
-- Bling apaga e regrava). Recalcula metadata.kit dos eventos da venda.
create or replace function public.fn_lead_events_sale_items_kit()
returns trigger language plpgsql as $$
declare
  v_sale uuid;
  v_kit boolean;
begin
  begin
    if tg_op = 'DELETE' then
      v_sale := old.sale_id;
    else
      v_sale := new.sale_id;
    end if;
    v_kit := exists (select 1 from public.sale_items i
                      where i.sale_id = v_sale and i.descricao ilike '%kit degust%');
    update public.lead_events e
       set metadata = coalesce(e.metadata, '{}'::jsonb) || jsonb_build_object('kit', v_kit)
     where e.dedupe_key in ('venda:' || v_sale, 'venda_cancelada:' || v_sale)
       and (e.metadata->'kit') is distinct from to_jsonb(v_kit);
  exception when others then
    raise warning 'fn_lead_events_sale_items_kit: %', sqlerrm;
  end;
  return null;
end $$;

drop trigger if exists trg_lead_events_sale_items_kit on public.sale_items;
create trigger trg_lead_events_sale_items_kit
  after insert or delete or update of descricao
  on public.sale_items
  for each row execute function public.fn_lead_events_sale_items_kit();

-- ── 5. DISPARO (broadcast_leads) ───────────────────────────────────────────────────────
create or replace function public.fn_lead_events_broadcast_disparo()
returns trigger language plpgsql as $$
declare
  v_meta jsonb;
begin
  begin
    if new.lead_id is null or new.sent_at is null then
      return new;
    end if;
    if tg_op = 'UPDATE' then
      if old.sent_at is not null then
        return new;
      end if;
    end if;
    v_meta := public.fn_lead_events_disparo_metadata(new);
    insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
    values (new.lead_id, 'disparo', v_meta->>'broadcast_nome', v_meta, new.sent_at, 'disparo',
            'disparo:' || new.id)
    on conflict (dedupe_key) where dedupe_key is not null do nothing;
  exception when others then
    raise warning 'fn_lead_events_broadcast_disparo: %', sqlerrm;
  end;
  return new;
end $$;

drop trigger if exists trg_lead_events_broadcast_disparo on public.broadcast_leads;
create trigger trg_lead_events_broadcast_disparo
  after insert or update of sent_at
  on public.broadcast_leads
  for each row execute function public.fn_lead_events_broadcast_disparo();
