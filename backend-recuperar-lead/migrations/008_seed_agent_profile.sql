-- 008_seed_agent_profile.sql
-- Seed the default ValerIA agent profile with current stage configuration

INSERT INTO agent_profiles (name, model, base_prompt, stages)
VALUES (
    'ValerIA - Cafe Canastra',
    'gpt-4.1',
    '',
    '{
        "secretaria": {
            "model": "gpt-4.1",
            "prompt": "",
            "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano"]
        },
        "atacado": {
            "model": "gpt-4.1",
            "prompt": "",
            "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"]
        },
        "private_label": {
            "model": "gpt-4.1",
            "prompt": "",
            "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"]
        },
        "exportacao": {
            "model": "gpt-4.1-mini",
            "prompt": "",
            "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"]
        },
        "consumo": {
            "model": "gpt-4.1-mini",
            "prompt": "",
            "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"]
        }
    }'::jsonb
)
ON CONFLICT DO NOTHING;
