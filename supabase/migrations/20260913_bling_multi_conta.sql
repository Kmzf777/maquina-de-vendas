-- supabase/migrations/20260913_bling_multi_conta.sql
--
-- Segunda conta Bling (spec 2026-09-13-bling-segunda-conta-design.md).
--
-- NAO E APLICADA PELO DEPLOY. O GitHub Actions sobe imagem, nao roda migration:
-- este arquivo precisa ser executado a mao no SQL editor do Supabase, IMEDIATAMENTE
-- antes do push, em horario de baixo movimento. Entre a aplicacao e o push existe
-- uma janela em que o codigo antigo faz upsert com on_conflict="id" contra PK
-- composta e toma 42P10 — sync de catalogo e criacao de pedido falham nela.
--
-- A conta existente recebe o slug 'default', NAO 'principal'. Renomear a linha de
-- bling_credentials abriria uma janela em que o codigo antigo nao acha credencial;
-- se um refresh cair nessa janela o Bling rotaciona o refresh_token e a linha nova
-- fica com um token ja invalidado — o cenario de reautorizacao manual que auth.py
-- marca como critico. O nome legivel vive como label na config, nao como chave.

-- ===========================================================================
-- 1. Espelhos: coluna account + PK composta
-- ===========================================================================
ALTER TABLE bling_products        ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
ALTER TABLE bling_contacts        ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
ALTER TABLE bling_sellers         ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
ALTER TABLE bling_payment_methods ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
ALTER TABLE bling_seller_map      ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
ALTER TABLE bling_sync_state      ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
ALTER TABLE bling_webhook_events  ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
ALTER TABLE bling_jobs            ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';

-- A FK de bling_seller_map aponta para bling_sellers(id) e IMPEDE a troca da PK.
-- Derrubar antes, recriar composta depois. E a UNICA FK apontando para uma tabela
-- bling_* — conferido no catalogo do Postgres de producao em 14/09/2026.
ALTER TABLE bling_seller_map DROP CONSTRAINT IF EXISTS bling_seller_map_bling_seller_id_fkey;

ALTER TABLE bling_products        DROP CONSTRAINT IF EXISTS bling_products_pkey;
ALTER TABLE bling_products        ADD PRIMARY KEY (account, id);
ALTER TABLE bling_contacts        DROP CONSTRAINT IF EXISTS bling_contacts_pkey;
ALTER TABLE bling_contacts        ADD PRIMARY KEY (account, id);
ALTER TABLE bling_sellers         DROP CONSTRAINT IF EXISTS bling_sellers_pkey;
ALTER TABLE bling_sellers         ADD PRIMARY KEY (account, id);
ALTER TABLE bling_payment_methods DROP CONSTRAINT IF EXISTS bling_payment_methods_pkey;
ALTER TABLE bling_payment_methods ADD PRIMARY KEY (account, id);
ALTER TABLE bling_sync_state      DROP CONSTRAINT IF EXISTS bling_sync_state_pkey;
ALTER TABLE bling_sync_state      ADD PRIMARY KEY (account, resource);
ALTER TABLE bling_webhook_events  DROP CONSTRAINT IF EXISTS bling_webhook_events_pkey;
ALTER TABLE bling_webhook_events  ADD PRIMARY KEY (account, event_id);
ALTER TABLE bling_seller_map      DROP CONSTRAINT IF EXISTS bling_seller_map_pkey;
ALTER TABLE bling_seller_map      ADD PRIMARY KEY (user_email, account);

ALTER TABLE bling_seller_map
  ADD CONSTRAINT bling_seller_map_seller_fkey
  FOREIGN KEY (account, bling_seller_id) REFERENCES bling_sellers(account, id);

-- ===========================================================================
-- 2. Vinculo lead <-> contato, agora por conta
-- ===========================================================================
CREATE TABLE IF NOT EXISTS lead_bling_contacts (
  lead_id          uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  account          text NOT NULL,
  bling_contact_id bigint NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (lead_id, account)
);

-- Preserva a garantia estrutural da 20260818: um contato do ERP pertence a no
-- maximo um lead. Agora dentro da conta, porque o mesmo numero de ID existe nas
-- duas contas apontando para clientes diferentes.
CREATE UNIQUE INDEX IF NOT EXISTS lead_bling_contacts_account_contact_key
  ON lead_bling_contacts (account, bling_contact_id);

-- Backfill: esperado 1479 linhas (medido em 13/09/2026).
INSERT INTO lead_bling_contacts (lead_id, account, bling_contact_id)
SELECT id, 'default', bling_contact_id
  FROM leads
 WHERE bling_contact_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- leads.bling_contact_id NAO e derrubada aqui: o codigo antigo ainda a le durante
-- a janela de deploy. Cai numa migration posterior, apos estabilizacao.

ALTER TABLE lead_bling_contacts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS lead_bling_contacts_select ON lead_bling_contacts;
CREATE POLICY lead_bling_contacts_select ON lead_bling_contacts
  FOR SELECT TO authenticated, service_role USING (true);

-- ===========================================================================
-- 3. Vendas e orcamentos
-- ===========================================================================
ALTER TABLE sales  ADD COLUMN IF NOT EXISTS bling_account text;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS bling_account text;

-- Esperado: 1024 linhas (medido em 13/09/2026). Venda manual fica NULL.
UPDATE sales SET bling_account = 'default'
 WHERE bling_order_id IS NOT NULL AND bling_account IS NULL;

-- Indice NAO-PARCIAL, pela mesma razao documentada em 20260818: o parametro
-- on_conflict= do PostgREST emite so a lista de colunas, nunca o WHERE, entao um
-- indice parcial fica invisivel para a inferencia e o upsert morre em 42P10.
--
-- sales_bling_order_id_key e INDICE (nao constraint) — conferido em pg_indexes.
DROP INDEX IF EXISTS sales_bling_order_id_key;
DROP INDEX IF EXISTS sales_bling_order_key;
CREATE UNIQUE INDEX sales_bling_order_key ON sales (bling_account, bling_order_id);

-- quotes_bling_proposal_id_key e CONSTRAINT (nao indice) — conferido em
-- pg_constraint. Os dois terminam em _key e parecem iguais; nao sao.
ALTER TABLE quotes DROP CONSTRAINT IF EXISTS quotes_bling_proposal_id_key;
DROP INDEX IF EXISTS quotes_bling_proposal_key;
CREATE UNIQUE INDEX quotes_bling_proposal_key ON quotes (bling_account, bling_proposal_id);

-- PostgREST nao enxerga coluna nova sem recarregar o cache de schema.
NOTIFY pgrst, 'reload schema';
