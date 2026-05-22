-- supabase/migrations/20260522_cadence_unify_drop_legacy.sql
-- Unifica o sistema de cadência: drop do legado, garante colunas no novo.

-- 1. Idempotência: channel_id em campaigns
ALTER TABLE campaigns
  ADD COLUMN IF NOT EXISTS channel_id UUID REFERENCES channels(id) ON DELETE SET NULL;

-- 2. Estado do round-robin
ALTER TABLE campaigns
  ADD COLUMN IF NOT EXISTS last_assigned_index INT NOT NULL DEFAULT -1;

-- 3. Drop tabelas legadas (já esvaziadas pela migration 20260521_migrate_cadence_enrollments.sql)
DROP TABLE IF EXISTS cadence_enrollments CASCADE;
DROP TABLE IF EXISTS cadence_steps CASCADE;
DROP TABLE IF EXISTS cadences CASCADE;
