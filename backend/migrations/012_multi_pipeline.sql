-- 012_multi_pipeline.sql
-- Cria tabelas pipelines e pipeline_stages, migra deals existentes

-- 1. Tabela de pipelines
CREATE TABLE IF NOT EXISTS pipelines (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL,
  order_index int  NOT NULL DEFAULT 0,
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now()
);

-- 2. Tabela de stages por pipeline
CREATE TABLE IF NOT EXISTS pipeline_stages (
  id           uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_id  uuid    NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
  label        text    NOT NULL,
  key          text,           -- só preenchido em stages protegidos: 'fechado_ganho' | 'fechado_perdido'
  dot_color    text    NOT NULL DEFAULT '#5b8aad',
  order_index  int     NOT NULL DEFAULT 0,
  is_protected boolean NOT NULL DEFAULT false,
  created_at   timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_stages_order ON pipeline_stages(pipeline_id, order_index);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_stages_key_unique
  ON pipeline_stages(pipeline_id, key)
  WHERE key IS NOT NULL;

-- 3. Adicionar colunas na tabela deals
ALTER TABLE deals ADD COLUMN IF NOT EXISTS pipeline_id uuid REFERENCES pipelines(id);
ALTER TABLE deals ADD COLUMN IF NOT EXISTS stage_id    uuid REFERENCES pipeline_stages(id);

CREATE INDEX IF NOT EXISTS idx_deals_pipeline_id ON deals(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_deals_stage_id    ON deals(stage_id);

-- 4. Função utilitária para shiftar order_index de stages
CREATE OR REPLACE FUNCTION increment_stage_order(p_pipeline_id uuid, p_from_order int)
RETURNS void LANGUAGE sql AS $$
  UPDATE pipeline_stages
  SET order_index = order_index + 1
  WHERE pipeline_id = p_pipeline_id AND order_index >= p_from_order;
$$;

-- 5. Seed: Funil Principal com 6 stages default + migrar deals existentes
DO $$
DECLARE
  v_pid  uuid;
  v_s0   uuid;
  v_s1   uuid;
  v_s2   uuid;
  v_s3   uuid;
  v_s4   uuid;
  v_s5   uuid;
BEGIN
  -- Guard: skip if already seeded
  IF EXISTS (SELECT 1 FROM pipelines WHERE name = 'Funil Principal') THEN
    RETURN;
  END IF;

  INSERT INTO pipelines (name, order_index) VALUES ('Funil Principal', 0)
    RETURNING id INTO v_pid;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Novo', null, '#e07a7a', 0, false) RETURNING id INTO v_s0;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Contato', null, '#d4a04a', 1, false) RETURNING id INTO v_s1;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Proposta', null, '#9b7abf', 2, false) RETURNING id INTO v_s2;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Negociação', null, '#5b8aad', 3, false) RETURNING id INTO v_s3;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Fechado Ganho', 'fechado_ganho', '#5aad65', 4, true) RETURNING id INTO v_s4;

  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
    VALUES (v_pid, 'Perdido', 'fechado_perdido', '#9ca3af', 5, true) RETURNING id INTO v_s5;

  -- Migrar deals existentes para o Funil Principal
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s0 WHERE stage = 'novo';
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s1 WHERE stage = 'contato';
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s2 WHERE stage = 'proposta';
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s3 WHERE stage = 'negociacao';
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s4 WHERE stage = 'fechado_ganho';
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s5 WHERE stage = 'fechado_perdido';
  -- Fallback: deals com stage desconhecido vão para 'Novo'
  UPDATE deals SET pipeline_id = v_pid, stage_id = v_s0 WHERE pipeline_id IS NULL;
END $$;

-- 6. Habilitar realtime
DO $$
BEGIN
  ALTER PUBLICATION supabase_realtime ADD TABLE pipelines;
EXCEPTION WHEN OTHERS THEN NULL; END $$;
DO $$
BEGIN
  ALTER PUBLICATION supabase_realtime ADD TABLE pipeline_stages;
EXCEPTION WHEN OTHERS THEN NULL; END $$;
