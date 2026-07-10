-- Adiciona colunas de outbound tracking na meta_webhook_logs
-- Necessárias para os endpoints de stats (/api/stats/whatsapp*)
-- Aplicado ao homolog em 2026-06-10 (homolog estava atrás do schema de produção)

ALTER TABLE meta_webhook_logs
  ADD COLUMN IF NOT EXISTS direction    text    DEFAULT 'inbound',
  ADD COLUMN IF NOT EXISTS request_type text,
  ADD COLUMN IF NOT EXISTS success      boolean DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_meta_webhook_logs_stats
  ON meta_webhook_logs (direction, request_type, success, received_at);
