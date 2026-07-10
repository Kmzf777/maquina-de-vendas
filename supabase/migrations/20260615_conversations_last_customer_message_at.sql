-- backend/migrations/20260615_conversations_last_customer_message_at.sql
--
-- Janela de atendimento de 24h POR CANAL.
--
-- Antes, a janela era rastreada por um único campo global `leads.last_customer_message_at`,
-- então um lead com inbound recente no canal A aparecia com a janela aberta no canal B também.
-- A entidade correta por (lead + canal) é `conversations`. Esta coluna passa a ser a fonte
-- da verdade da janela: é carimbada (em app/conversations/service.py:save_message) sempre que
-- o CLIENTE (role='user') envia uma mensagem nesta conversa.
--
-- Backfill: popula a partir da última mensagem do cliente já existente em cada conversa,
-- para que conversas atuais não fiquem com a janela "fechada" logo após o deploy.

ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS last_customer_message_at timestamptz DEFAULT NULL;

UPDATE conversations c
SET last_customer_message_at = sub.max_at
FROM (
  SELECT conversation_id, MAX(created_at) AS max_at
  FROM messages
  WHERE role = 'user'
  GROUP BY conversation_id
) sub
WHERE sub.conversation_id = c.id
  AND c.last_customer_message_at IS NULL;
