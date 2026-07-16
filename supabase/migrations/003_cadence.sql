-- 003_cadence.sql
-- Legacy cadence columns on campaigns (migrated to new schema in 010).

DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_interval_hours int DEFAULT 24; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_send_start_hour int DEFAULT 7; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_send_end_hour int DEFAULT 18; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_cooldown_hours int DEFAULT 48; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_max_messages int DEFAULT 8; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_sent int DEFAULT 0; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_responded int DEFAULT 0; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_exhausted int DEFAULT 0; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_cooled int DEFAULT 0; EXCEPTION WHEN duplicate_column THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS cadence_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id uuid REFERENCES campaigns(id) ON DELETE CASCADE,
    stage text NOT NULL,
    step_order int NOT NULL,
    message_text text NOT NULL,
    created_at timestamptz DEFAULT now(),
    UNIQUE(campaign_id, stage, step_order)
);

CREATE TABLE IF NOT EXISTS cadence_state (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE UNIQUE,
    campaign_id uuid REFERENCES campaigns(id) ON DELETE CASCADE,
    current_step int DEFAULT 0,
    status text DEFAULT 'active',
    total_messages_sent int DEFAULT 0,
    max_messages int DEFAULT 8,
    next_send_at timestamptz,
    cooldown_until timestamptz,
    responded_at timestamptz,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cadence_steps_campaign ON cadence_steps(campaign_id);
CREATE INDEX IF NOT EXISTS idx_cadence_state_lead ON cadence_state(lead_id);
CREATE INDEX IF NOT EXISTS idx_cadence_state_status ON cadence_state(status);
CREATE INDEX IF NOT EXISTS idx_cadence_state_next_send ON cadence_state(next_send_at);

CREATE OR REPLACE FUNCTION increment_cadence_sent(campaign_id_param uuid)
RETURNS void AS $$ BEGIN UPDATE campaigns SET cadence_sent = cadence_sent + 1 WHERE id = campaign_id_param; END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION increment_cadence_responded(campaign_id_param uuid)
RETURNS void AS $$ BEGIN UPDATE campaigns SET cadence_responded = cadence_responded + 1 WHERE id = campaign_id_param; END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION increment_cadence_exhausted(campaign_id_param uuid)
RETURNS void AS $$ BEGIN UPDATE campaigns SET cadence_exhausted = cadence_exhausted + 1 WHERE id = campaign_id_param; END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION increment_cadence_cooled(campaign_id_param uuid)
RETURNS void AS $$ BEGIN UPDATE campaigns SET cadence_cooled = cadence_cooled + 1 WHERE id = campaign_id_param; END; $$ LANGUAGE plpgsql;
