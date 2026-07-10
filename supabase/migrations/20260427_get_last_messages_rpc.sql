CREATE OR REPLACE FUNCTION get_last_messages(conv_ids uuid[])
RETURNS TABLE(conversation_id uuid, content text, role text)
LANGUAGE sql STABLE AS $$
  SELECT DISTINCT ON (conversation_id) conversation_id, content, role
  FROM messages
  WHERE conversation_id = ANY(conv_ids)
  ORDER BY conversation_id, created_at DESC;
$$;
