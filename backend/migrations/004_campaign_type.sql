-- 004_campaign_type.sql
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN type text DEFAULT 'broadcast';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
