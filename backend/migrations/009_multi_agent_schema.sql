-- 009_multi_agent_schema.sql
-- Adiciona suporte a múltiplos agentes por conversa e por broadcast

ALTER TABLE agent_profiles
  ADD COLUMN IF NOT EXISTS prompt_key text NOT NULL DEFAULT 'valeria_inbound';

ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS agent_profile_id uuid REFERENCES agent_profiles(id);

ALTER TABLE broadcasts
  ADD COLUMN IF NOT EXISTS agent_profile_id uuid REFERENCES agent_profiles(id);

UPDATE agent_profiles
  SET prompt_key = 'valeria_inbound'
WHERE prompt_key = 'valeria_inbound';

INSERT INTO agent_profiles (name, model, prompt_key, base_prompt, stages)
VALUES (
  'ValerIA - Outbound / Recuperacao',
  'gemini-3-flash-preview',
  'valeria_outbound',
  '',
  '{
    "secretaria":    {"model": "gemini-3-flash-preview", "prompt": "", "tools": ["salvar_nome", "mudar_stage"]},
    "atacado":       {"model": "gemini-3-flash-preview", "prompt": "", "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto"]},
    "private_label": {"model": "gemini-3-flash-preview", "prompt": "", "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto"]},
    "exportacao":    {"model": "gemini-3-flash-preview", "prompt": "", "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano"]},
    "consumo":       {"model": "gemini-3-flash-preview", "prompt": "", "tools": ["salvar_nome", "mudar_stage"]}
  }'::jsonb
)
ON CONFLICT DO NOTHING;
