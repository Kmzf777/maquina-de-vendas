-- FinOps LLM (auditoria 08/07): observabilidade de cache + preços Gemini versionados.
--
-- 1) token_usage ganha duas colunas de observabilidade:
--    - thoughts_tokens: tokens de "thinking" (thoughts_token_count) da chamada. O CUSTO
--      deles já está dentro de completion_tokens (gemini_native soma thinking no output,
--      commit 8f8b81e) — a coluna existe para medir a PARTICIPAÇÃO do thinking no gasto.
--    - cached_tokens: subconjunto de prompt_tokens servido pelo implicit caching do Gemini
--      (cached_content_token_count), cobrado a ~25% do preço de input. É a métrica que
--      comprova o hit-rate do prefixo estático do prompt (commit a7a287e) e corrige o
--      total_cost nos hits (token_tracker aplica o desconto).
--    O backend tem fallback p/ o formato legado se estas colunas faltarem (PGRST204),
--    então a ordem deploy/migração não importa — mas sem a migração não há telemetria.
--
-- 2) model_pricing ganha os preços da família gemini-2.5 VERSIONADOS (antes só existiam
--    seeds de modelos OpenAI legados na 005; o preço do 2.5-flash foi corrigido em prod
--    via SQL manual — cb6a716 — e ficou fora do versionamento). Valores em USD por token
--    (lista Google jul/2026; output do 2.5-flash INCLUI thinking):
--      gemini-2.5-flash:      in US$0,30/1M  out US$2,50/1M
--      gemini-2.5-flash-lite: in US$0,10/1M  out US$0,40/1M
--      gemini-2.5-pro:        in US$1,25/1M  out US$10,00/1M (faixa <=200K de prompt)
--    ON CONFLICT DO NOTHING: linhas já corrigidas à mão em prod NÃO são sobrescritas.

ALTER TABLE public.token_usage ADD COLUMN IF NOT EXISTS thoughts_tokens integer NOT NULL DEFAULT 0;
ALTER TABLE public.token_usage ADD COLUMN IF NOT EXISTS cached_tokens integer NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.token_usage.thoughts_tokens IS
  'Tokens de thinking (thoughts_token_count). Custo já incluso em completion_tokens; coluna é só observabilidade.';
COMMENT ON COLUMN public.token_usage.cached_tokens IS
  'Tokens de prompt servidos pelo implicit caching do Gemini (cobrados a ~25% do preço de input).';

INSERT INTO public.model_pricing (model, price_per_input_token, price_per_output_token) VALUES
    ('gemini-2.5-flash',      0.0000003,  0.0000025),
    ('gemini-2.5-flash-lite', 0.0000001,  0.0000004),
    ('gemini-2.5-pro',        0.00000125, 0.00001)
ON CONFLICT (model) DO NOTHING;

-- PostgREST só enxerga colunas novas após reload do schema cache (PGRST204/PGRST205
-- até lá — ver runbook de DDL do projeto).
NOTIFY pgrst, 'reload schema';
