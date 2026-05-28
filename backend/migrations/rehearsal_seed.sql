-- rehearsal_seed.sql
-- Seed EXCLUSIVO para o banco de homologação do rehearsal runner.
-- NÃO aplicar em produção.
--
-- Requisitos:
--   1. Canal com phone_number_id="rehearsal" para o webhook router encontrá-lo.
--   2. Agent profile valeria_outbound já criado por 009_multi_agent_schema.sql.

INSERT INTO channels (
    name,
    phone,
    provider,
    provider_config,
    agent_profile_id,
    is_active
)
VALUES (
    'Canal Rehearsal',
    'rehearsal',
    'meta_cloud',
    '{"phone_number_id": "rehearsal", "verify_token": "rehearsal", "access_token": "", "app_secret": ""}'::jsonb,
    (SELECT id FROM agent_profiles WHERE prompt_key = 'valeria_outbound' LIMIT 1),
    true
)
ON CONFLICT (phone) DO NOTHING;
