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
--
-- Reexecutar e seguro: toda alteracao nomeada e precedida de DROP ... IF EXISTS,
-- tabelas e indices usam IF NOT EXISTS, e o backfill usa ON CONFLICT DO NOTHING.
--
-- SEM `BEGIN`/`COMMIT` explicito, de proposito. O editor SQL do Supabase ja manda
-- o arquivo inteiro como uma transacao implicita, entao uma falha no meio desfaz
-- tudo em vez de deixar o schema pela metade — e nenhuma instrucao aqui precisa
-- rodar fora de transacao (nao ha CONCURRENTLY nem VACUUM). Envolver a mao traria
-- um risco pior que o que resolveria: se o editor tratar mal o bloco, sobra uma
-- transacao ABERTA segurando ACCESS EXCLUSIVE em bling_products e sales, e isso
-- trava a aplicacao inteira ate alguem matar a sessao. As duas migrations Bling
-- anteriores (20260818, 20260825) tambem nao usam bloco explicito.
--
-- DEPOIS DESTE PONTO, A RECUPERACAO E SO PARA FRENTE. Nao existe down-migration.
-- Voltar a imagem antiga da aplicacao SEM reverter o schema nao conserta nada —
-- reproduz o mesmo 42P10 da janela de deploy (o on_conflict="id" do sync e o
-- on_conflict="bling_order_id" do pedido deixam de casar com as chaves
-- compostas), so que sem prazo para acabar: sync de catalogo e criacao de pedido
-- simplesmente param. E se a segunda conta ja tiver sido conectada e sincronizada,
-- o codigo antigo lendo bling_products/bling_contacts por `id` puro pode receber
-- MAIS DE UMA linha onde espera uma — falha pior e mais silenciosa que o 42P10.
-- Se precisar reverter de verdade, o schema tem que voltar junto, e esse script
-- nao existe pronto.

-- ===========================================================================
-- 0. Teto de espera por lock
-- ===========================================================================
-- Sem isto, um ACCESS EXCLUSIVE que encontre QUALQUER sessao segurando lock em
-- `sales` ou `leads` espera para sempre — e como o Postgres concede locks
-- conflitantes em ordem de fila, toda query que chegar depois enfileira atras
-- dele. O resultado nao e "a migration demora": e /vendas e escrita de lead
-- paradas ate alguem achar e matar a sessao na mao. Conferido em 14/09/2026:
-- nenhum role relevante (postgres, service_role, supabase_admin) tem
-- lock_timeout nem statement_timeout configurado.
--
-- LOCAL, e nao SET puro, por causa do pool de conexoes do Supabase: um SET de
-- sessao sobreviveria a esta execucao e imporia o teto de 5s a queries alheias
-- que reutilizassem a mesma conexao depois.
SET LOCAL lock_timeout = '5s';

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

-- O DROP antes do ADD nao e zelo: o Postgres nao tem ADD CONSTRAINT IF NOT
-- EXISTS, entao sem ele a segunda execucao deste arquivo morre em 42710. Os PKs
-- acima nao precisam do mesmo cuidado explicito porque o Postgres nomeia um
-- ADD PRIMARY KEY sem rotulo de <tabela>_pkey — exatamente o nome que o DROP da
-- linha anterior ja alcanca.
ALTER TABLE bling_seller_map DROP CONSTRAINT IF EXISTS bling_seller_map_seller_fkey;
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
