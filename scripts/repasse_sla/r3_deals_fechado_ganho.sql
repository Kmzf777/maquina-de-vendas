-- scripts/repasse_sla/r3_deals_fechado_ganho.sql — backfill R3 (cartão 7b143561, spec seção 7, B7)
--
-- Devolve a Fechado Ganho os deals que o disparo de 29/07/2026 tirou de lá:
--   alvo = deals em etapa key 'chamado_reposicao', com closed_at não nulo, cujo lead tem
--          broadcast_leads.deal_moved_at > deals.closed_at
--   novo stage_id        = a etapa key 'fechado_ganho' do mesmo pipeline_id do deal
--   novo entered_stage_at = closed_at
-- Guarda (deal_id, stage_id anterior, entered_stage_at anterior) em backup_r3_deals_20261019.
--
-- Contagem EXATA: aborta se o alvo tiver número diferente do esperado (30, medido em 15 e
-- 19/10/2026). O esperado só muda com novo OK do Rafael, via
--   SET repasse.r3_esperado = 'N';   (na mesma sessão, antes do script; padrão 30)
-- Aborta também se algum pipeline do alvo não tiver exatamente 1 etapa 'fechado_ganho'.
-- Alvo vazio (já aplicado) = nada a fazer, sem erro: idempotente.
--
-- Dois UPDATEs: o gatilho BEFORE UPDATE trg_update_deal_entered_stage_at põe now() em
-- entered_stage_at quando stage_id muda; o 2º UPDATE (sem mudar stage_id) grava closed_at.
-- O gatilho trg_lead_events_deals_etapa registra um evento 'etapa' por deal (esperado).
--
-- Rodar SÓ com o OK do Rafael:  psql -X -v ON_ERROR_STOP=1 < r3_deals_fechado_ganho.sql
-- Desfazer: r3_rollback.sql

BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.backup_r3_deals_20261019 (
  deal_id                   uuid PRIMARY KEY,
  stage_id_anterior         uuid,
  entered_stage_at_anterior timestamptz,
  stage_id_novo             uuid NOT NULL,
  gravado_em                timestamptz NOT NULL DEFAULT now()
);
-- tabela em public: fora da API (Supabase dá grants padrão a anon/authenticated)
ALTER TABLE public.backup_r3_deals_20261019 ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.backup_r3_deals_20261019 FROM PUBLIC, anon, authenticated;

-- Alvo travado (FOR UPDATE) e congelado: os dois UPDATEs e o backup usam a mesma lista.
CREATE TEMP TABLE r3_alvo ON COMMIT DROP AS
SELECT d.id AS deal_id, d.stage_id, d.entered_stage_at, d.closed_at, d.pipeline_id, d.value,
       (SELECT min(g.id::text)::uuid FROM public.pipeline_stages g
         WHERE g.pipeline_id = d.pipeline_id AND g.key = 'fechado_ganho') AS ganho_id,
       (SELECT count(*) FROM public.pipeline_stages g
         WHERE g.pipeline_id = d.pipeline_id AND g.key = 'fechado_ganho') AS n_ganho
  FROM public.deals d
  JOIN public.pipeline_stages s ON s.id = d.stage_id
 WHERE s.key = 'chamado_reposicao'
   AND d.closed_at IS NOT NULL
   AND EXISTS (SELECT 1 FROM public.broadcast_leads bl
                WHERE bl.lead_id = d.lead_id AND bl.deal_moved_at > d.closed_at)
   FOR UPDATE OF d;

DO $$
DECLARE
  c_esperado CONSTANT int := COALESCE(NULLIF(current_setting('repasse.r3_esperado', true), '')::int, 30);
  v_alvo int;
  v_valor numeric;
  v_ruins text;
  v_upd int;
  v_depois int;
BEGIN
  SELECT count(*), COALESCE(sum(value), 0) INTO v_alvo, v_valor FROM r3_alvo;
  RAISE NOTICE 'R3 alvo: % (esperado %) | valor R$ %', v_alvo, c_esperado, v_valor;

  IF v_alvo = 0 THEN
    RAISE NOTICE 'R3: nada a fazer (já aplicado ou sem alvo)';
    RETURN;
  END IF;
  IF v_alvo <> c_esperado THEN
    RAISE EXCEPTION 'R3 abortado: alvo % <> esperado %', v_alvo, c_esperado;
  END IF;

  SELECT string_agg(DISTINCT COALESCE(pipeline_id::text, 'sem pipeline') || ' (' || n_ganho || ')', ', ')
    INTO v_ruins FROM r3_alvo WHERE n_ganho <> 1;
  IF v_ruins IS NOT NULL THEN
    RAISE EXCEPTION 'R3 abortado: pipeline sem exatamente 1 etapa fechado_ganho: %', v_ruins;
  END IF;

  INSERT INTO public.backup_r3_deals_20261019 (deal_id, stage_id_anterior, entered_stage_at_anterior, stage_id_novo)
  SELECT deal_id, stage_id, entered_stage_at, ganho_id FROM r3_alvo
  ON CONFLICT (deal_id) DO UPDATE
     SET stage_id_anterior = EXCLUDED.stage_id_anterior,
         entered_stage_at_anterior = EXCLUDED.entered_stage_at_anterior,
         stage_id_novo = EXCLUDED.stage_id_novo,
         gravado_em = now();

  UPDATE public.deals d
     SET stage_id = a.ganho_id, updated_at = now()
    FROM r3_alvo a
   WHERE d.id = a.deal_id;
  GET DIAGNOSTICS v_upd = ROW_COUNT;

  UPDATE public.deals d
     SET entered_stage_at = a.closed_at
    FROM r3_alvo a
   WHERE d.id = a.deal_id;

  IF v_upd <> c_esperado THEN
    RAISE EXCEPTION 'R3 abortado: % deals atualizados <> esperado %', v_upd, c_esperado;
  END IF;

  SELECT count(*) INTO v_depois
    FROM public.deals d
    JOIN public.pipeline_stages s ON s.id = d.stage_id
   WHERE s.key = 'chamado_reposicao'
     AND d.closed_at IS NOT NULL
     AND EXISTS (SELECT 1 FROM public.broadcast_leads bl
                  WHERE bl.lead_id = d.lead_id AND bl.deal_moved_at > d.closed_at);
  RAISE NOTICE 'R3 movidos: % | alvo depois: %', v_upd, v_depois;
END $$;

COMMIT;
