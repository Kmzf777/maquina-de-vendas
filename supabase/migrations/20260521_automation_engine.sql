-- supabase/migrations/20260521_automation_engine.sql

-- 1. Colunas novas em campaigns
ALTER TABLE campaigns
  ADD COLUMN IF NOT EXISTS priority      INT NOT NULL DEFAULT 5,
  ADD COLUMN IF NOT EXISTS frequency_cap INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS send_start_hour INT NOT NULL DEFAULT 7,
  ADD COLUMN IF NOT EXISTS send_end_hour   INT NOT NULL DEFAULT 18;

-- 2. Colunas novas em campaign_enrollments
ALTER TABLE campaign_enrollments
  ADD COLUMN IF NOT EXISTS retry_count    INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_error     TEXT,
  ADD COLUMN IF NOT EXISTS next_retry_at  TIMESTAMPTZ;

-- 3. Tabela de controle de frequência diária
CREATE TABLE IF NOT EXISTS lead_daily_sends (
  lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  date    DATE NOT NULL,
  count   INT  NOT NULL DEFAULT 0,
  PRIMARY KEY (lead_id, date)
);

-- 4. Função para incremento atômico
CREATE OR REPLACE FUNCTION increment_daily_send(p_lead_id UUID, p_date DATE)
RETURNS VOID AS $$
BEGIN
  INSERT INTO lead_daily_sends (lead_id, date, count)
  VALUES (p_lead_id, p_date, 1)
  ON CONFLICT (lead_id, date)
  DO UPDATE SET count = lead_daily_sends.count + 1;
END;
$$ LANGUAGE plpgsql;

-- 5. Função para repurchase_window trigger (GROUP BY não disponível via PostgREST)
CREATE OR REPLACE FUNCTION get_leads_for_repurchase(cutoff_date TIMESTAMPTZ, p_env_tag TEXT)
RETURNS TABLE(id UUID, phone TEXT) AS $$
  SELECT l.id, l.phone
  FROM leads l
  WHERE l.env_tag = p_env_tag
    AND l.ai_enabled = TRUE
  AND EXISTS (SELECT 1 FROM sales s WHERE s.lead_id = l.id)
  AND (
    SELECT MAX(s2.sold_at) FROM sales s2 WHERE s2.lead_id = l.id
  ) <= cutoff_date;
$$ LANGUAGE sql;

-- 6. Função para no_sale_in_stage trigger
CREATE OR REPLACE FUNCTION get_leads_no_sale_in_stage(
  p_stage TEXT,
  cutoff_date TIMESTAMPTZ,
  p_env_tag TEXT
)
RETURNS TABLE(id UUID, phone TEXT) AS $$
  SELECT l.id, l.phone
  FROM leads l
  WHERE l.env_tag = p_env_tag
    AND l.stage = p_stage
    AND l.ai_enabled = TRUE
    AND l.entered_stage_at IS NOT NULL
    AND l.entered_stage_at <= cutoff_date
    AND NOT EXISTS (
      SELECT 1 FROM sales s WHERE s.lead_id = l.id
    );
$$ LANGUAGE sql;
