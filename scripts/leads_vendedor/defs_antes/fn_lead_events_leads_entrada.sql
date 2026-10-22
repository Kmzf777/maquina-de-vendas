CREATE OR REPLACE FUNCTION public.fn_lead_events_leads_entrada()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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
end $function$
;
