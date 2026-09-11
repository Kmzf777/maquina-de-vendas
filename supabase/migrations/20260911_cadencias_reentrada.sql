-- 20260911_cadencias_reentrada.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. O GitHub Actions sobe imagem; esta migration roda a
--    MAO no SQL editor do Supabase, depois de lida e revisada por um humano.
--    Nenhum agente de IA deve aplica-la.
--
-- ── O QUE FAZ ───────────────────────────────────────────────────────────────
-- Derruba a UNIQUE TOTAL (campaign_id, lead_id) de campaign_enrollments, preservando
-- o indice PARCIAL que protege matricula viva.
--
-- ── POR QUE ─────────────────────────────────────────────────────────────────
-- A constraint total impede um lead de entrar numa campanha mais de uma vez NA VIDA:
-- assim que a matricula vira 'completed', `create_enrollment` colide e o lead nunca
-- mais reentra. Isso e fatal para a esteira de reposicao, cujo desenho e justamente
-- repetir a cada 45 dias, e para qualquer automacao recorrente.
--
-- O que precisa continuar protegido e outra coisa: duas matriculas VIVAS do mesmo
-- lead na mesma campanha. Disso cuida o indice parcial `uq_campaign_enrollments_active`
-- (20260709_cadence_enrollment_hardening.sql), que permanece intocado.
--
-- A constraint total e DRIFT — nasceu fora de migration; nenhum arquivo em
-- supabase/migrations/ a cria. Esta migration a remove e documenta o porque, para
-- que ela nao volte por acidente.
--
-- ── RISCO ───────────────────────────────────────────────────────────────────
-- Baixo e medido: `campaign_enrollments` tem ZERO linhas em toda a historia
-- (medicao de 11/09/2026). Nao ha dado existente que a remocao possa afetar.
--
-- Reexecutar e seguro: DROP ... IF EXISTS.

ALTER TABLE campaign_enrollments
  DROP CONSTRAINT IF EXISTS campaign_enrollments_campaign_id_lead_id_key;

-- O PostgREST serve o schema em cache: sem isto o CRM pode responder PGRST204/205.
-- Precedente: 20260825:195, 20260909:162, 20260910.
NOTIFY pgrst, 'reload schema';
