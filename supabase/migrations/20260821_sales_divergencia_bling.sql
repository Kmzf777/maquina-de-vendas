-- supabase/migrations/20260821_sales_divergencia_bling.sql
--
-- Edicao recusada pelo Bling (tipicamente pedido ja faturado) pode valer no CRM,
-- mas nunca em silencio: divergencia silenciosa entre CRM e ERP e exatamente o
-- que a integracao existe para evitar. Estas colunas tornam a escolha auditavel.
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_divergent  boolean NOT NULL DEFAULT false;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_divergence jsonb;

CREATE INDEX IF NOT EXISTS sales_bling_divergent_idx
  ON sales (bling_divergent) WHERE bling_divergent;
