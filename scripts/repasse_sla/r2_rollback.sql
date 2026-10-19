-- scripts/repasse_sla/r2_rollback.sql — desfaz o backfill R2 (cartão 7b143561)
-- Volta leads.first_response_at ao valor anterior gravado em backup_r2_first_response_20261019,
-- só onde o valor atual ainda é o que o R2 gravou (se mudou depois, fica e é contado).
-- Depois apaga a tabela de backup. Idempotente: sem a tabela, não faz nada.
-- Teto: 1.900 (o mesmo do R2).
-- Obs.: o trigger trg_leads_first_response continua ativo; quem quiser também desfazê-lo usa
-- rollback_migration.sql (que não apaga valores).

BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
  c_teto CONSTANT int := 1900;
  v_backup int;
  v_upd int;
BEGIN
  IF to_regclass('public.backup_r2_first_response_20261019') IS NULL THEN
    RAISE NOTICE 'R2 rollback: sem backup_r2_first_response_20261019, nada a desfazer';
    RETURN;
  END IF;

  EXECUTE 'SELECT count(*) FROM public.backup_r2_first_response_20261019' INTO v_backup;
  RAISE NOTICE 'R2 rollback: linhas no backup: %', v_backup;

  EXECUTE $q$
    UPDATE public.leads l
       SET first_response_at = b.first_response_at_anterior
      FROM public.backup_r2_first_response_20261019 b
     WHERE l.id = b.lead_id
       AND l.first_response_at IS NOT DISTINCT FROM b.first_response_at_gravado
  $q$;
  GET DIAGNOSTICS v_upd = ROW_COUNT;

  IF v_upd > c_teto THEN
    RAISE EXCEPTION 'R2 rollback abortado: % leads passam do teto de %', v_upd, c_teto;
  END IF;

  EXECUTE 'DROP TABLE public.backup_r2_first_response_20261019';
  RAISE NOTICE 'R2 rollback: restaurados: % | mantidos (valor mudou depois do R2): %', v_upd, v_backup - v_upd;
END $$;

COMMIT;
