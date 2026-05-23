-- 20260523_handoff_rescue_job_type.sql
-- Adiciona job_type e metadata à follow_up_jobs para suportar jobs de resgate de handoff.
-- job_type='standard' é o default; registros existentes não são afetados.
ALTER TABLE follow_up_jobs
  ADD COLUMN IF NOT EXISTS job_type TEXT NOT NULL DEFAULT 'standard',
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_followup_jobs_type
  ON follow_up_jobs (job_type, status)
  WHERE status = 'pending';
