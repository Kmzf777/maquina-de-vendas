-- Add campaign type and instance fields
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS type text NOT NULL DEFAULT 'bot';
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS instance_name text;
