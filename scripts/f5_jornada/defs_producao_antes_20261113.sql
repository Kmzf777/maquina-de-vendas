Output format is unaligned.
CREATE OR REPLACE FUNCTION public.fn_lead_canal(p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text, p_utm_source text, p_utm_medium text, p_traffic_type text, p_gbraid text DEFAULT NULL::text, p_wbraid text DEFAULT NULL::text, p_origem text DEFAULT NULL::text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
AS $function$
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
    else 'Sem rastreio'
  end
$function$
;
CREATE OR REPLACE FUNCTION public.fn_lead_events_leads_entrada()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare
  v_meta jsonb;
  v_ultimo uuid;
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
    -- D1b: lead inbound sem rastreio = "Orgânico". O rastreio que chegar em ate 30 min funde
    -- nesta mesma linha (abaixo); o que chegar depois so substitui esta entrada se for o
    -- meta_ad_id (anuncio que trouxe o lead).
    if not v_tem_rastreio then
      insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
      values (new.id, 'entrada', 'Orgânico',
              jsonb_build_object('canal', 'Orgânico', 'sem_rastreio', true),
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
    -- nunca entrada nova. Acontece no webhook (meta_ad_id chega depois do ctwa_clid) e no
    -- scripts/trafego/recuperar_meta_ad_id.py do P2 (~687 leads antigos), que sem esta regra
    -- ganhariam entradas falsas datadas do dia do script. Atualiza a entrada mais recente com
    -- o MESMO ctwa_clid. b67f1c6b: sem ela, a entrada "Orgânico" automatica vira a do anuncio;
    -- e o lead SEM entrada nenhuma ganha a entrada (datada do cadastro) em vez de ficar sem.
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
      select e.id into v_ultimo
        from public.lead_events e
       where e.lead_id = new.id
         and e.event_type = 'entrada'
         and e.occurred_at >= now() - interval '30 minutes'
       order by e.occurred_at desc, e.created_at desc
       limit 1;
      if v_ultimo is not null then
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
                 else 'entrada:lead:' || new.id || ':' || extract(epoch from now())::text end)
    on conflict (dedupe_key) where dedupe_key is not null do nothing;
  exception when others then
    raise warning 'fn_lead_events_leads_entrada: %', sqlerrm;
  end;
  return new;
end $function$
;
fn_lead_canal(text,text,text,text,text,text,text,text,text,text)

