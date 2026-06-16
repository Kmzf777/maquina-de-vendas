-- Rastreabilidade de persona da IA: identifica qual prompt_key (persona) gerou
-- cada mensagem de saída — ex: 'valeria_outbound' vs 'valeria_inbound'.
-- NULLABLE: inserts antigos e mensagens não geradas por persona (user, broadcast,
-- followup, handoff) permanecem com agent_persona = NULL sem quebrar nada.
-- Idempotente: IF NOT EXISTS.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS agent_persona VARCHAR NULL;

COMMENT ON COLUMN messages.agent_persona IS
  'prompt_key da persona da IA que gerou a mensagem (valeria_inbound | valeria_outbound). NULL para mensagens não geradas por persona.';
