CREATE TABLE IF NOT EXISTS sales (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id         uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  sold_at         timestamptz NOT NULL DEFAULT now(),
  value           numeric(12,2) NOT NULL,
  product         text NOT NULL,
  sold_by         text,
  deal_id         uuid REFERENCES deals(id) ON DELETE SET NULL,
  conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
  notes           text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sales_lead_id_sold_at ON sales(lead_id, sold_at);
CREATE INDEX IF NOT EXISTS idx_sales_sold_at ON sales(sold_at);
CREATE INDEX IF NOT EXISTS idx_sales_sold_by ON sales(sold_by);

ALTER TABLE sales ENABLE ROW LEVEL SECURITY;
CREATE POLICY "authenticated read sales" ON sales FOR SELECT TO authenticated USING (true);
CREATE POLICY "authenticated insert sales" ON sales FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "authenticated update sales" ON sales FOR UPDATE TO authenticated USING (true);
CREATE POLICY "authenticated delete sales" ON sales FOR DELETE TO authenticated USING (true);
