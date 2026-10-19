-- scripts/repasse_sla/r3_rollback.sql — desfaz o backfill R3 (cartão 7b143561)
-- Volta stage_id e entered_stage_at dos deals ao que está em backup_r3_deals_20261019, só onde o
-- deal ainda está na etapa que o R3 pôs (se o deal andou depois, fica e é contado).
-- Dois UPDATEs pelo mesmo motivo do R3 (trg_update_deal_entered_stage_at). O gatilho de
-- lead_events registra mais um evento 'etapa' por deal; os eventos 'etapa' do R3 ficam.
-- Depois apaga a tabela de backup. Idempotente: sem a tabela, não faz nada.
-- Teto: 30 (o esperado do R3).

BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
  c_teto CONSTANT int := GREATEST(30, COALESCE(NULLIF(current_setting('repasse.r3_esperado', true), '')::int, 30));
  v_backup int;
  v_upd int;
BEGIN
  IF to_regclass('public.backup_r3_deals_20261019') IS NULL THEN
    RAISE NOTICE 'R3 rollback: sem backup_r3_deals_20261019, nada a desfazer';
    RETURN;
  END IF;

  EXECUTE 'SELECT count(*) FROM public.backup_r3_deals_20261019' INTO v_backup;
  RAISE NOTICE 'R3 rollback: linhas no backup: %', v_backup;

  EXECUTE $q$
    CREATE TEMP TABLE r3_volta ON COMMIT DROP AS
    SELECT b.* FROM public.backup_r3_deals_20261019 b
      JOIN public.deals d ON d.id = b.deal_id
     WHERE d.stage_id = b.stage_id_novo
       FOR UPDATE OF d
  $q$;

  UPDATE public.deals d SET stage_id = v.stage_id_anterior, updated_at = now()
    FROM r3_volta v WHERE d.id = v.deal_id;
  GET DIAGNOSTICS v_upd = ROW_COUNT;

  UPDATE public.deals d SET entered_stage_at = v.entered_stage_at_anterior
    FROM r3_volta v WHERE d.id = v.deal_id;

  IF v_upd > c_teto THEN
    RAISE EXCEPTION 'R3 rollback abortado: % deals passam do teto de %', v_upd, c_teto;
  END IF;

  EXECUTE 'DROP TABLE public.backup_r3_deals_20261019';
  RAISE NOTICE 'R3 rollback: restaurados: % | mantidos (deal mudou de etapa depois do R3): %', v_upd, v_backup - v_upd;
END $$;

COMMIT;
