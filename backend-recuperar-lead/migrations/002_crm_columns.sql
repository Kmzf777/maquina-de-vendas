-- 002_crm_columns.sql
-- Run this in Supabase SQL Editor after 001_initial.sql

-- CRM columns on leads
ALTER TABLE leads ADD COLUMN IF NOT EXISTS seller_stage text DEFAULT 'novo';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS assigned_to uuid;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS human_control boolean DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS channel text DEFAULT 'evolution';

-- Indexes for CRM queries
CREATE INDEX IF NOT EXISTS idx_leads_seller_stage ON leads(seller_stage);
CREATE INDEX IF NOT EXISTS idx_leads_human_control ON leads(human_control);

-- Sender tracking on messages
ALTER TABLE messages ADD COLUMN IF NOT EXISTS sent_by text DEFAULT 'agent';

-- Enable Realtime on tables the CRM subscribes to
ALTER PUBLICATION supabase_realtime ADD TABLE leads;
ALTER PUBLICATION supabase_realtime ADD TABLE messages;
ALTER PUBLICATION supabase_realtime ADD TABLE campaigns;
