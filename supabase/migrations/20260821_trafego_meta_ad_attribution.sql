-- supabase/migrations/20260821_trafego_meta_ad_attribution.sql
-- Atribuição de campanha para leads do Meta Ads (Click-to-WhatsApp).
--
-- Um lead que chega por CTWA não traz utm_campaign nenhum: o webhook da Meta só manda
-- `referral.source_id`, que é o ID do ANÚNCIO. Sem guardar esse id e sem o mapa
-- anúncio→campanha, o investimento do Meta não gruda em campanha nenhuma no /trafego
-- (era o caso: 100% das linhas do Meta com investimento R$ 0,00 e ROAS vazio).

-- 1. O anúncio que originou o lead (first-touch, carimbado pelo webhook).
ALTER TABLE leads ADD COLUMN IF NOT EXISTS meta_ad_id text;

CREATE INDEX IF NOT EXISTS leads_meta_ad_id_idx ON leads (meta_ad_id) WHERE meta_ad_id IS NOT NULL;

-- 2. Mapa anúncio→campanha, alimentado pelo sync do Meta Ads (insights level=ad).
CREATE TABLE IF NOT EXISTS meta_ad_campaigns (
  ad_id text PRIMARY KEY,
  campaign_id text NOT NULL,
  campaign_name text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS meta_ad_campaigns_campaign_idx ON meta_ad_campaigns (campaign_id);
