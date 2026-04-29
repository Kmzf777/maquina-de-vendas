-- Backfill: set ai_enabled=FALSE for conversations that already had
-- encaminhar_humano triggered before the backend fix (2026-04-29).
-- Safe to re-run: only affects rows still incorrectly set to TRUE.
UPDATE conversations c
SET ai_enabled = FALSE
WHERE c.ai_enabled = TRUE
  AND EXISTS (
    SELECT 1 FROM messages m
    WHERE m.conversation_id = c.id
      AND m.role = 'system'
      AND m.content LIKE '[encaminhar_humano]%'
  );
