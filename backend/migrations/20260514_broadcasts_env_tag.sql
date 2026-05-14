ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS env_tag text DEFAULT 'production';

UPDATE broadcasts SET env_tag = 'production' WHERE env_tag IS NULL;
