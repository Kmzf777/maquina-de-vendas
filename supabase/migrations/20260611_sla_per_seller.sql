-- ============================================================
-- SLA por vendedor: config individual, alvo global, anulações
-- ============================================================

-- 1. Config por vendedor (canal 1:1)
CREATE TABLE IF NOT EXISTS sla_seller_config (
  user_id              uuid PRIMARY KEY,
  channel_id           uuid NOT NULL UNIQUE,
  display_name         text NOT NULL DEFAULT '',
  window_start_minute  int  NOT NULL DEFAULT 600,   -- 10h00
  window_end_minute    int  NOT NULL DEFAULT 960,   -- 16h00
  active_weekdays      int[] NOT NULL DEFAULT '{1,2,3,4,5}', -- 0=dom..6=sáb
  active               boolean NOT NULL DEFAULT true,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

-- 2. Configuração global (singleton)
CREATE TABLE IF NOT EXISTS sla_settings (
  id             int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  target_minutes int NOT NULL DEFAULT 20,
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- 3. Anulações (dias inteiros; user_id NULL = global)
CREATE TABLE IF NOT EXISTS sla_overrides (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid,                       -- NULL = todos os vendedores
  start_date date NOT NULL,
  end_date   date NOT NULL,
  reason     text,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_sla_overrides_user ON sla_overrides(user_id);
CREATE INDEX IF NOT EXISTS idx_sla_overrides_dates ON sla_overrides(start_date, end_date);

-- 4. RLS: leitura para autenticados; escrita só via service role (rotas admin)
ALTER TABLE sla_seller_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE sla_settings      ENABLE ROW LEVEL SECURITY;
ALTER TABLE sla_overrides     ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sla_seller_config_read ON sla_seller_config;
CREATE POLICY sla_seller_config_read ON sla_seller_config
  FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS sla_settings_read ON sla_settings;
CREATE POLICY sla_settings_read ON sla_settings
  FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS sla_overrides_read ON sla_overrides;
CREATE POLICY sla_overrides_read ON sla_overrides
  FOR SELECT TO authenticated USING (true);

-- 5. Seed: alvo global + config do João (não regredir o dashboard atual)
INSERT INTO sla_settings (id, target_minutes)
  VALUES (1, 20)
  ON CONFLICT (id) DO NOTHING;

-- João: canal a3a607b1-..., janela 10-16h seg-sex.
-- user_id derivado do canal (assume coluna channels.owner_user_id; ajustar se o
-- vínculo real for outro). Se não houver user vinculado ainda, o admin completa
-- pela aba SLA — o seed abaixo é best-effort e não falha se já existir.
INSERT INTO sla_seller_config (user_id, channel_id, display_name)
  SELECT gen_random_uuid(), 'a3a607b1-6bff-4370-8609-b275eef270dd', 'João'
  WHERE NOT EXISTS (
    SELECT 1 FROM sla_seller_config
    WHERE channel_id = 'a3a607b1-6bff-4370-8609-b275eef270dd'
  );

-- 6. Remover RPC obsoleta (substituída pelo passe único client-side)
DROP FUNCTION IF EXISTS get_seller_overdue_candidates(uuid);
