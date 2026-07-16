-- Desvincula o canal de rehearsal do agent_profile fixo (gpt-4.1).
-- Sem agent_profile_id, o orchestrator usa o DEFAULT_MODEL (gemini-2.5-flash),
-- que é o modelo que tem GEMINI_API_KEY no .env.local.
-- Aplicar SOMENTE no banco de homologação.
UPDATE channels
SET agent_profile_id = NULL
WHERE phone = 'rehearsal'
  AND provider = 'meta_cloud';
