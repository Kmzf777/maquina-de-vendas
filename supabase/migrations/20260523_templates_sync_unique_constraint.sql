-- Migration: templates_sync_unique_constraint
-- Replace any (channel_id, name) unique constraint with (channel_id, name, language)
-- to correctly support the same template name in multiple languages.

-- Step A: Drop any existing unique constraint on exactly (channel_id, name)
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.conname
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'message_templates'
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname ORDER BY a.attname)
        FROM pg_attribute a
        WHERE a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
      ) = ARRAY['channel_id', 'name']::name[]
  LOOP
    EXECUTE 'ALTER TABLE message_templates DROP CONSTRAINT ' || quote_ident(r.conname);
    RAISE NOTICE 'Dropped constraint: %', r.conname;
  END LOOP;
END $$;

-- Step B: Add correct unique constraint on (channel_id, name, language) — idempotent
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'message_templates'
      AND c.conname = 'message_templates_channel_name_lang_key'
  ) THEN
    ALTER TABLE message_templates
      ADD CONSTRAINT message_templates_channel_name_lang_key
      UNIQUE (channel_id, name, language);
    RAISE NOTICE 'Created constraint: message_templates_channel_name_lang_key';
  ELSE
    RAISE NOTICE 'Constraint already exists, skipping.';
  END IF;
END $$;
