-- Backfill sent_by for messages created before the column existed.
--
-- Context:
--   When the sent_by column was added (002_crm_enrichment.sql), PostgreSQL
--   backfilled all existing rows with the column DEFAULT ('agent').
--   The frontend send endpoint has always written sent_by='seller' since the
--   column was introduced, so recent outbound seller messages are already correct.
--
--   This migration handles two cases:
--   1. NULL values (should not exist given the DEFAULT, but defensive).
--   2. Historical assistant messages that pre-date the column and therefore
--      carry sent_by='agent' regardless of whether they were from the AI or
--      a seller. We use a timing heuristic: if an assistant message arrived
--      more than 3 minutes after the most recent preceding user message in the
--      same conversation, it is unlikely to be an automated AI response and is
--      reclassified as 'seller'.
--
-- IMPORTANT: Review the SELECT below before running the UPDATE.
-- Run the SELECT first, inspect rows, then uncomment the UPDATE.

-- Step 1: fix NULLs (safe, no ambiguity)
UPDATE messages
SET sent_by = 'user'
WHERE sent_by IS NULL AND role = 'user';

UPDATE messages
SET sent_by = 'agent'
WHERE sent_by IS NULL AND role IN ('assistant', 'system');

-- Step 2: reclassify likely-seller messages among legacy 'agent' rows.
--
-- A message is considered a manual seller message when:
--   - role = 'assistant'          (outbound, not from the customer)
--   - sent_by = 'agent'           (old default — could be AI or seller)
--   - conversation_id IS NOT NULL (belongs to a tracked conversation)
--   - the gap from the last user message in that conversation is > 3 minutes,
--     OR there is no prior user message (seller initiated without AI trigger)
--
-- Inspect first:
/*
SELECT
    m.id,
    m.conversation_id,
    m.content,
    m.created_at,
    prior_user.last_user_at,
    EXTRACT(EPOCH FROM (m.created_at - prior_user.last_user_at)) / 60 AS gap_minutes
FROM messages m
LEFT JOIN LATERAL (
    SELECT MAX(created_at) AS last_user_at
    FROM messages
    WHERE conversation_id = m.conversation_id
      AND role = 'user'
      AND created_at < m.created_at
) prior_user ON true
WHERE m.role = 'assistant'
  AND m.sent_by = 'agent'
  AND m.conversation_id IS NOT NULL
  AND (
        prior_user.last_user_at IS NULL
        OR EXTRACT(EPOCH FROM (m.created_at - prior_user.last_user_at)) > 180
      )
ORDER BY m.created_at DESC
LIMIT 200;
*/

-- Run the UPDATE only after reviewing the SELECT output above:
/*
UPDATE messages m
SET sent_by = 'seller'
FROM (
    SELECT m2.id
    FROM messages m2
    LEFT JOIN LATERAL (
        SELECT MAX(created_at) AS last_user_at
        FROM messages
        WHERE conversation_id = m2.conversation_id
          AND role = 'user'
          AND created_at < m2.created_at
    ) prior_user ON true
    WHERE m2.role = 'assistant'
      AND m2.sent_by = 'agent'
      AND m2.conversation_id IS NOT NULL
      AND (
            prior_user.last_user_at IS NULL
            OR EXTRACT(EPOCH FROM (m2.created_at - prior_user.last_user_at)) > 180
          )
) candidates
WHERE m.id = candidates.id;
*/
