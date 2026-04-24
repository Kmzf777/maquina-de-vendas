-- backend/migrations/20260424_last_customer_message_at.sql
ALTER TABLE leads
ADD COLUMN IF NOT EXISTS last_customer_message_at timestamptz DEFAULT NULL;
