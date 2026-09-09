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
-- add_tags_to_lead resolve por NOME EXATO e nunca cria tags. Sem este seed, as
-- tags do bot seriam ignoradas sem nenhum erro visível.
INSERT INTO tags (name, color)
SELECT v.name, v.color
FROM (VALUES
  ('Reativação: Quente',              '#ef4444'),
  ('Reativação: 1 mês',               '#f59e0b'),
  ('Reativação: 3 meses',             '#eab308'),
  ('Reativação: 6 meses',             '#84cc16'),
  ('Reativação: Recusou',             '#6b7280'),
  ('Reativação: Atendimento humano',  '#3b82f6')
) AS v(name, color)
WHERE NOT EXISTS (SELECT 1 FROM tags t WHERE t.name = v.name);
