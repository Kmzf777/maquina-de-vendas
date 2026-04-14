-- 009_deals.sql
-- Create deals table and migrate existing seller pipeline data

-- 1. Create deals table
CREATE TABLE IF NOT EXISTS deals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    title text NOT NULL,
    value numeric(12,2) DEFAULT 0,
    stage text NOT NULL DEFAULT 'novo',
    category text,
    expected_close_date date,
    assigned_to text,
    closed_at timestamptz,
    lost_reason text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deals_lead_id ON deals(lead_id);
CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);
CREATE INDEX IF NOT EXISTS idx_deals_category ON deals(category);

-- 2. Migrate existing lead data to deals (only if legacy columns exist)
DO $$
DECLARE
  has_seller_stage boolean;
  has_sale_value boolean;
BEGIN
  SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'leads' AND column_name = 'seller_stage'
  ) INTO has_seller_stage;

  SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'leads' AND column_name = 'sale_value'
  ) INTO has_sale_value;

  IF has_seller_stage AND has_sale_value THEN
    INSERT INTO deals (lead_id, title, value, stage, created_at)
    SELECT
      id,
      COALESCE(name, phone) || ' - Oportunidade',
      COALESCE(sale_value, 0),
      CASE seller_stage
        WHEN 'novo' THEN 'novo'
        WHEN 'em_contato' THEN 'contato'
        WHEN 'negociacao' THEN 'negociacao'
        WHEN 'fechado' THEN 'fechado_ganho'
        WHEN 'perdido' THEN 'fechado_perdido'
        ELSE 'novo'
      END,
      created_at
    FROM leads
    WHERE human_control = true
      AND seller_stage IS NOT NULL
      AND seller_stage != '';

  ELSIF has_seller_stage THEN
    INSERT INTO deals (lead_id, title, stage, created_at)
    SELECT
      id,
      COALESCE(name, phone) || ' - Oportunidade',
      CASE seller_stage
        WHEN 'novo' THEN 'novo'
        WHEN 'em_contato' THEN 'contato'
        WHEN 'negociacao' THEN 'negociacao'
        WHEN 'fechado' THEN 'fechado_ganho'
        WHEN 'perdido' THEN 'fechado_perdido'
        ELSE 'novo'
      END,
      created_at
    FROM leads
    WHERE human_control = true
      AND seller_stage IS NOT NULL
      AND seller_stage != '';
  END IF;
END $$;

-- 3. Drop deprecated columns from leads (safe — IF EXISTS)
ALTER TABLE leads DROP COLUMN IF EXISTS seller_stage;
ALTER TABLE leads DROP COLUMN IF EXISTS sale_value;

-- 4. Enable realtime for deals
ALTER PUBLICATION supabase_realtime ADD TABLE deals;
