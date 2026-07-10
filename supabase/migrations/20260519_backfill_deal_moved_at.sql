-- Backfill deal_moved_at for broadcast_leads where the deal is ALREADY in the
-- target stage. This happens for broadcasts sent BEFORE the deal_moved_at
-- column was added — the move occurred but the timestamp was never recorded.
--
-- Safe to run multiple times (deal_moved_at IS NULL guard).
-- Uses CURRENT_TIMESTAMP as approximation (actual move date unknown).

UPDATE broadcast_leads bl
SET deal_moved_at = CURRENT_TIMESTAMP
WHERE bl.deal_moved_at IS NULL
  AND bl.status IN ('sent', 'delivered')
  AND EXISTS (
    SELECT 1
    FROM broadcasts b
    JOIN pipeline_stages ps ON ps.id = b.move_to_stage_id
    WHERE b.id = bl.broadcast_id
      AND b.move_to_stage_id IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM deals d
        WHERE d.lead_id = bl.lead_id
          AND d.pipeline_id = ps.pipeline_id
          AND d.stage_id = b.move_to_stage_id
      )
  );
