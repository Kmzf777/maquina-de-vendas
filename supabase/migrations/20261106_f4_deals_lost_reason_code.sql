-- supabase/migrations/20261106_f4_deals_lost_reason_code.sql
--
-- Frente F4 (consolidado tráfego × CRM, 06/11/2026): motivo de perda estruturado.
--
--   deals.lost_reason_code  — vocabulário FECHADO (CHECK abaixo). É o que os relatórios contam.
--   deals.lost_competitor   — texto: de quem o lead comprou quando o código é 'comprou_outro'.
--   deals.lost_reason       — continua livre: vira a OBSERVAÇÃO do motivo.
--
-- O vocabulário é o mesmo de backend/app/leads/motivo_perda.py e de
-- frontend/src/lib/lost-reason.ts (os testes dos dois lados conferem esta lista).
--
-- NÃO É APLICADA PELO DEPLOY. Aplicar à mão ANTES do push, pelo psql do supabase_db.
-- Só aditiva; reexecutar é seguro. Depois: recarregar o cache do PostgREST com SIGUSR1.
-- Desfazer:
--   ALTER TABLE public.deals DROP CONSTRAINT IF EXISTS deals_lost_reason_code_check;
--   DROP INDEX IF EXISTS public.idx_deals_lost_reason_code;
--   ALTER TABLE public.deals DROP COLUMN IF EXISTS lost_competitor;
--   ALTER TABLE public.deals DROP COLUMN IF EXISTS lost_reason_code;

BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.deals ADD COLUMN IF NOT EXISTS lost_reason_code text;
ALTER TABLE public.deals ADD COLUMN IF NOT EXISTS lost_competitor text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.deals'::regclass AND conname = 'deals_lost_reason_code_check'
  ) THEN
    ALTER TABLE public.deals ADD CONSTRAINT deals_lost_reason_code_check
      CHECK (lost_reason_code IS NULL OR lost_reason_code IN (
        'preco_margem', 'frete', 'pedido_minimo', 'condicao_bonificacao', 'comprou_outro',
        'ainda_pesquisando', 'consumidor_final', 'sem_resposta', 'outro'
      ));
  END IF;
END $$;

-- Contagem por motivo (relatório do /trafego e da pesquisa de perda).
CREATE INDEX IF NOT EXISTS idx_deals_lost_reason_code
  ON public.deals (lost_reason_code) WHERE lost_reason_code IS NOT NULL;

COMMENT ON COLUMN public.deals.lost_reason_code IS
  'F4: motivo da perda, vocabulário fechado (preco_margem | frete | pedido_minimo | '
  'condicao_bonificacao | comprou_outro | ainda_pesquisando | consumidor_final | sem_resposta | outro). '
  'NULL = perda antiga, de antes da F4.';
COMMENT ON COLUMN public.deals.lost_competitor IS
  'F4: de quem o lead comprou (texto), preenchido quando lost_reason_code = comprou_outro.';
COMMENT ON COLUMN public.deals.lost_reason IS
  'Observação livre sobre a perda. O motivo que conta nos relatórios é lost_reason_code.';

COMMIT;
