-- 002_lead_enrichment.sql
-- Run this in Supabase SQL Editor

-- B2B fields
ALTER TABLE leads ADD COLUMN IF NOT EXISTS cnpj text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS razao_social text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS nome_fantasia text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS endereco text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS telefone_comercial text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS inscricao_estadual text;

-- Sale value
ALTER TABLE leads ADD COLUMN IF NOT EXISTS sale_value numeric DEFAULT 0;

-- Metric fields
ALTER TABLE leads ADD COLUMN IF NOT EXISTS entered_stage_at timestamptz DEFAULT now();
ALTER TABLE leads ADD COLUMN IF NOT EXISTS first_response_at timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS on_hold boolean DEFAULT false;

-- Index for stats queries
CREATE INDEX IF NOT EXISTS idx_leads_seller_stage ON leads(seller_stage);
CREATE INDEX IF NOT EXISTS idx_leads_entered_stage_at ON leads(entered_stage_at);

-- Trigger to auto-update entered_stage_at when stage changes
CREATE OR REPLACE FUNCTION update_entered_stage_at()
RETURNS trigger AS $$
BEGIN
    IF OLD.stage IS DISTINCT FROM NEW.stage OR OLD.seller_stage IS DISTINCT FROM NEW.seller_stage THEN
        NEW.entered_stage_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_entered_stage_at ON leads;
CREATE TRIGGER trg_update_entered_stage_at
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION update_entered_stage_at();
