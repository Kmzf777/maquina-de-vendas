CREATE OR REPLACE FUNCTION public.fn_lead_tem_rastreio(p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text, p_utm_source text, p_utm_campaign text, p_gbraid text DEFAULT NULL::text, p_wbraid text DEFAULT NULL::text)
 RETURNS boolean
 LANGUAGE sql
 IMMUTABLE
AS $function$
  select public.fn_lead_txt(p_gclid) <> '' or public.fn_lead_txt(p_fbclid) <> ''
      or public.fn_lead_txt(p_ctwa_clid) <> '' or public.fn_lead_txt(p_meta_ad_id) <> ''
      or public.fn_lead_txt(p_utm_source) <> '' or public.fn_lead_txt(p_utm_campaign) <> ''
      or public.fn_lead_txt(p_gbraid) <> '' or public.fn_lead_txt(p_wbraid) <> ''
$function$
;
