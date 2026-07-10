-- 20260429_conversations_unread_count.sql
-- Adiciona contador de mensagens não-lidas por conversa.
-- Incrementado a cada mensagem inbound (sent_by='user') e zerado via endpoint mark-read.

ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS unread_count INTEGER NOT NULL DEFAULT 0;

-- Backfill defensivo (DEFAULT já cobre, mas garante)
UPDATE conversations SET unread_count = 0 WHERE unread_count IS NULL;

-- Index opcional para sort/filter por não-lidas
CREATE INDEX IF NOT EXISTS idx_conversations_unread_count
  ON conversations (unread_count) WHERE unread_count > 0;
