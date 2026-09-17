-- scripts/apaga_campanhas_de_teste.sql
--
-- ⛔ NÃO EXECUTAR SEM AUTORIZAÇÃO EXPLÍCITA DO DONO. Apaga linhas em
--    PRODUÇÃO. Nenhum agente de IA deve rodar este arquivo. Ele existe para
--    ser LIDO, revisado, autorizado e só então aplicado à mão por um humano:
--    primeiro o bloco "SELECT DE CONFERÊNCIA — ANTES" sozinho, e só depois
--    de ler o resultado o bloco BEGIN…COMMIT.
--
-- ── O QUE ELE FAZ ────────────────────────────────────────────────────────────
-- Apaga as 3 campanhas de LIXO DE TESTE do sistema de automação
-- (`campaigns`, supabase/migrations/20260527_automation_campaigns_schema.sql):
--
--     Tiburcio-Miranda-2       status='draft'   6 nós
--     cadencia                 status='draft'   3 nós
--     Cadencia Teste deletar   status='draft'   1 nó
--
-- Medido em produção em 16/09/2026: o banco tem 16 campanhas no total, 0 com
-- status='active', e 0 matrículas (`campaign_enrollments`) em toda a
-- história — nenhuma das 16 nunca rodou para lead nenhum. As outras 13 são
-- seeds legítimos (esteiras genéricas, esteiras do João, espelho da
-- ValerIA) e este arquivo NÃO toca em nenhuma delas: o WHERE casa só os 3
-- nomes exatos acima, nunca um padrão (`LIKE`/`ILIKE`) que pudesse pegar uma
-- campanha real cujo nome contivesse "teste" ou "cadência".
--
-- ── EFEITO CASCATA (leia antes de aplicar) ──────────────────────────────────
-- `campaign_nodes.campaign_id` é `REFERENCES campaigns(id) ON DELETE
-- CASCADE` (20260527_automation_campaigns_schema.sql:23). Apagar as 3
-- linhas de `campaigns` apaga em cascata os 10 nós delas (6 + 3 + 1) — não é
-- um DELETE separado neste arquivo, é o Postgres cumprindo a FK. Nenhuma das
-- 3 tem `campaign_enrollments` (é a própria guarda do WHERE abaixo), então a
-- cascata não alcança matrícula nenhuma.
--
-- ── POR QUE É SEGURO ─────────────────────────────────────────────────────────
-- O DELETE exige, cumulativamente:
--   · name IN (...)     — os 3 nomes EXATOS, não um padrão
--   · status = 'draft'  — nenhuma das 3 nunca foi ativada
--   · NOT EXISTS em campaign_enrollments — nenhuma delas nunca rodou para
--     lead nenhum; se alguma ganhar uma matrícula entre a escrita deste
--     arquivo e a aplicação, ela sai do alvo sozinha.
--
-- ── O QUE ESTE ARQUIVO NÃO FAZ ──────────────────────────────────────────────
-- Não mexe nas outras 13 campanhas. Não mexe em `leads`, `deals`, `sales`
-- nem em tag alguma. Não é migration: não cria nem altera estrutura de
-- tabela — não pertence a `supabase/migrations/`, é uma limpeza pontual de
-- DADO de teste, descartável depois de aplicada uma única vez.
--
-- ── COMO APLICAR ─────────────────────────────────────────────────────────────
-- SQL puro, sem meta-comando de psql — roda direto no editor SQL do
-- Supabase.
--   1. Rode o bloco "SELECT DE CONFERÊNCIA — ANTES" sozinho e confira: 3
--      linhas, matriculas=0 em todas.
--   2. Rode o bloco BEGIN…COMMIT inteiro de uma vez.
--   3. Rode o bloco "SELECT DE CONFERÊNCIA — DEPOIS" e confira: 0 linhas.

-- ===========================================================================
-- SELECT DE CONFERÊNCIA — ANTES   (rodar sozinho, ler o resultado antes do BEGIN)
-- ===========================================================================
SELECT c.id,
       c.name,
       c.status,
       c.env_tag,
       c.created_at,
       (SELECT count(*) FROM campaign_nodes n WHERE n.campaign_id = c.id)       AS nos,
       (SELECT count(*) FROM campaign_enrollments e WHERE e.campaign_id = c.id) AS matriculas
  FROM campaigns c
 WHERE c.name IN ('Tiburcio-Miranda-2', 'cadencia', 'Cadencia Teste deletar')
   AND c.status = 'draft'
   AND NOT EXISTS (
     SELECT 1 FROM campaign_enrollments e WHERE e.campaign_id = c.id
   )
 ORDER BY c.name;
-- Esperado em 16/09/2026: 3 linhas, matriculas=0 em todas, nos = 6/3/1.

-- ===========================================================================
-- O APAGAMENTO
-- ===========================================================================
BEGIN;

-- Guarda de sanidade. 3 é o número medido; abortar aqui desfaz a transação
-- inteira sem apagar nada — nunca "pela metade".
DO $$
DECLARE
  alvo integer;
BEGIN
  SELECT count(*) INTO alvo
    FROM campaigns c
   WHERE c.name IN ('Tiburcio-Miranda-2', 'cadencia', 'Cadencia Teste deletar')
     AND c.status = 'draft'
     AND NOT EXISTS (
       SELECT 1 FROM campaign_enrollments e WHERE e.campaign_id = c.id
     );

  IF alvo = 0 THEN
    RAISE EXCEPTION 'nenhuma campanha de teste encontrada -- ou ja foi apagada, ou o WHERE mudou';
  END IF;
  IF alvo <> 3 THEN
    RAISE EXCEPTION 'esperava exatamente 3 campanhas de teste, achei % -- revise antes de continuar', alvo;
  END IF;

  RAISE NOTICE 'campanhas de teste a apagar: %', alvo;
END $$;

-- campaign_nodes cai por ON DELETE CASCADE (ver seção acima) — nenhum
-- comando explícito para essa tabela é necessário nem escrito aqui.
DELETE FROM campaigns AS c
 WHERE c.name IN ('Tiburcio-Miranda-2', 'cadencia', 'Cadencia Teste deletar')
   AND c.status = 'draft'
   AND NOT EXISTS (
     SELECT 1 FROM campaign_enrollments e WHERE e.campaign_id = c.id
   );

COMMIT;

-- ===========================================================================
-- SELECT DE CONFERÊNCIA — DEPOIS
-- ===========================================================================
-- Esperado: 0 linhas.
SELECT c.id, c.name
  FROM campaigns c
 WHERE c.name IN ('Tiburcio-Miranda-2', 'cadencia', 'Cadencia Teste deletar');

-- E as outras 13 continuam intactas:
-- Esperado: 13.
SELECT count(*) AS campanhas_restantes FROM campaigns;
