-- scripts/repasse_sla/r1_eventos_repasse.sql — backfill R1 (cartão 7b143561, spec seção 7)
--
-- Um evento lead_events 'repasse' para cada mensagem-marcador que ainda não tem evento:
--   marcador     = role='system' AND content LIKE '[encaminhar\_humano] Lead encaminhado%'
--   occurred_at  = created_at do marcador
--   source       = 'backfill'
--   dedupe_key   = 'repasse:' || message_id   (o mesmo do código novo, leads/repasse.py)
--   metadata     = {vendedor_id: leads.assigned_to atual (texto do uuid),
--                   vendedor/segmento/motivo: de leads.metadata.handoff SÓ se o 'at' do carimbo
--                   estiver a até 5 min do marcador (o carimbo guarda só o último repasse),
--                   conversation_id, message_id}
--   new_value    = vendedor do carimbo quando bate
--
-- Idempotente: só pega marcador sem evento e o insert usa ON CONFLICT no índice único parcial.
-- Teto: 2.100 inserções (esperado em 19/10/2026: 1.807). Acima disso, RAISE EXCEPTION e nada fica.
-- Rodar SÓ com o OK do Rafael:  psql -X -v ON_ERROR_STOP=1 < r1_eventos_repasse.sql
-- Desfazer: r1_rollback.sql

BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
  c_teto CONSTANT int := 2100;
  v_antes int;
  v_ins int;
  v_depois int;
BEGIN
  SELECT count(*) INTO v_antes
    FROM public.messages m
   WHERE m.role = 'system'
     AND m.content LIKE '[encaminhar\_humano] Lead encaminhado%'
     AND m.lead_id IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM public.lead_events e WHERE e.dedupe_key = 'repasse:' || m.id);
  RAISE NOTICE 'R1 marcadores sem evento: %', v_antes;

  WITH alvo AS (
    SELECT m.id, m.lead_id, m.conversation_id, m.created_at,
           l.assigned_to,
           l.metadata->'handoff' AS h,
           -- só ISO com offset (os dois caminhos gravam assim); qualquer outra coisa = não bate
           CASE WHEN l.metadata->'handoff'->>'at'
                     ~ '^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}(:?\d{2})?|Z)$'
                THEN (l.metadata->'handoff'->>'at')::timestamptz END AS h_at
      FROM public.messages m
      JOIN public.leads l ON l.id = m.lead_id
     WHERE m.role = 'system'
       AND m.content LIKE '[encaminhar\_humano] Lead encaminhado%'
       AND NOT EXISTS (SELECT 1 FROM public.lead_events e WHERE e.dedupe_key = 'repasse:' || m.id)
  ), a AS (
    SELECT alvo.*,
           (h_at IS NOT NULL AND abs(extract(epoch FROM (h_at - created_at))) <= 300) AS bate
      FROM alvo
  )
  INSERT INTO public.lead_events (lead_id, event_type, new_value, occurred_at, source, dedupe_key, metadata)
  SELECT a.lead_id, 'repasse',
         CASE WHEN a.bate THEN a.h->>'vendedor' END,
         a.created_at, 'backfill', 'repasse:' || a.id,
         jsonb_build_object(
           'vendedor_id',     a.assigned_to::text,
           'vendedor',        CASE WHEN a.bate THEN a.h->>'vendedor' END,
           'segmento',        CASE WHEN a.bate THEN a.h->>'segmento' END,
           'motivo',          CASE WHEN a.bate THEN a.h->>'motivo' END,
           'conversation_id', a.conversation_id::text,
           'message_id',      a.id::text)
    FROM a
  ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING;
  GET DIAGNOSTICS v_ins = ROW_COUNT;

  IF v_ins > c_teto THEN
    RAISE EXCEPTION 'R1 abortado: % inserções passam do teto de %', v_ins, c_teto;
  END IF;

  SELECT count(*) INTO v_depois
    FROM public.messages m
   WHERE m.role = 'system'
     AND m.content LIKE '[encaminhar\_humano] Lead encaminhado%'
     AND m.lead_id IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM public.lead_events e WHERE e.dedupe_key = 'repasse:' || m.id);
  RAISE NOTICE 'R1 inseridos: % | marcadores sem evento depois: %', v_ins, v_depois;
END $$;

COMMIT;
