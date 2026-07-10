-- Camada de Memória de Longo Prazo (Lead Memory Layer) — "Dossiê do Lead".
-- Ver docs/superpowers/specs/2026-06-26-lead-memory-layer-design.md
--
-- rolling_summary            : o dossiê consolidado e evolutivo do lead (markdown).
-- rolling_summary_updated_at : timestamp da última geração — usado para debounce e como
--                              cursor do DELTA (mensagens com created_at > este valor).
-- rolling_summary_processing_at : LOCK de concorrência (D5). NULL = livre; setado p/ now()
--                              ao reivindicar. Lock mais velho que now()-LOCK_TTL (~5 min)
--                              é considerado travado/órfão e pode ser re-reivindicado.

ALTER TABLE leads ADD COLUMN IF NOT EXISTS rolling_summary text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS rolling_summary_updated_at timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS rolling_summary_processing_at timestamptz;

-- Índice parcial p/ a seleção do worker de inatividade (leads com sessão recém-encerrada).
CREATE INDEX IF NOT EXISTS idx_leads_rolling_summary_worker
    ON leads (last_customer_message_at)
    WHERE last_customer_message_at IS NOT NULL;

-- Recarrega o cache de schema do PostgREST/supabase-py (senão PGRST205 até o reload).
NOTIFY pgrst, 'reload schema';
