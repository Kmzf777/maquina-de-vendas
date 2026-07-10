-- Fix 2 (sincronia visual de persona): denormaliza a persona EFETIVA resolvida pelo
-- backend a cada turno da IA na conversa, para o frontend exibir exatamente a persona
-- que rodou (elimina a "mentira visual" do pin estático agent_profile_id).
--
-- Coluna nullable: NULL = nenhuma resposta de IA ainda (frontend cai no fallback do pin).
-- Escrita fail-soft no processor; leitura via select("*") na listagem de conversas.

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS agent_persona text;

COMMENT ON COLUMN conversations.agent_persona IS
  'Persona (prompt_key) efetiva da última resposta da IA — valeria_inbound | valeria_outbound. Denormalizada do resolve_persona_prompt_key para display no frontend.';

-- Recarrega o cache de schema do PostgREST para a coluna ficar visível à supabase-py imediatamente.
NOTIFY pgrst, 'reload schema';
