-- backend/migrations/20260430_messages_media_columns.sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_type TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_url TEXT;
