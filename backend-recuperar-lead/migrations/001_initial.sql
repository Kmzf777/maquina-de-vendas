-- 001_initial.sql
-- Run this in Supabase SQL Editor

-- Campaigns table (must exist before leads due to FK)
CREATE TABLE IF NOT EXISTS campaigns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    template_name text NOT NULL,
    template_params jsonb,
    total_leads int DEFAULT 0,
    sent int DEFAULT 0,
    failed int DEFAULT 0,
    replied int DEFAULT 0,
    status text DEFAULT 'draft',
    send_interval_min int DEFAULT 3,
    send_interval_max int DEFAULT 8,
    created_at timestamptz DEFAULT now()
);

-- Leads table
CREATE TABLE IF NOT EXISTS leads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    phone text UNIQUE NOT NULL,
    name text,
    company text,
    stage text DEFAULT 'pending',
    status text DEFAULT 'imported',
    campaign_id uuid REFERENCES campaigns(id),
    last_msg_at timestamptz,
    created_at timestamptz DEFAULT now()
);

-- Messages table (unified history)
CREATE TABLE IF NOT EXISTS messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    role text NOT NULL,
    content text NOT NULL,
    stage text,
    created_at timestamptz DEFAULT now()
);

-- Templates table (mirror of Meta approved templates)
CREATE TABLE IF NOT EXISTS templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    meta_id text,
    name text NOT NULL,
    language text DEFAULT 'pt_BR',
    category text,
    body_text text,
    status text,
    synced_at timestamptz
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_campaign ON leads(campaign_id);
CREATE INDEX IF NOT EXISTS idx_messages_lead_id ON messages(lead_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

-- RPC for atomic counter increment (used by worker)
CREATE OR REPLACE FUNCTION increment_campaign_sent(campaign_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE campaigns SET sent = sent + 1 WHERE id = campaign_id_param;
END;
$$ LANGUAGE plpgsql;

-- RPC for incrementing replied counter
CREATE OR REPLACE FUNCTION increment_campaign_replied(campaign_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE campaigns SET replied = replied + 1 WHERE id = campaign_id_param;
END;
$$ LANGUAGE plpgsql;
