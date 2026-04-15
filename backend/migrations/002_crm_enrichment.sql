-- 002_crm_enrichment.sql
-- Merges: 002_crm_columns + 002_lead_enrichment + 002_tags

-- CRM control columns
DO $$ BEGIN ALTER TABLE leads ADD COLUMN human_control boolean DEFAULT false;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN ALTER TABLE leads ADD COLUMN assigned_to uuid;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN ALTER TABLE leads ADD COLUMN channel text DEFAULT 'evolution';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- B2B enrichment
DO $$ BEGIN ALTER TABLE leads ADD COLUMN cnpj text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN razao_social text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN nome_fantasia text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN endereco text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN telefone_comercial text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN email text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN instagram text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN inscricao_estadual text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN sale_value numeric DEFAULT 0; EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Stage tracking
DO $$ BEGIN ALTER TABLE leads ADD COLUMN seller_stage text DEFAULT 'novo'; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN entered_stage_at timestamptz DEFAULT now(); EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN first_response_at timestamptz; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN on_hold boolean DEFAULT false; EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Messages tracking
DO $$ BEGIN ALTER TABLE messages ADD COLUMN sent_by text DEFAULT 'agent'; EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_leads_seller_stage ON leads(seller_stage);
CREATE INDEX IF NOT EXISTS idx_leads_human_control ON leads(human_control);
CREATE INDEX IF NOT EXISTS idx_leads_entered_stage_at ON leads(entered_stage_at);

-- Trigger: auto-update entered_stage_at on stage change
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
    FOR EACH ROW EXECUTE FUNCTION update_entered_stage_at();

-- Tags
CREATE TABLE IF NOT EXISTS tags (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    color text NOT NULL DEFAULT '#8b5cf6',
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lead_tags (
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    tag_id uuid REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (lead_id, tag_id)
);

-- Realtime
ALTER PUBLICATION supabase_realtime ADD TABLE leads;
ALTER PUBLICATION supabase_realtime ADD TABLE messages;
ALTER PUBLICATION supabase_realtime ADD TABLE campaigns;
