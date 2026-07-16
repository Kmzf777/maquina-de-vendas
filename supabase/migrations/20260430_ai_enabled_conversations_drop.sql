-- Remove conversations.ai_enabled after all code has been migrated to use leads.ai_enabled.

ALTER TABLE conversations DROP COLUMN IF EXISTS ai_enabled;
