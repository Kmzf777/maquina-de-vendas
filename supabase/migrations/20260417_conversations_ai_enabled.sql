-- Add ai_enabled column to conversations
-- agent_profile_id already exists (added by broadcast worker)
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS ai_enabled BOOLEAN NOT NULL DEFAULT TRUE;

-- Index for filtering active AI conversations
CREATE INDEX IF NOT EXISTS idx_conversations_ai_enabled
  ON conversations (ai_enabled)
  WHERE ai_enabled = FALSE;

COMMENT ON COLUMN conversations.ai_enabled IS
  'When false, AI agent is silenced and human vendor handles replies via CRM';
