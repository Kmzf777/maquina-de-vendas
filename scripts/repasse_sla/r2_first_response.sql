-- scripts/repasse_sla/r2_first_response.sql — backfill R2 (cartão 7b143561, spec seção 7, D4/D6)
--
-- leads.first_response_at = 1ª mensagem sent_by='seller' (sem reação), em qualquer conversa do
-- lead, com created_at >= 1º marcador de repasse do lead
-- (role='system' AND content LIKE '[encaminhar\_humano] Lead encaminhado%').
-- Mesma regra do trigger trg_leads_first_response (migration 20261019_repasse_sla.sql), que
-- usa o marcador e não lead_events: o R2 não depende do R1.
--
-- Alvo: leads com resposta depois do 1º repasse e first_response_at
--   * NULL (o caso de quase todos: a coluna era 100% nula até a migration), ou
--   * POSTERIOR ao valor da regra: o trigger, ativo desde a migration, preenche com a próxima
--     mensagem seller que chega; num lead repassado e respondido ANTES da migration, isso é a
--     1ª mensagem depois do deploy, e não a 1ª resposta de verdade. O R2 corrige esses.
-- Guarda (lead_id, valor anterior, valor gravado) em public.backup_r2_first_response_20261019.
--
-- Aborta se algum lead tiver first_response_at ANTERIOR ao valor da regra, ou preenchido sem a
-- regra dar valor: nem o trigger nem o R2 gravam isso, então alguém gravou por outro caminho
-- (investigar antes). O plano dizia "aborta se o alvo já tiver valor"; ao pé da letra isso
-- impediria rodar depois do trigger estar ativo e tornaria a 2ª execução um erro.
--
-- Idempotente: na 2ª execução todo lead do alvo já tem o valor da regra.
-- Teto: 1.900 (esperado em 19/10/2026: 1.257). Acima disso, RAISE EXCEPTION e nada fica.
-- Rodar SÓ com o OK do Rafael:  psql -X -v ON_ERROR_STOP=1 < r2_first_response.sql
-- Desfazer: r2_rollback.sql

BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.backup_r2_first_response_20261019 (
  lead_id                    uuid PRIMARY KEY,
  first_response_at_anterior timestamptz,
  first_response_at_gravado  timestamptz NOT NULL,
  gravado_em                 timestamptz NOT NULL DEFAULT now()
);
-- tabela em public: fora da API (Supabase dá grants padrão a anon/authenticated)
ALTER TABLE public.backup_r2_first_response_20261019 ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.backup_r2_first_response_20261019 FROM PUBLIC, anon, authenticated;

CREATE TEMP TABLE r2_calc ON COMMIT DROP AS
WITH pm AS (
  SELECT m.lead_id, min(m.created_at) AS repasse_em
    FROM public.messages m
   WHERE m.role = 'system'
     AND m.content LIKE '[encaminhar\_humano] Lead encaminhado%'
     AND m.lead_id IS NOT NULL
   GROUP BY m.lead_id
)
SELECT pm.lead_id,
       (SELECT min(s.created_at)
          FROM public.messages s
         WHERE s.lead_id = pm.lead_id
           AND s.sent_by = 'seller'
           AND COALESCE(s.message_type, '') <> 'reaction'
           AND s.created_at >= pm.repasse_em) AS calculado
  FROM pm;

DO $$
DECLARE
  c_teto CONSTANT int := 1900;
  v_div int;
  v_ja int;
  v_antes int;
  v_corrigir int;
  v_upd int;
  v_depois int;
  v_ex text;
BEGIN
  SELECT count(*), string_agg(l.id || ' tem ' || l.first_response_at || ' (regra: ' || COALESCE(c.calculado::text, 'nenhum') || ')', '; ')
    INTO v_div, v_ex
    FROM public.leads l
    LEFT JOIN r2_calc c ON c.lead_id = l.id
   WHERE l.first_response_at IS NOT NULL
     AND (c.calculado IS NULL OR l.first_response_at < c.calculado);
  IF v_div > 0 THEN
    RAISE EXCEPTION 'R2 abortado: % lead(s) com first_response_at que diverge da regra D6 (anterior a ela ou sem resposta pela regra): %', v_div, left(v_ex, 2000);
  END IF;

  SELECT count(*) FILTER (WHERE l.first_response_at = c.calculado),
         count(*) FILTER (WHERE l.first_response_at IS NULL),
         count(*) FILTER (WHERE l.first_response_at > c.calculado)
    INTO v_ja, v_antes, v_corrigir
    FROM r2_calc c JOIN public.leads l ON l.id = c.lead_id
   WHERE c.calculado IS NOT NULL;
  RAISE NOTICE 'R2 leads com resposta após o 1º repasse: já certos: % | a preencher: % | a corrigir: %', v_ja, v_antes, v_corrigir;

  -- FOR UPDATE: o valor anterior lido aqui é o que o UPDATE substitui (o trigger pode gravar
  -- em paralelo; quem chegar depois espera o COMMIT e então vê o valor novo, não-NULL).
  WITH alvo AS (
    SELECT l.id, l.first_response_at AS anterior, c.calculado
      FROM public.leads l JOIN r2_calc c ON c.lead_id = l.id
     WHERE c.calculado IS NOT NULL
       AND (l.first_response_at IS NULL OR l.first_response_at > c.calculado)
       FOR UPDATE OF l
  ), upd AS (
    UPDATE public.leads l
       SET first_response_at = a.calculado
      FROM alvo a
     WHERE l.id = a.id
    RETURNING l.id, a.anterior, l.first_response_at
  )
  INSERT INTO public.backup_r2_first_response_20261019 (lead_id, first_response_at_anterior, first_response_at_gravado)
  SELECT id, anterior, first_response_at FROM upd
  ON CONFLICT (lead_id) DO UPDATE
     SET first_response_at_gravado = EXCLUDED.first_response_at_gravado, gravado_em = now();
  GET DIAGNOSTICS v_upd = ROW_COUNT;

  IF v_upd > c_teto THEN
    RAISE EXCEPTION 'R2 abortado: % leads passam do teto de %', v_upd, c_teto;
  END IF;

  SELECT count(*) INTO v_depois
    FROM r2_calc c JOIN public.leads l ON l.id = c.lead_id
   WHERE c.calculado IS NOT NULL AND (l.first_response_at IS NULL OR l.first_response_at <> c.calculado);
  RAISE NOTICE 'R2 gravados: % | fora da regra depois: %', v_upd, v_depois;
END $$;

COMMIT;
