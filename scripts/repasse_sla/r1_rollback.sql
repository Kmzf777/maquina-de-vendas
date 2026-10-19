-- scripts/repasse_sla/r1_rollback.sql — desfaz o backfill R1 (cartão 7b143561)
-- Apaga só os eventos 'repasse' do backfill. Os gravados pelo código (source 'ia'/'button_flow')
-- ficam. Idempotente. Teto: 2.100 (o mesmo do R1).

BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
  c_teto CONSTANT int := 2100;
  v_antes int;
  v_del int;
BEGIN
  SELECT count(*) INTO v_antes FROM public.lead_events WHERE event_type = 'repasse' AND source = 'backfill';
  RAISE NOTICE 'R1 rollback: eventos de backfill antes: %', v_antes;

  DELETE FROM public.lead_events WHERE event_type = 'repasse' AND source = 'backfill';
  GET DIAGNOSTICS v_del = ROW_COUNT;

  IF v_del > c_teto THEN
    RAISE EXCEPTION 'R1 rollback abortado: % remoções passam do teto de %', v_del, c_teto;
  END IF;
  RAISE NOTICE 'R1 rollback: removidos: %', v_del;
END $$;

COMMIT;
