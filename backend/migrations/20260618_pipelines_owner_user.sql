-- 20260618_pipelines_owner_user.sql
-- Funis por usuário: owner_user_id (NULL = administrativo, igual a channels) + is_universal (Blacklist).
-- Idempotente. Aplicar manualmente no Supabase SQL Editor.
--
-- SEQUÊNCIA DE ROLLOUT:
--   PARTE A (colunas + backfill) — segura, pode aplicar a qualquer momento.
--   Deploy do frontend (cria funis com dono, guardas na API, UI).
--   PARTE B (RLS) — CORTE: passa a escopar leitura/realtime no ato. Aplicar após o deploy do frontend.

-- ============================================================
-- PARTE A — Colunas + índice + backfill
-- ============================================================
ALTER TABLE pipelines
  ADD COLUMN IF NOT EXISTS owner_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE pipelines
  ADD COLUMN IF NOT EXISTS is_universal boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_pipelines_owner_user_id ON pipelines(owner_user_id);

COMMENT ON COLUMN pipelines.owner_user_id IS
  'Dono do funil. NULL = administrativo (visível só a admins, igual a channels.owner_user_id).';
COMMENT ON COLUMN pipelines.is_universal IS
  'Funil de sistema visível e gravável (deals) por todos. Reservado ao Blacklist.';

-- 1. Funis do João → joao@cafecanastra.com (falha alto se o usuário não existir)
DO $$
DECLARE v_joao uuid;
BEGIN
  SELECT id INTO v_joao FROM auth.users WHERE email = 'joao@cafecanastra.com';
  IF v_joao IS NULL THEN
    RAISE EXCEPTION 'Usuário joao@cafecanastra.com não encontrado em auth.users';
  END IF;
  UPDATE pipelines
    SET owner_user_id = v_joao
    WHERE (name ILIKE '%joão%' OR name ILIKE '%joao%')
      AND id <> '8988e852-2836-4add-b023-4db4d6cd0e6e';
END $$;

-- 2. Blacklist → universal (dono permanece NULL)
UPDATE pipelines
  SET is_universal = true, owner_user_id = NULL
  WHERE id = '8988e852-2836-4add-b023-4db4d6cd0e6e';

-- 3. Demais funis já têm owner_user_id = NULL (= administrativo). Nada a fazer.

-- ============================================================
-- PARTE B — RLS (CORTE: aplicar após deploy do frontend)
-- ============================================================
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT COALESCE((auth.jwt() -> 'app_metadata' ->> 'role') = 'admin', false);
$$;

ALTER TABLE pipelines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pipelines_select ON pipelines;
CREATE POLICY pipelines_select ON pipelines FOR SELECT TO authenticated
  USING (public.is_admin() OR owner_user_id = auth.uid() OR is_universal);

ALTER TABLE pipeline_stages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pipeline_stages_select ON pipeline_stages;
CREATE POLICY pipeline_stages_select ON pipeline_stages FOR SELECT TO authenticated
  USING (public.is_admin() OR EXISTS (
    SELECT 1 FROM pipelines p
    WHERE p.id = pipeline_stages.pipeline_id
      AND (p.owner_user_id = auth.uid() OR p.is_universal)
  ));

ALTER TABLE deals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS deals_select ON deals;
CREATE POLICY deals_select ON deals FOR SELECT TO authenticated
  USING (public.is_admin() OR EXISTS (
    SELECT 1 FROM pipelines p
    WHERE p.id = deals.pipeline_id
      AND (p.owner_user_id = auth.uid() OR p.is_universal)
  ));

-- Sem policies de INSERT/UPDATE/DELETE: escrita direta pelo client fica bloqueada;
-- toda escrita passa pela API/backend (service role).
