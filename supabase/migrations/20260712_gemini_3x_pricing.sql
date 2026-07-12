-- FinOps Higiene (12/07/2026): versiona os preços da família Gemini 3.x que existiam
-- APENAS como linhas manuais no banco de produção (inseridas durante o incidente do
-- falso sunset de 09/07 — commit 9269e80/af58de8). Modelo sem linha em model_pricing
-- gera total_cost=0 SILENCIOSO no token_tracker; regra da casa: troca de modelo exige
-- migração de pricing no MESMO commit.
--
-- Valores copiados do prod em 12/07 (USD por token):
--   gemini-3.5-flash        $1.50/M input  $9.00/M output
--   gemini-3.1-flash-lite   $0.25/M input  $1.50/M output
--   gemini-3-flash-preview  $0.50/M input  $3.00/M output
--
-- ON CONFLICT DO NOTHING preserva qualquer valor já presente (mesma convenção da
-- 20260708_token_usage_cache_cols_gemini_pricing.sql).

INSERT INTO model_pricing (model, price_per_input_token, price_per_output_token)
VALUES
    ('gemini-3.5-flash',       0.0000015,  0.000009),
    ('gemini-3.1-flash-lite',  0.00000025, 0.0000015),
    ('gemini-3-flash-preview', 0.0000005,  0.000003)
ON CONFLICT (model) DO NOTHING;
