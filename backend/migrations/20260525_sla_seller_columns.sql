-- Adicionar colunas SLA ao conversations
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS first_seller_response_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS last_seller_response_at  TIMESTAMPTZ;

-- Trigger: atualiza colunas ao inserir mensagem do vendedor
CREATE OR REPLACE FUNCTION update_conversation_seller_response()
RETURNS trigger AS $$
BEGIN
  IF NEW.sent_by = 'seller' AND NEW.conversation_id IS NOT NULL THEN
    UPDATE conversations
    SET
      last_seller_response_at  = NEW.created_at,
      first_seller_response_at = COALESCE(first_seller_response_at, NEW.created_at)
    WHERE id = NEW.conversation_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_conversation_seller_response ON messages;
CREATE TRIGGER trg_conversation_seller_response
  AFTER INSERT ON messages
  FOR EACH ROW EXECUTE FUNCTION update_conversation_seller_response();

-- Backfill a partir de mensagens existentes
UPDATE conversations c
SET
  first_seller_response_at = sub.first_at,
  last_seller_response_at  = sub.last_at
FROM (
  SELECT
    conversation_id,
    MIN(created_at) AS first_at,
    MAX(created_at) AS last_at
  FROM messages
  WHERE sent_by = 'seller' AND conversation_id IS NOT NULL
  GROUP BY conversation_id
) sub
WHERE c.id = sub.conversation_id;

-- Índice para queries por canal
CREATE INDEX IF NOT EXISTS idx_conversations_channel_id
  ON conversations(channel_id);
