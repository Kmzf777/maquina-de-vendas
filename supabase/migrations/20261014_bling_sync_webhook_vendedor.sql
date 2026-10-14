-- supabase/migrations/20261014_bling_sync_webhook_vendedor.sql
--
-- Fase 1 da sincronia Bling (docs/avaliacao/2026-10-13-sync-bling-duas-contas.md,
-- runbook em docs/avaliacao/runbook-sync-bling.md).
--
-- NAO E APLICADA PELO DEPLOY. Aplicar a mao (scripts/apply_migrations.py ou SQL
-- editor) ANTES do push do codigo da Fase 1: `upsert_from_bling` passa a gravar
-- `sales.vendedor_fonte` e `sales.discount`, e o processador de webhook filtra e
-- grava `bling_webhook_events.next_attempt_at`. Sem estas colunas, todo upsert de
-- venda do Bling e todo claim da fila de webhook falham (PGRST204/42703).
--
-- So ADITIVA: nenhuma linha existente muda de valor. Colunas novas nascem NULL.
-- Reexecutar e seguro (IF NOT EXISTS em tudo). Sem BEGIN/COMMIT explicito, como
-- as outras migrations Bling: o editor do Supabase ja manda o arquivo numa
-- transacao implicita.
--
-- O backfill de vendedor/frete/cancelados dos pedidos JA gravados nao esta aqui:
-- ele precisa reler cada pedido no Bling (API) e roda pelo backfill/varredura,
-- com aprovacao do dono (runbook, passo A/B).

SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------------------
-- 1. sales: de onde veio o vendedor (regra D8) e o desconto do pedido
-- ---------------------------------------------------------------------------
-- vendedor_fonte: 'bling_pedido' (pedido.vendedor.id -> bling_seller_map),
-- 'bling_contato' (bling_contacts.vendedor_id -> bling_seller_map) ou
-- 'lead_assigned' (leads.assigned_to). NULL = o import nao preencheu `sold_by`
-- (venda do CRM/manual, `sold_by` ja preenchido, ou nenhuma fonte achou vendedor).
-- `sold_by_source` (20260824) continua existindo e e de outra coisa: marca as
-- normalizacoes manuais de `sold_by`; este import nunca escreve nela.
ALTER TABLE sales ADD COLUMN IF NOT EXISTS vendedor_fonte text;
ALTER TABLE sales DROP CONSTRAINT IF EXISTS sales_vendedor_fonte_check;
ALTER TABLE sales ADD CONSTRAINT sales_vendedor_fonte_check
  CHECK (vendedor_fonte IS NULL
         OR vendedor_fonte IN ('bling_pedido', 'bling_contato', 'lead_assigned', 'crm', 'manual'));

-- Desconto de cabecalho do pedido no Bling, em R$ (percentual ja convertido
-- sobre o total dos itens). `value` continua sendo o total do pedido (com frete
-- e desconto ja aplicados), como sempre foi.
ALTER TABLE sales ADD COLUMN IF NOT EXISTS discount numeric(12,2);

-- ---------------------------------------------------------------------------
-- 2. bling_webhook_events: backoff por evento
-- ---------------------------------------------------------------------------
-- Antes as 6 tentativas aconteciam em sequencia, uma por tick (minutos), bem
-- antes de o espelho de contatos ter o cliente novo -> `failed` para sempre.
-- next_attempt_at NULL = pode processar ja (todas as linhas existentes).
ALTER TABLE bling_webhook_events ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz;

-- O claim filtra `status = 'pending' AND (next_attempt_at IS NULL OR <= now())`
-- ordenado por received_at. O indice parcial antigo (received_at WHERE pending)
-- continua servindo; este cobre a varredura de reabertura dos `failed`.
CREATE INDEX IF NOT EXISTS bling_webhook_events_failed_idx
  ON bling_webhook_events (account, processed_at) WHERE status = 'failed';

-- ROLLBACK (nao executar; guardado aqui de proposito). So depois de voltar o
-- codigo para a versao anterior a Fase 1:
--   DROP INDEX IF EXISTS bling_webhook_events_failed_idx;
--   ALTER TABLE bling_webhook_events DROP COLUMN IF EXISTS next_attempt_at;
--   ALTER TABLE sales DROP CONSTRAINT IF EXISTS sales_vendedor_fonte_check;
--   ALTER TABLE sales DROP COLUMN IF EXISTS discount;
--   ALTER TABLE sales DROP COLUMN IF EXISTS vendedor_fonte;
