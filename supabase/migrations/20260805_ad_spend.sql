-- supabase/migrations/20260805_ad_spend.sql
-- Investimento (spend) por campanha/dia, por plataforma. Alimentado pelo sync diário.
CREATE TABLE IF NOT EXISTS ad_spend (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  platform text NOT NULL DEFAULT 'google',
  campaign_id text,
  campaign_name text NOT NULL,
  date date NOT NULL,
  cost numeric NOT NULL DEFAULT 0,
  currency text NOT NULL DEFAULT 'BRL',
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (platform, campaign_id, date)
);

CREATE INDEX IF NOT EXISTS ad_spend_platform_name_date_idx
  ON ad_spend (platform, campaign_name, date);
