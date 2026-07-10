-- Rastreia quando o lead respondeu ao disparo pela primeira vez (dentro da janela de 48h)
ALTER TABLE broadcast_leads
  ADD COLUMN IF NOT EXISTS first_replied_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_broadcast_leads_replied
  ON broadcast_leads(broadcast_id, first_replied_at)
  WHERE first_replied_at IS NOT NULL;
