ALTER TABLE broadcast_leads ADD COLUMN IF NOT EXISTS claimed_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_broadcast_leads_claim
    ON broadcast_leads (broadcast_id, status, claimed_at);
