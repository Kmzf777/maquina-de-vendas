-- 20260618_leads_traffic_tracking.sql
-- Rastreamento de tráfego tradicional (Landing Pages / site).
--
-- Adiciona os identificadores de clique e parâmetros UTM enviados pelo navegador
-- quando um lead chega via formulário de landing page vindo de campanhas Meta/Google:
--   * fbclid       — Facebook click id (Meta Ads no site → base p/ CAPI quando não há ctwa_clid)
--   * gclid        — Google click id (base p/ Google Offline Conversions / Vendas Offline)
--   * utm_source   — origem da campanha (ex: facebook, google)
--   * utm_medium   — meio (ex: cpc, paid_social)
--   * utm_campaign — nome da campanha
--
-- Complementa o `ctwa_clid` (anúncios Click-to-WhatsApp): ctwa_clid/fbclid alimentam a
-- Meta CAPI; gclid alimenta o Google. Extração defensiva no lp_webhook (campos ausentes
-- no payload → NULL). Identidade/dedup do lead continua por `phone`.
--
-- Idempotente: seguro reaplicar. Aplicar em HOMOLOG e depois PROD (paridade de schema).

ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS fbclid       text NULL,
    ADD COLUMN IF NOT EXISTS gclid        text NULL,
    ADD COLUMN IF NOT EXISTS utm_source   text NULL,
    ADD COLUMN IF NOT EXISTS utm_medium   text NULL,
    ADD COLUMN IF NOT EXISTS utm_campaign text NULL;

COMMENT ON COLUMN leads.fbclid       IS 'Facebook click id capturado no formulário da landing page. Base p/ Meta CAPI (fbc) quando não houver ctwa_clid. NULL = origem não rastreada.';
COMMENT ON COLUMN leads.gclid        IS 'Google click id capturado no formulário da landing page. Base p/ Google Offline Conversions (Vendas Offline). NULL = origem não rastreada.';
COMMENT ON COLUMN leads.utm_source   IS 'utm_source da campanha que originou o lead (ex: facebook, google).';
COMMENT ON COLUMN leads.utm_medium   IS 'utm_medium da campanha (ex: cpc, paid_social).';
COMMENT ON COLUMN leads.utm_campaign IS 'utm_campaign — nome da campanha que originou o lead.';
