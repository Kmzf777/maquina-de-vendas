-- Índice parcial em messages.wamid.
-- Acelera os lookups por wamid usados em:
--   - dedup de ingestão (backstop no processor / _wamid_already_processed)
--   - resolução de reply (quoted_wamid) e reação (target_wamid) para contexto e UI
-- Parcial (WHERE wamid IS NOT NULL) porque a maioria das linhas de saída do agente não tem wamid.
-- Tabela pequena no momento (~4k linhas) → índice normal é suficiente; sem CONCURRENTLY
-- para permitir aplicação dentro de transação (apply_migration / supabase).
CREATE INDEX IF NOT EXISTS idx_messages_wamid
ON public.messages (wamid)
WHERE wamid IS NOT NULL;
