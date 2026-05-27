-- 20260527_follow_up_jobs_schema.sql
-- Cria a tabela follow_up_jobs (base do sistema de follow-up de 1h/23h)
-- e a coluna followup_enabled em conversations.
--
-- A migration 20260523_handoff_rescue_job_type.sql usa ADD COLUMN IF NOT EXISTS
-- para job_type/metadata — permanece idempotente com esta tabela já tendo essas colunas.

CREATE TABLE IF NOT EXISTS follow_up_jobs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  lead_id         UUID NOT NULL REFERENCES leads(id),
  channel_id      UUID NOT NULL REFERENCES channels(id),
  sequence        INTEGER NOT NULL,
  fire_at         TIMESTAMPTZ NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sent', 'cancelled')),
  cancel_reason   TEXT,
  sent_at         TIMESTAMPTZ,
  env_tag         TEXT NOT NULL DEFAULT 'production',
  job_type        TEXT NOT NULL DEFAULT 'standard',
  metadata        JSONB NOT NULL DEFAULT '{}',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_followup_jobs_due
  ON follow_up_jobs (status, fire_at)
  WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_followup_jobs_conversation
  ON follow_up_jobs (conversation_id, status);

CREATE INDEX IF NOT EXISTS idx_followup_jobs_type
  ON follow_up_jobs (job_type, status)
  WHERE status = 'pending';

ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS followup_enabled BOOLEAN NOT NULL DEFAULT true;
