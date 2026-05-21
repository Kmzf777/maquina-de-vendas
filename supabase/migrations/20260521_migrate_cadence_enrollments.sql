-- supabase/migrations/20260521_migrate_cadence_enrollments.sql
-- Migrate active cadence enrollments to completed status
-- Run in Supabase SQL Editor ONCE before removing the cadence UI

UPDATE cadence_enrollments
SET
  status = 'completed',
  completed_at = NOW()
WHERE status IN ('active', 'responded');
