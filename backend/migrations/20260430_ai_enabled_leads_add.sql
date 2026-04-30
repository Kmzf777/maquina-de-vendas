-- Adds ai_enabled as single source of truth for AI control per lead.
-- Backfill: leads with human_control=true are marked ai_enabled=false.

ALTER TABLE leads ADD COLUMN IF NOT EXISTS ai_enabled BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE leads SET ai_enabled = FALSE WHERE human_control = TRUE;
