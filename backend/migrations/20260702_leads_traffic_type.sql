-- 20260702_leads_traffic_type.sql
-- Classificação de origem do lead: tráfego PAGO x ORGÂNICO.
--
-- Derivado no backend a partir dos identificadores já capturados:
--   * gclid / fbclid / ctwa_clid presentes         -> 'paid'
--   * utm_medium pago (cpc, paid_social, cpm, ...)  -> 'paid'
--   * sinal de UTM orgânico (utm_source/medium/campaign, ex. bio/organic) -> 'organic'
--   * sem nenhum sinal                              -> NULL (não classificado)
-- Gravado no lp_webhook (caminho Landing Page) e no meta_router (CTWA => paid).
--
-- Idempotente: seguro reaplicar. Aplicar em HOMOLOG e depois PROD (paridade de schema).

ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS traffic_type text NULL;

COMMENT ON COLUMN leads.traffic_type IS
    'Origem do acesso: paid | organic | NULL (não classificado). Derivado de gclid/fbclid/ctwa_clid/utm_medium.';
