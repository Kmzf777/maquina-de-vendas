-- supabase/migrations/20260528_quoted_messages.sql

-- Column to store the wamid of the message being replied to
ALTER TABLE messages ADD COLUMN IF NOT EXISTS quoted_wamid TEXT NULL;

-- Index on wamid for fast lookup when resolving quoted messages
-- (wamid already exists as a column from previous migrations)
CREATE INDEX IF NOT EXISTS idx_messages_wamid
  ON messages (wamid)
  WHERE wamid IS NOT NULL;
