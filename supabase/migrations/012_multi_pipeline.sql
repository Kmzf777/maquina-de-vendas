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

-- 5. Habilitar realtime
DO $$
BEGIN
  ALTER PUBLICATION supabase_realtime ADD TABLE pipelines;
EXCEPTION WHEN OTHERS THEN NULL; END $$;
DO $$
BEGIN
  ALTER PUBLICATION supabase_realtime ADD TABLE pipeline_stages;
EXCEPTION WHEN OTHERS THEN NULL; END $$;
