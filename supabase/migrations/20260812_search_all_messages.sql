-- Busca de mensagens em /conversas: passa a cobrir TUDO, não só o cliente.
--   Antes: só role='user' (mensagens do cliente) e só a coluna content.
--   Agora: role IN ('user','assistant') (cliente + vendedor + IA) e também
--          document_name — assim um PDF enviado ("Viva Mais Chapecó") é achado
--          pelo nome do arquivo, mesmo quando content está vazio.
-- system fica de fora de propósito: são resumos internos de handoff, não conversa.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- f_unaccent: wrapper imutável (unaccent não é IMMUTABLE por padrão). Ver
-- 20260625_search_customer_messages.sql para o porquê do search_path.
CREATE OR REPLACE FUNCTION f_unaccent(text)
  RETURNS text
  LANGUAGE sql
  IMMUTABLE PARALLEL SAFE STRICT
  SET search_path = extensions, public, pg_catalog
AS $$ SELECT unaccent('unaccent', $1) $$;

-- Índice trigram de content: antes era PARCIAL só p/ role='user'. Reescreve p/
-- cobrir também as mensagens que enviamos (role='assistant').
DROP INDEX IF EXISTS idx_messages_content_trgm;
CREATE INDEX IF NOT EXISTS idx_messages_content_trgm
  ON messages USING gin (f_unaccent(lower(content)) gin_trgm_ops)
  WHERE role IN ('user', 'assistant') AND content IS NOT NULL;

-- Novo índice p/ buscar pelo nome do arquivo (documentos/PDFs).
CREATE INDEX IF NOT EXISTS idx_messages_docname_trgm
  ON messages USING gin (f_unaccent(lower(document_name)) gin_trgm_ops)
  WHERE document_name IS NOT NULL;

-- A assinatura de retorno muda (novo sent_by), então DROP + CREATE (CREATE OR
-- REPLACE não altera RETURNS TABLE). Mantém o mesmo NOME p/ não mexer na API/route.
DROP FUNCTION IF EXISTS search_customer_messages(text, uuid[], int);

-- RPC: uma linha por conversa, com a mensagem mais recente que casou.
-- Casa em content OU document_name. sent_by permite a UI marcar "Você:".
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
  channel_name text,
  sent_by text
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
      -- Snippet: content quando há texto/legenda; senão o nome do arquivo (PDF).
      COALESCE(NULLIF(btrim(m.content), ''), m.document_name) AS snippet,
      m.created_at,
      m.sent_by,
      ROW_NUMBER() OVER (
        PARTITION BY m.conversation_id ORDER BY m.created_at DESC
      ) AS rn,
      COUNT(*) OVER (PARTITION BY m.conversation_id) AS match_count
    FROM messages m
    JOIN conversations c ON c.id = m.conversation_id
    WHERE m.role IN ('user', 'assistant')
      AND (
        (m.content IS NOT NULL
          AND f_unaccent(lower(m.content)) LIKE '%' || f_unaccent(lower(search_query)) || '%')
        OR (m.document_name IS NOT NULL
          AND f_unaccent(lower(m.document_name)) LIKE '%' || f_unaccent(lower(search_query)) || '%')
      )
      AND (channel_ids IS NULL OR c.channel_id = ANY (channel_ids))
  )
  SELECT
    mt.conversation_id,
    mt.message_id,
    mt.snippet,
    mt.created_at                       AS match_created_at,
    mt.match_count,
    l.name                             AS lead_name,
    l.phone                            AS lead_phone,
    c.channel_id,
    ch.name                            AS channel_name,
    mt.sent_by
  FROM matches mt
  JOIN conversations c ON c.id = mt.conversation_id
  LEFT JOIN leads l    ON l.id = c.lead_id
  LEFT JOIN channels ch ON ch.id = c.channel_id
  WHERE mt.rn = 1
  ORDER BY mt.created_at DESC
  LIMIT GREATEST(max_results, 1);
$$;

-- anon permanece SEM acesso (revogado em 20260704_revoke_search_customer_messages_public.sql).
GRANT EXECUTE ON FUNCTION search_customer_messages(text, uuid[], int) TO authenticated, service_role;
