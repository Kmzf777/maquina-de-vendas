-- 20260820_button_flow_agent.sql
-- Bot de botões (Meta interactive) para qualificação de reativação.
--
-- Introduz o conceito de agente NÃO-LLM: `agent_profiles.kind='button_flow'`.
-- Um perfil desse tipo é atendido por app/button_flow/runner.py (fluxo fechado,
-- determinístico) em vez do orquestrador Gemini — inclusive em canais mode='human',
-- porque um fluxo de botões não é IA generativa.
--
-- APLICAR À MÃO no Supabase: o deploy não roda migrations. Até ser aplicada, o código
-- novo é inerte (nenhum perfil button_flow existe, o gate nunca dispara).

-- 1) Tipo do agente ---------------------------------------------------------
ALTER TABLE agent_profiles
  ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'llm';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'agent_profiles_kind_check'
      AND conrelid = 'agent_profiles'::regclass
  ) THEN
    ALTER TABLE agent_profiles
      ADD CONSTRAINT agent_profiles_kind_check
      CHECK (kind IN ('llm', 'button_flow'));
  END IF;
END $$;

COMMENT ON COLUMN agent_profiles.kind IS
  'llm = atendido pelo orquestrador Gemini; button_flow = fluxo determinístico de botões (app/button_flow).';

-- 2) Estado do fluxo por conversa -------------------------------------------
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS flow_state jsonb DEFAULT NULL;

COMMENT ON COLUMN conversations.flow_state IS
  'Estado do bot de botões: {"flow","node","nudged","updated_at"}. NULL = fluxo não iniciado.';

-- 3) O agente ---------------------------------------------------------------
INSERT INTO agent_profiles (name, kind, prompt_key, model, base_prompt, stages)
SELECT 'Bot Reativação', 'button_flow', 'bot_reativacao', '', '', '{}'::jsonb
WHERE NOT EXISTS (
  SELECT 1 FROM agent_profiles WHERE prompt_key = 'bot_reativacao'
);

-- 4) Tags do desfecho -------------------------------------------------------
-- add_tags_to_lead (leads/service.py) resolve tag por NOME EXATO e NUNCA cria tag
-- que não exista. Sem este seed o bot chamaria add_tags_to_lead com um nome órfão,
-- a função devolveria sem erro, sem log e sem vínculo — e o desfecho de 1.208 leads
-- ficaria invisível no CRM. É o modo de falha mais silencioso do projeto inteiro.
--
-- ⚠️ RENOMEADAS EM 09/09/2026. O seed original usava "Reativação: ..." e prazos em
-- meses ("1 mês" / "3 meses" / "6 meses"). O agente virou "Recuperação" e os prazos
-- viraram DIAS (30/60/90), porque o intervalo médio entre compras desta coorte é
-- 78-122 dias — "3 meses" era um rótulo pior para o mesmo número. Como esta migração
-- ainda NÃO foi aplicada em produção (verificado em 09/09/2026: agent_profiles.kind
-- não existe, conversations.flow_state não existe, nenhuma tag "Reativação: ..."
-- de desfecho no banco), corrigir aqui basta — não há nada a renomear.
--
-- A LISTA ABAIXO É O ESPELHO DE backend/app/button_flow/flows.py (TAG_* e PRAZOS).
-- Divergir de um caractere reproduz exatamente o bug acima; o teste
-- test_recuperacao_migration_2026_09_09.py lê os dois lados e trava a igualdade.
INSERT INTO tags (name, color)
SELECT v.name, v.color
FROM (VALUES
  ('Recuperação: Quente',               '#ef4444'),
  ('Recuperação: Recusou',              '#6b7280'),
  ('Recuperação: Atendimento humano',   '#3b82f6'),
  ('Recuperação: Cadastro mantido',     '#14b8a6'),
  ('Recuperação: Pretexto contestado',  '#a855f7'),
  ('Recuperação: 30 dias',              '#f59e0b'),
  ('Recuperação: 60 dias',              '#eab308'),
  ('Recuperação: 90 dias',              '#84cc16')
) AS v(name, color)
WHERE NOT EXISTS (SELECT 1 FROM tags t WHERE t.name = v.name);
