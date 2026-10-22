-- supabase/migrations/20261022f_stage_fase_check.sql
--
-- Cartão b67f1c6b — spec docs/superpowers/specs/2026-10-22-crm-leads-vendedor-design.md (B9).
--
-- CHECK de fase em leads.stage: pending | novo | triagem | qualificando | perdido.
-- O segmento mora em leads.segmento (migration 20261022b).
--
-- SÓ DEPOIS do backfill F3 (scripts/leads_vendedor/f3_*.sql). Se ainda houver stage fora das
-- fases, a pré-checagem levanta 'rodar F3 antes' e nada é alterado.
-- NAO E APLICADA PELO DEPLOY. Aplicar à mão. Reexecutar é seguro.
-- Desfazer: ALTER TABLE public.leads DROP CONSTRAINT IF EXISTS leads_stage_fase_check;

BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
  v_fora text;
BEGIN
  SELECT string_agg(DISTINCT coalesce(stage, 'NULL'), ', ')
    INTO v_fora
    FROM public.leads
   WHERE stage IS NULL
      OR stage NOT IN ('pending', 'novo', 'triagem', 'qualificando', 'perdido');
  IF v_fora IS NOT NULL THEN
    RAISE EXCEPTION 'leads.stage fora das fases (%): rodar F3 antes', v_fora;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.leads'::regclass AND conname = 'leads_stage_fase_check'
  ) THEN
    ALTER TABLE public.leads ADD CONSTRAINT leads_stage_fase_check
      CHECK (stage IN ('pending', 'novo', 'triagem', 'qualificando', 'perdido')) NOT VALID;
  END IF;
END $$;

ALTER TABLE public.leads VALIDATE CONSTRAINT leads_stage_fase_check;

ALTER TABLE public.leads ALTER COLUMN stage SET DEFAULT 'pending';

COMMIT;
