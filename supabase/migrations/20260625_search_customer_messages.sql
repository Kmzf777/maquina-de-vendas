-- Busca de mensagens do cliente em /conversas (estilo WhatsApp).
-- Substring acento-insensível sobre messages.content (role='user'), escopada por canal.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- unaccent não é IMMUTABLE por padrão; wrapper imutável permite indexar a expressão.
-- SET search_path inclui o schema "extensions" porque o Supabase instala a extensão
-- unaccent lá (não em public); sem isso, unaccent('unaccent', $1) não resolve no build
-- do índice ("function unaccent(unknown, text) does not exist").
CREATE OR REPLACE FUNCTION f_unaccent(text)
  RETURNS text
  LANGUAGE sql
  IMMUTABLE PARALLEL SAFE STRICT
  SET search_path = extensions, public, pg_catalog
AS $$ SELECT unaccent('unaccent', $1) $$;

-- Índice GIN trigram PARCIAL: só mensagens do cliente (casa com o filtro da busca).
CREATE INDEX IF NOT EXISTS idx_messages_content_trgm
  ON messages USING gin (f_unaccent(lower(content)) gin_trgm_ops)
  WHERE role = 'user';

-- RPC: uma linha por conversa, com a mensagem do cliente mais recente que casou.
-- channel_ids NULL => admin (sem restrição). Caso contrário, restringe a esses canais.
CREATE OR REPLACE FUNCTION search_customer_messages(
  search_query text,
  channel_ids uuid[],
  max_results int DEFAULT 50
)
RETURNS TABLE (
  conversation_id uuid,
  message_id uuid,
  snippet text,
  match_created_at timestamptz,
  match_count bigint,
  lead_name text,
  lead_phone text,
  channel_id uuid,
  channel_name text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH matches AS (
    SELECT
      m.id            AS message_id,
      m.conversation_id,
      m.content,
      m.created_at,
      ROW_NUMBER() OVER (
        PARTITION BY m.conversation_id ORDER BY m.created_at DESC
      ) AS rn,
      COUNT(*) OVER (PARTITION BY m.conversation_id) AS match_count
    FROM messages m
    JOIN conversations c ON c.id = m.conversation_id
    WHERE m.role = 'user'
      AND m.content IS NOT NULL
      AND f_unaccent(lower(m.content)) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      AND (channel_ids IS NULL OR c.channel_id = ANY (channel_ids))
  )
  SELECT
    mt.conversation_id,
    mt.message_id,
    mt.content                          AS snippet,
    mt.created_at                       AS match_created_at,
    mt.match_count,
    l.name                             AS lead_name,
    l.phone                            AS lead_phone,
    c.channel_id,
    ch.name                            AS channel_name
  FROM matches mt
  JOIN conversations c ON c.id = mt.conversation_id
  LEFT JOIN leads l    ON l.id = c.lead_id
  LEFT JOIN channels ch ON ch.id = c.channel_id
  WHERE mt.rn = 1
  ORDER BY mt.created_at DESC
  LIMIT GREATEST(max_results, 1);
$$;

GRANT EXECUTE ON FUNCTION search_customer_messages(text, uuid[], int) TO authenticated, service_role, anon;
