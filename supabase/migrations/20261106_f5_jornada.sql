-- supabase/migrations/20261106_f5_jornada.sql
--
-- Frente F5 (06/11/2026): jornada do lead e "Sem rastreio". Especificação: cartões B e C de
-- Canastra-Content-Creator/relatorios/crm-jornada-e-trafego-2026-11.md.
--
--   1. fn_lead_canal (mesma assinatura de 10 args da 20261022c): sem click-id nem UTM, a
--      origem_cadastro dá nome ao canal — inbound "WhatsApp direto", manual "Cadastro manual /
--      disparo", csv_import "Importado (CSV)". Sem p_origem (chamada de 9 args, ex.:
--      analytics.dim_lead) continua "Sem rastreio". Espelho: traffic_report.derive_channel.
--   2. fn_lead_canal_contexto: refina um canal sem sinal de anúncio com o que o CRM sabe
--      (cliente antigo, outro número de WhatsApp, nunca escreveu). Espelho:
--      traffic_report.aplicar_contexto_canal.
--   3. fn_lead_canal_entrada: canal de UM toque (entrada). Espelho: traffic_report.canal_da_entrada.
--   4. Gatilho de entrada (fn_lead_events_leads_entrada):
--      a. a entrada automática do lead inbound sem rastreio passa a se chamar "WhatsApp direto"
--         (era "Orgânico"; o /trafego chamava de "Sem rastreio" — unificado, cartão C item 1).
--         O marcador metadata.sem_rastreio = true continua: é ele que a fusão procura;
--      b. a fusão de 30 min só junta toques da MESMA plataforma, ou quando a entrada anterior é a
--         automática (sem_rastreio). Meta e Google em 10 min viram 2 entradas (cartão B item 1c).
--   5. vw_lead_contexto_canal: tem_inbound, cliente_antigo, numero_antigo por lead (o /trafego lê).
--   6. vw_lead_jornada: uma linha por lead — primeira/última origem, origens na ordem (sem repetir
--      seguidas), n_toques, multicanal, estimado. Espelho: traffic_report.jornada_do_lead.
--   7. SELECT ao consulta_ro e ao service_role nas views; anon e authenticated sem acesso.
--
-- Depende de 20261006 (leads.ja_era_cliente), 20261006b/20261008 (fn_lead_txt,
-- fn_lead_tem_rastreio, fn_lead_entrada_metadata, fn_lead_entrada_source) e 20261022c.
--
-- NAO E APLICADA PELO DEPLOY. Aplicar à mão, pelo psql do supabase_db, ANTES de subir o backend
-- da F5 (o relatório é fail-soft sem ela, mas sem contexto). Reexecutar é seguro.
-- Depois: recarregar o PostgREST com SIGUSR1 (NOTIFY é ignorado na VPS).
-- Rollback: scripts/f5_jornada/rollback_20261106.sql (devolve as definições da 20261022c).

BEGIN;
SET LOCAL lock_timeout = '5s';

-- ── 1. fn_lead_canal com os canais nomeados ────────────────────────────────────────
create or replace function public.fn_lead_canal(
  p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text,
  p_utm_source text, p_utm_medium text, p_traffic_type text,
  p_gbraid text default null, p_wbraid text default null, p_origem text default null)
returns text language sql immutable as $$
  select case
    when public.fn_lead_txt(p_gclid) <> '' or public.fn_lead_txt(p_gbraid) <> ''
      or public.fn_lead_txt(p_wbraid) <> '' then 'Google Ads'
    when public.fn_lead_txt(p_fbclid) <> '' or public.fn_lead_txt(p_ctwa_clid) <> ''
      or public.fn_lead_txt(p_meta_ad_id) <> '' then 'Meta Ads'
    when public.fn_lead_txt(p_origem) = any (array['bling_import', 'reativacao_import']) -- _ORIGENS_IMPORTADAS
      then 'Bling'
    when public.fn_lead_txt(p_utm_source) = any (array['metaads', 'meta_ads', 'meta-ads', 'meta', 'facebook_ads', 'facebookads', 'fb_ads']) -- _META_AD_SOURCES
      then 'Meta Ads'
    when public.fn_lead_txt(p_utm_source) = any (array['google', 'googleads', 'google_ads', 'adwords']) -- _GOOGLE_AD_SOURCES
     and public.fn_lead_txt(p_utm_medium) = any (array['cpc', 'ppc', 'pmax', 'performance_max', 'paid', 'paid_search', 'paidsearch', 'display', 'cpm', 'paid_social', 'paidsocial']) -- _PAID_CHANNEL_MEDIUMS
      then 'Google Ads'
    when public.fn_lead_txt(p_traffic_type) = 'organic' or public.fn_lead_txt(p_utm_source) <> ''
      then 'Orgânico'
    when public.fn_lead_txt(p_origem) = 'inbound' then 'WhatsApp direto' -- _CANAL_POR_ORIGEM
    when public.fn_lead_txt(p_origem) = 'manual' then 'Cadastro manual / disparo' -- _CANAL_POR_ORIGEM
    when public.fn_lead_txt(p_origem) = 'csv_import' then 'Importado (CSV)' -- _CANAL_POR_ORIGEM
    else 'Sem rastreio'
  end
$$;

-- ── 2. fn_lead_canal_contexto ──────────────────────────────────────────────────────
create or replace function public.fn_lead_canal_contexto(
  p_canal text, p_cliente_antigo boolean, p_numero_antigo text, p_tem_inbound boolean,
  p_lead_channel text default null)
returns text language sql immutable as $$
  select case
    when p_canal is null
      or p_canal <> all (array['WhatsApp direto', 'Cadastro manual / disparo', 'Importado (CSV)', 'Sem rastreio']) -- _CANAIS_SEM_SINAL
      then p_canal
    when coalesce(p_cliente_antigo, false) then 'Cliente antigo'
    when public.fn_lead_txt(p_numero_antigo) <> '' and p_canal in ('WhatsApp direto', 'Sem rastreio')
      then 'Número antigo / outro número'
    -- leads.channel de cadastro vence o 'inbound' padrão (470 leads 'manual' + 'inbound', 10/11)
    when p_canal = 'WhatsApp direto'
     and public.fn_lead_txt(p_lead_channel) = any (array['campaign', 'manual', 'broadcast', 'bling', 'csv']) then
      case public.fn_lead_txt(p_lead_channel) -- _CANAL_POR_LEAD_CHANNEL
        when 'campaign' then 'Cadastro manual / disparo'
        when 'manual' then 'Cadastro manual / disparo'
        when 'broadcast' then 'Cadastro manual / disparo'
        when 'bling' then 'Bling'
        when 'csv' then 'Importado (CSV)'
        else 'Sem rastreio'
      end
    when p_canal = 'WhatsApp direto' and p_tem_inbound is false then 'Sem rastreio'
    else p_canal
  end
$$;

-- ── 3. fn_lead_rastreio_toque e fn_lead_canal_entrada ──────────────────────────────
-- A entrada é um retrato das colunas do lead: o clique NOVO do Meta chega com o gclid ANTIGO (e
-- vice-versa). Revisão de 12/11/2026: 7 cliques do Meta gravados como "Google Ads". Com click id
-- novo de uma plataforma, saem os click ids de OUTRA plataforma iguais aos do toque anterior, o
-- UTM pago de outra plataforma que não mudou e, se o anúncio do Meta saiu, a campanha dele.
-- Espelho: traffic_report.rastreio_do_toque.
-- plpgsql, não SQL: as funções SQL com CTE eram replanejadas a cada chamada (14 ms por toque,
-- a vw_lead_jornada passava de 30 s em produção em 13/11). Mesma lógica.
create or replace function public.fn_lead_rastreio_toque(p_meta jsonb, p_ant jsonb)
returns jsonb language plpgsql immutable as $$
declare
  c_plataforma constant jsonb := '{"gclid": "google", "gbraid": "google", "wbraid": "google", "fbclid": "meta", "ctwa_clid": "meta", "meta_ad_id": "meta"}'; -- _CLICK_PLATAFORMA
  v_k text;
  v_pl text;
  v_novas text[] := '{}';
  v_sai text[] := '{}';
  v_utm text;
begin
  if p_meta is null or p_ant is null then
    return p_meta;
  end if;
  for v_k, v_pl in select key, value from jsonb_each_text(c_plataforma) loop
    if btrim(coalesce(p_meta->>v_k, '')) <> ''
       and btrim(coalesce(p_meta->>v_k, '')) <> btrim(coalesce(p_ant->>v_k, ''))
       and not (v_pl = any (v_novas)) then
      v_novas := v_novas || v_pl;
    end if;
  end loop;
  if cardinality(v_novas) = 0 then
    return p_meta;
  end if;
  for v_k, v_pl in select key, value from jsonb_each_text(c_plataforma) loop
    if not (v_pl = any (v_novas))
       and btrim(coalesce(p_meta->>v_k, '')) <> ''
       and btrim(coalesce(p_meta->>v_k, '')) = btrim(coalesce(p_ant->>v_k, '')) then
      v_sai := v_sai || v_k;
    end if;
  end loop;
  if 'meta_ad_id' = any (v_sai) then
    v_sai := v_sai || array['campanha_id', 'campanha_nome'];
  end if;
  v_utm := case
    when public.fn_lead_txt(p_meta->>'utm_source') = any (array['metaads', 'meta_ads', 'meta-ads', 'meta', 'facebook_ads', 'facebookads', 'fb_ads']) -- _META_AD_SOURCES
      then 'meta'
    when public.fn_lead_txt(p_meta->>'utm_source') = any (array['google', 'googleads', 'google_ads', 'adwords']) -- _GOOGLE_AD_SOURCES
     and public.fn_lead_txt(p_meta->>'utm_medium') = any (array['cpc', 'ppc', 'pmax', 'performance_max', 'paid', 'paid_search', 'paidsearch', 'display', 'cpm', 'paid_social', 'paidsocial']) -- _PAID_CHANNEL_MEDIUMS
      then 'google'
  end;
  if v_utm is not null and not (v_utm = any (v_novas))
     and btrim(coalesce(p_meta->>'utm_source', '')) = btrim(coalesce(p_ant->>'utm_source', ''))
     and btrim(coalesce(p_meta->>'utm_campaign', '')) = btrim(coalesce(p_ant->>'utm_campaign', '')) then
    v_sai := v_sai || array['utm_source', 'utm_medium', 'utm_campaign'];
  end if;
  return p_meta - v_sai;
end $$;

create or replace function public.fn_lead_canal_entrada(p_metadata jsonb, p_new_value text,
                                                        p_anterior jsonb default null)
returns text language plpgsql immutable as $$
declare
  v_rotulo text := coalesce(nullif(btrim(p_metadata->>'canal'), ''), nullif(btrim(p_new_value), ''));
  m jsonb;
  v_canal text;
begin
  if v_rotulo = 'Bling' then -- lead importado: o gatilho já aplicou a origem
    return 'Bling';
  end if;
  m := public.fn_lead_rastreio_toque(p_metadata, p_anterior);
  v_canal := public.fn_lead_canal(m->>'gclid', m->>'fbclid', m->>'ctwa_clid', m->>'meta_ad_id',
                                  m->>'utm_source', m->>'utm_medium', m->>'traffic_type',
                                  m->>'gbraid', m->>'wbraid');
  if v_canal <> 'Sem rastreio' then
    return v_canal;
  end if;
  if v_rotulo = 'Orgânico' and p_metadata->>'sem_rastreio' = 'true' then
    return 'WhatsApp direto';
  end if;
  return coalesce(v_rotulo, 'Sem rastreio');
end $$;

GRANT EXECUTE ON FUNCTION public.fn_lead_canal_contexto(text,boolean,text,boolean,text)
  TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.fn_lead_canal_entrada(jsonb,text,jsonb) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.fn_lead_rastreio_toque(jsonb,jsonb) TO authenticated, service_role;

-- ── 4. Gatilho de entrada ──────────────────────────────────────────────────────────
create or replace function public.fn_lead_events_leads_entrada()
returns trigger language plpgsql security definer set search_path = public, pg_temp as $$
declare
  v_meta jsonb;
  v_ultimo uuid;
  v_ultimo_meta jsonb;
  v_ultimo_valor text;
  v_alvo uuid;
  v_tem_rastreio boolean;
  v_inicial boolean := (tg_op = 'INSERT');
begin
  -- Guardas baratas FORA do bloco com exception: ele abre subtransacao por linha.
  v_tem_rastreio := public.fn_lead_tem_rastreio(new.gclid, new.fbclid, new.ctwa_clid, new.meta_ad_id,
                                                new.utm_source, new.utm_campaign,
                                                new.gbraid, new.wbraid);
  if not v_tem_rastreio then
    -- D1b: so o lead que chegou pelo WhatsApp (inbound) ganha entrada sem rastreio.
    if tg_op <> 'INSERT' or coalesce(new.origem_cadastro, 'inbound') <> 'inbound' then
      return new;
    end if;
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
    -- D1b + F5: lead inbound sem rastreio = "WhatsApp direto" (antes "Orgânico"). O rastreio que
    -- chegar em ate 30 min funde nesta mesma linha (abaixo); o que chegar depois so substitui
    -- esta entrada se for o meta_ad_id (anuncio que trouxe o lead).
    if not v_tem_rastreio then
      insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
      values (new.id, 'entrada', 'WhatsApp direto',
              jsonb_build_object('canal', 'WhatsApp direto', 'sem_rastreio', true),
              coalesce(new.created_at, now()), 'inbound',
              'entrada:lead:' || new.id || ':inicial')
      on conflict (dedupe_key) where dedupe_key is not null do nothing;
      return new;
    end if;

    v_meta := public.fn_lead_entrada_metadata(new.gclid, new.fbclid, new.ctwa_clid, new.meta_ad_id,
                                              new.utm_source, new.utm_medium, new.utm_campaign,
                                              new.traffic_type, new.gbraid, new.wbraid);
    -- canal com a origem do cadastro (regra "Bling" para importado)
    v_meta := v_meta || jsonb_build_object('canal',
                public.fn_lead_canal(new.gclid, new.fbclid, new.ctwa_clid, new.meta_ad_id,
                                     new.utm_source, new.utm_medium, new.traffic_type,
                                     new.gbraid, new.wbraid, new.origem_cadastro));

    -- so meta_ad_id mudou (ctwa_clid e o resto iguais): e ENRIQUECIMENTO da mesma entrada,
    -- nunca entrada nova (webhook: meta_ad_id chega depois do ctwa_clid; script do P2).
    if tg_op = 'UPDATE'
       and new.ctwa_clid is not distinct from old.ctwa_clid
       and new.gclid is not distinct from old.gclid
       and new.gbraid is not distinct from old.gbraid
       and new.wbraid is not distinct from old.wbraid
       and new.fbclid is not distinct from old.fbclid
       and new.utm_source is not distinct from old.utm_source
       and new.utm_campaign is not distinct from old.utm_campaign then
      if public.fn_lead_txt(new.ctwa_clid) <> '' then
        select e.id into v_alvo from public.lead_events e
         where e.lead_id = new.id and e.event_type = 'entrada'
           and e.metadata->>'ctwa_clid' = new.ctwa_clid
         order by e.occurred_at desc, e.created_at desc
         limit 1;
        if v_alvo is not null then
          update public.lead_events alvo
             set metadata = coalesce(alvo.metadata, '{}'::jsonb)
                            || jsonb_build_object('meta_ad_id', new.meta_ad_id)
                            || case when v_meta->>'campanha_id' is not null
                                    then jsonb_build_object('campanha_id', v_meta->'campanha_id',
                                                            'campanha_nome', v_meta->'campanha_nome')
                                    else '{}'::jsonb end
           where alvo.id = v_alvo;
          return new;
        end if;
      end if;
      update public.lead_events
         set metadata = (coalesce(metadata, '{}'::jsonb) - 'sem_rastreio') || v_meta,
             new_value = v_meta->>'canal',
             source = public.fn_lead_entrada_source(v_meta)
       where dedupe_key = 'entrada:lead:' || new.id || ':inicial'
         and event_type = 'entrada'
         and metadata->>'sem_rastreio' = 'true';
      if found then
        return new;
      end if;
      if exists (select 1 from public.lead_events e
                  where e.lead_id = new.id and e.event_type = 'entrada') then
        return new;
      end if;
      v_inicial := true;
    end if;

    if tg_op = 'UPDATE' and not v_inicial then
      -- F5 (revisão 12/11): o toque é só o que mudou. Clique novo do Meta não leva o gclid antigo.
      v_meta := public.fn_lead_rastreio_toque(v_meta,
                  public.fn_lead_entrada_metadata(old.gclid, old.fbclid, old.ctwa_clid, old.meta_ad_id,
                                                  old.utm_source, old.utm_medium, old.utm_campaign,
                                                  old.traffic_type, old.gbraid, old.wbraid));
      v_meta := v_meta || jsonb_build_object('canal',
                  public.fn_lead_canal(v_meta->>'gclid', v_meta->>'fbclid', v_meta->>'ctwa_clid',
                                       v_meta->>'meta_ad_id', v_meta->>'utm_source',
                                       v_meta->>'utm_medium', new.traffic_type, v_meta->>'gbraid',
                                       v_meta->>'wbraid', new.origem_cadastro));
      select e.id, e.metadata, e.new_value into v_ultimo, v_ultimo_meta, v_ultimo_valor
        from public.lead_events e
       where e.lead_id = new.id
         and e.event_type = 'entrada'
         and e.occurred_at >= now() - interval '30 minutes'
       order by e.occurred_at desc, e.created_at desc
       limit 1;
      -- F5 (cartão B 1c): so funde a MESMA plataforma, ou a entrada automatica sem rastreio.
      -- Clique do Meta e do Google em 10 min sao dois toques, nao um.
      if v_ultimo is not null
         and (v_ultimo_meta->>'sem_rastreio' = 'true'
              or public.fn_lead_canal_entrada(v_ultimo_meta, v_ultimo_valor) = v_meta->>'canal') then
        update public.lead_events
           set metadata = (coalesce(metadata, '{}'::jsonb) - 'sem_rastreio') || v_meta,
               new_value = v_meta->>'canal',
               source = public.fn_lead_entrada_source(v_meta)
         where id = v_ultimo;
        return new;
      end if;
    end if;

    insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
    values (new.id, 'entrada', v_meta->>'canal', v_meta,
            case when v_inicial then coalesce(new.created_at, now()) else now() end,
            public.fn_lead_entrada_source(v_meta),
            case when v_inicial then 'entrada:lead:' || new.id || ':inicial'
                 else 'entrada:lead:' || new.id || ':' || extract(epoch from clock_timestamp())::text end)
    on conflict (dedupe_key) where dedupe_key is not null do nothing;
  exception when others then
    raise warning 'fn_lead_events_leads_entrada: %', sqlerrm;
  end;
  return new;
end $$;
-- Funcao de trigger nao e RPC.
revoke execute on function public.fn_lead_events_leads_entrada() from public, anon, authenticated;

-- ── 5. vw_lead_contexto_canal ──────────────────────────────────────────────────────
-- "Número dos anúncios" = canal da 1ª conversa de quem chegou por anúncio do Meta (ctwa_clid ou
-- meta_ad_id). A 1ª conversa de um lead em outro canal (ou na Evolution legada) é "outro número".
create or replace view public.vw_lead_contexto_canal with (security_invoker = true) as
with primeira_conversa as (
  select distinct on (c.lead_id) c.lead_id, c.channel_id
    from public.conversations c
   where c.lead_id is not null and c.channel_id is not null
   order by c.lead_id, c.created_at, c.id
), canais_anuncio as (
  select distinct pc.channel_id
    from primeira_conversa pc
    join public.leads la on la.id = pc.lead_id
   where public.fn_lead_txt(la.ctwa_clid) <> '' or public.fn_lead_txt(la.meta_ad_id) <> ''
)
select
  l.id as lead_id,
  (l.last_customer_message_at is not null
   or exists (select 1 from public.conversations c
               where c.lead_id = l.id and c.last_customer_message_at is not null)) as tem_inbound,
  (coalesce(l.ja_era_cliente, false)
   or exists (select 1 from public.sales s
               where s.lead_id = l.id
                 and (s.sold_at at time zone 'America/Sao_Paulo')::date
                     < (l.created_at at time zone 'America/Sao_Paulo')::date)) as cliente_antigo,
  case
    when pc.channel_id is null then null
    when ch.provider = 'evolution'
      or not exists (select 1 from canais_anuncio ca where ca.channel_id = pc.channel_id)
      then coalesce(nullif(btrim(ch.name), ''), ch.phone)
  end as numero_antigo
from public.leads l
left join primeira_conversa pc on pc.lead_id = l.id
left join public.channels ch on ch.id = pc.channel_id;

comment on view public.vw_lead_contexto_canal is
  'F5: o que o CRM sabe de como o lead entrou, para refinar o canal sem anúncio '
  '(fn_lead_canal_contexto). tem_inbound = já escreveu; cliente_antigo = ja_era_cliente ou venda '
  'antes do cadastro; numero_antigo = nome do canal da 1ª conversa quando não é o dos anúncios.';

-- ── 6. vw_lead_jornada ─────────────────────────────────────────────────────────────
create or replace view public.vw_lead_jornada with (security_invoker = true) as
with ordenadas as (
  select e.lead_id, e.id, e.occurred_at, e.metadata, e.new_value,
         lag(e.metadata) over (partition by e.lead_id order by e.occurred_at, e.id) as anterior
    from public.lead_events e
   where e.event_type = 'entrada' and e.occurred_at is not null
), toques as (
  select o.lead_id, o.id, o.occurred_at,
         public.fn_lead_canal_entrada(o.metadata, o.new_value, o.anterior) as canal
    from ordenadas o
), seq as (
  select t.*, lag(t.canal) over (partition by t.lead_id order by t.occurred_at, t.id) as anterior
    from toques t
), agg as (
  select t.lead_id,
         (array_agg(t.canal order by t.occurred_at, t.id))[1] as primeira_canal,
         min(t.occurred_at) as primeira_em,
         (array_agg(t.canal order by t.occurred_at desc, t.id desc))[1] as ultima_canal,
         max(t.occurred_at) as ultima_em,
         count(*)::int as n_toques,
         count(distinct t.canal) >= 2 as multicanal
    from toques t
   group by t.lead_id
), origens as (
  select s.lead_id, string_agg(s.canal, ' → ' order by s.occurred_at, s.id) as origens
    from seq s
   where s.anterior is distinct from s.canal
   group by s.lead_id
), base as (
  select l.id as lead_id, l.channel as lead_channel, ctx.cliente_antigo, ctx.numero_antigo,
         ctx.tem_inbound,
         public.fn_lead_canal(l.gclid, l.fbclid, l.ctwa_clid, l.meta_ad_id, l.utm_source,
                              l.utm_medium, l.traffic_type, l.gbraid, l.wbraid,
                              l.origem_cadastro) as canal_colunas
    from public.leads l
    left join public.vw_lead_contexto_canal ctx on ctx.lead_id = l.id
)
-- tem_inbound ("nunca escreveu") só vale para o lead SEM entrada: a entrada já prova como ele chegou.
select
  b.lead_id,
  public.fn_lead_canal_contexto(coalesce(a.primeira_canal, b.canal_colunas), b.cliente_antigo,
                                b.numero_antigo, case when a.lead_id is null then b.tem_inbound end,
                                b.lead_channel) as primeira_origem,
  a.primeira_em,
  public.fn_lead_canal_contexto(coalesce(a.ultima_canal, b.canal_colunas), b.cliente_antigo,
                                b.numero_antigo, case when a.lead_id is null then b.tem_inbound end,
                                b.lead_channel) as ultima_origem,
  a.ultima_em,
  coalesce(o.origens,
           public.fn_lead_canal_contexto(b.canal_colunas, b.cliente_antigo, b.numero_antigo,
                                         b.tem_inbound, b.lead_channel)) as origens,
  coalesce(a.n_toques, 0) as n_toques,
  coalesce(a.multicanal, false) as multicanal,
  (a.lead_id is null) as estimado
from base b
left join agg a on a.lead_id = b.lead_id
left join origens o on o.lead_id = b.lead_id;

comment on view public.vw_lead_jornada is
  'F5: jornada do lead pela linha do tempo (entradas). primeira/ultima_origem com o contexto '
  '(cliente antigo, outro número); origens = canais na ordem sem repetir seguidos; estimado = '
  'lead sem entrada (canal das colunas). A ultima_origem aqui é a de hoje; o /trafego corta na '
  'venda ou no repasse (traffic_report.jornada_do_lead).';

-- ── 7. Acesso ──────────────────────────────────────────────────────────────────────
revoke all on public.vw_lead_contexto_canal from anon, authenticated;
revoke all on public.vw_lead_jornada from anon, authenticated;
grant select on public.vw_lead_contexto_canal to service_role;
grant select on public.vw_lead_jornada to service_role;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'consulta_ro') THEN
    GRANT SELECT ON public.vw_lead_contexto_canal TO consulta_ro;
    GRANT SELECT ON public.vw_lead_jornada TO consulta_ro;
    GRANT EXECUTE ON FUNCTION public.fn_lead_canal_contexto(text,boolean,text,boolean,text) TO consulta_ro;
    GRANT EXECUTE ON FUNCTION public.fn_lead_canal_entrada(jsonb,text,jsonb) TO consulta_ro;
    GRANT EXECUTE ON FUNCTION public.fn_lead_rastreio_toque(jsonb,jsonb) TO consulta_ro;
  END IF;
END $$;

COMMIT;
