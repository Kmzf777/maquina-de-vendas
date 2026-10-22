-- supabase/migrations/20261022b_segmento.sql
--
-- Cartão b67f1c6b — spec docs/superpowers/specs/2026-10-22-crm-leads-vendedor-design.md (B9, D9, D11).
--
--   1. leads.segmento  — atacado | private_label | consumo | exportacao | NULL (= ainda não sabe).
--      "secretaria" deixa de ser segmento: vira a fase `triagem` em leads.stage.
--   2. idx_leads_segmento.
--   3. fn_lead_b2b(p_lead) — D9: B2B = segmento atacado/private_label, OU deal em funil
--      Atacado/Private Label, OU contato Bling com CNPJ (14 dígitos), via lead_bling_contacts
--      (account, bling_contact_id) ou via leads.bling_contact_id (conta 'default').
--      Ter score não basta. Lead inexistente → false (nunca NULL).
--
-- NAO E APLICADA PELO DEPLOY. Aplicar à mão ANTES do push, pelo psql do supabase_db.
-- Só aditiva + CREATE OR REPLACE. Reexecutar é seguro.
-- Depois: recarregar o cache do PostgREST com SIGUSR1 (o NOTIFY é ignorado nesta VPS).
-- O CHECK de fase em leads.stage NÃO entra aqui: é a migration 20261022f, depois do F3.

BEGIN;
SET LOCAL lock_timeout = '5s';

-- ── 1. Coluna + CHECK ───────────────────────────────────────────────────────────────
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS segmento text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.leads'::regclass AND conname = 'leads_segmento_check'
  ) THEN
    ALTER TABLE public.leads ADD CONSTRAINT leads_segmento_check
      CHECK (segmento IN ('atacado', 'private_label', 'consumo', 'exportacao'));
  END IF;
END $$;

COMMENT ON COLUMN public.leads.segmento IS
  'Segmento do lead (b67f1c6b): atacado | private_label | consumo | exportacao | NULL = ainda não sabe. Separado da fase (leads.stage).';

-- ── 2. Índice ───────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_leads_segmento ON public.leads (segmento);

-- ── 3. fn_lead_b2b ──────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.fn_lead_b2b(p_lead uuid)
RETURNS boolean
LANGUAGE sql STABLE
SET search_path = public
AS $$
  SELECT
    EXISTS (
      SELECT 1 FROM leads l
       WHERE l.id = p_lead AND l.segmento IN ('atacado', 'private_label')
    )
    OR EXISTS (
      SELECT 1 FROM deals d
        JOIN pipelines p ON p.id = d.pipeline_id
       WHERE d.lead_id = p_lead
         AND p.name ~* '(atacado|private label)'
    )
    OR EXISTS (
      SELECT 1 FROM lead_bling_contacts lbc
        JOIN bling_contacts bc ON bc.account = lbc.account AND bc.id = lbc.bling_contact_id
       WHERE lbc.lead_id = p_lead
         AND length(bc.doc_digits) = 14
    )
    OR EXISTS (
      SELECT 1 FROM leads l
        JOIN bling_contacts bc ON bc.account = 'default' AND bc.id = l.bling_contact_id
       WHERE l.id = p_lead
         AND length(bc.doc_digits) = 14
    );
$$;

COMMENT ON FUNCTION public.fn_lead_b2b(uuid) IS
  'D9 (b67f1c6b): segmento atacado/private_label OU deal em funil Atacado/Private Label OU contato Bling com CNPJ.';

REVOKE ALL ON FUNCTION public.fn_lead_b2b(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.fn_lead_b2b(uuid) TO authenticated, service_role, consulta_ro;

COMMIT;
