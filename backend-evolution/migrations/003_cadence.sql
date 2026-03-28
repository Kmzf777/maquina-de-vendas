-- 003_cadence.sql
-- Run this in Supabase SQL Editor after 002_crm_columns.sql

-- Cadence configuration columns on campaigns
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_interval_hours int DEFAULT 24;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_send_start_hour int DEFAULT 7;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_send_end_hour int DEFAULT 18;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_cooldown_hours int DEFAULT 48;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_max_messages int DEFAULT 8;

-- Cadence counters on campaigns
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_sent int DEFAULT 0;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_responded int DEFAULT 0;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_exhausted int DEFAULT 0;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_cooled int DEFAULT 0;

-- Cadence steps: pre-written messages per stage per campaign
CREATE TABLE IF NOT EXISTS cadence_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id uuid REFERENCES campaigns(id) ON DELETE CASCADE,
    stage text NOT NULL,
    step_order int NOT NULL,
    message_text text NOT NULL,
    created_at timestamptz DEFAULT now(),
    UNIQUE(campaign_id, stage, step_order)
);

-- Cadence state: tracks each lead's progress through the cadence
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

-- Indexes
CREATE INDEX IF NOT EXISTS idx_cadence_steps_campaign ON cadence_steps(campaign_id);
CREATE INDEX IF NOT EXISTS idx_cadence_steps_lookup ON cadence_steps(campaign_id, stage, step_order);
CREATE INDEX IF NOT EXISTS idx_cadence_state_lead ON cadence_state(lead_id);
CREATE INDEX IF NOT EXISTS idx_cadence_state_status ON cadence_state(status);
CREATE INDEX IF NOT EXISTS idx_cadence_state_next_send ON cadence_state(next_send_at);

-- RPC: increment cadence_sent counter
CREATE OR REPLACE FUNCTION increment_cadence_sent(campaign_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE campaigns SET cadence_sent = cadence_sent + 1 WHERE id = campaign_id_param;
END;
$$ LANGUAGE plpgsql;

-- RPC: increment cadence_responded counter
CREATE OR REPLACE FUNCTION increment_cadence_responded(campaign_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE campaigns SET cadence_responded = cadence_responded + 1 WHERE id = campaign_id_param;
END;
$$ LANGUAGE plpgsql;

-- RPC: increment cadence_exhausted counter
CREATE OR REPLACE FUNCTION increment_cadence_exhausted(campaign_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE campaigns SET cadence_exhausted = cadence_exhausted + 1 WHERE id = campaign_id_param;
END;
$$ LANGUAGE plpgsql;

-- RPC: increment cadence_cooled counter
CREATE OR REPLACE FUNCTION increment_cadence_cooled(campaign_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE campaigns SET cadence_cooled = cadence_cooled + 1 WHERE id = campaign_id_param;
END;
$$ LANGUAGE plpgsql;

-- Enable Realtime on new tables
ALTER PUBLICATION supabase_realtime ADD TABLE cadence_steps;
ALTER PUBLICATION supabase_realtime ADD TABLE cadence_state;
