-- Logs de todos os webhooks recebidos da Meta API
-- Usado para auditoria e debugging de mensagens perdidas

CREATE TABLE IF NOT EXISTS meta_webhook_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    channel_id UUID REFERENCES channels(id) ON DELETE SET NULL,
    phone_number_id TEXT,
    from_number TEXT,
    payload JSONB NOT NULL,
    message_count INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_meta_webhook_logs_channel_received
    ON meta_webhook_logs(channel_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_meta_webhook_logs_from_number
    ON meta_webhook_logs(from_number, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_meta_webhook_logs_received_at
    ON meta_webhook_logs(received_at DESC);
