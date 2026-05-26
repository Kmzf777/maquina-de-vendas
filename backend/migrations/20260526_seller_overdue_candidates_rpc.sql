-- Candidatos a "em atraso" para SLA do vendedor, computados a partir da tabela
-- messages (fonte da verdade por conversa), não do campo denormalizado
-- leads.last_customer_message_at (que era incompleto e gerava sub/super-contagem).
--
-- Uma conversa é candidata se a última mensagem do CLIENTE (sent_by='user')
-- não foi respondida pelo vendedor — considerando tanto mensagens do vendedor
-- (sent_by='seller') quanto last_seller_response_at (botão Finalizar Conversa,
-- que não insere mensagem).
--
-- Retorna last_user_at para o frontend aplicar o filtro de horário comercial
-- (10h-16h Seg-Sex SP, > 20 min) — regra que não cabe bem em SQL puro.
CREATE OR REPLACE FUNCTION get_seller_overdue_candidates(p_channel_id uuid)
RETURNS TABLE(conversation_id uuid, last_user_at timestamptz)
LANGUAGE sql STABLE AS $$
  WITH convs AS (
    SELECT c.id, c.last_seller_response_at
    FROM conversations c
    WHERE c.channel_id = p_channel_id
  ),
  agg AS (
    SELECT
      m.conversation_id,
      MAX(m.created_at) FILTER (WHERE m.sent_by = 'user')   AS last_user_at,
      MAX(m.created_at) FILTER (WHERE m.sent_by = 'seller')  AS last_seller_at
    FROM messages m
    WHERE m.conversation_id IN (SELECT id FROM convs)
    GROUP BY m.conversation_id
  )
  SELECT a.conversation_id, a.last_user_at
  FROM agg a
  JOIN convs c ON c.id = a.conversation_id
  WHERE a.last_user_at IS NOT NULL
    AND GREATEST(
          COALESCE(a.last_seller_at, '-infinity'::timestamptz),
          COALESCE(c.last_seller_response_at, '-infinity'::timestamptz)
        ) < a.last_user_at;
$$;
