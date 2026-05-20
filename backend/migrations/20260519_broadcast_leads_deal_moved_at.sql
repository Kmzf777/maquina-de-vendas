-- Adiciona coluna para rastrear se/quando o deal do lead foi movido no Kanban após disparo
ALTER TABLE broadcast_leads ADD COLUMN IF NOT EXISTS deal_moved_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_broadcast_leads_deal_moved
    ON broadcast_leads(broadcast_id, deal_moved_at)
    WHERE deal_moved_at IS NOT NULL;
