CREATE OR REPLACE FUNCTION public.fn_lead_entrada_metadata(p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text, p_utm_source text, p_utm_medium text, p_utm_campaign text, p_traffic_type text, p_gbraid text DEFAULT NULL::text, p_wbraid text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
AS $function$
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
$function$
;
