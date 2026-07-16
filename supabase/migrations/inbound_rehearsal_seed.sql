-- inbound_rehearsal_seed.sql
-- Seed EXCLUSIVO para o banco de homologação do rehearsal inbound.
-- NÃO aplicar em produção.
--
-- Cria canal com o phone_number_id real da Valéria Inbound (1079773125220705)
-- apontando para agent_profile com prompt_key='valeria_inbound'.
-- Requisito: agent_profile valeria_inbound já criado por 009_multi_agent_schema.sql (default).

INSERT INTO channels (
    name,
    phone,
    provider,
    provider_config,
    agent_profile_id,
    is_active
)
VALUES (
    'Canal Inbound Rehearsal',
    '553492009777',
    'meta_cloud',
    '{"phone_number_id": "1079773125220705", "display_phone_number": "553492009777", "verify_token": "rehearsal", "access_token": "", "app_secret": ""}'::jsonb,
    (SELECT id FROM agent_profiles WHERE prompt_key = 'valeria_inbound' LIMIT 1),
    true
)
ON CONFLICT (phone) DO NOTHING;
