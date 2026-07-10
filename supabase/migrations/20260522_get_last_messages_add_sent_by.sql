-- Adds sent_by to get_last_messages so the sidebar can distinguish "IA:" from "Vendedor:"
CREATE OR REPLACE FUNCTION get_last_messages(conv_ids uuid[])
RETURNS TABLE(conversation_id uuid, content text, role text, sent_by text)
LANGUAGE sql STABLE AS $$
  SELECT DISTINCT ON (conversation_id) conversation_id, content, role, sent_by
  FROM messages
  WHERE conversation_id = ANY(conv_ids)
  ORDER BY conversation_id, created_at DESC;
$$;
