-- supabase/migrations/20260818_bling_integration.sql
--
-- Integracao CRM <-> Bling (spec 2026-08-18-crm-bling-integracao-design.md).
--
-- Tres blocos: (1) credenciais OAuth, (2) espelhos locais do Bling, (3) vinculos
-- e projecao de pedido em sales.
--
-- Decisao de design que esta migration materializa: o vinculo lead <-> contato
-- Bling e 1:1 e garantido por INDICE UNICO, nao por convencao no codigo. E a
-- defesa estrutural contra contato duplicado no ERP.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- f_unaccent ja existe (20260812_search_all_messages.sql); defensivo se rodar isolada.
CREATE OR REPLACE FUNCTION f_unaccent(text)
  RETURNS text
  LANGUAGE sql
  IMMUTABLE PARALLEL SAFE STRICT
  SET search_path = extensions, public, pg_catalog
AS $$ SELECT unaccent('unaccent', $1) $$;

-- ===========================================================================
-- 1. Credenciais OAuth
-- ===========================================================================
-- Tokens ficam no Postgres (verdade duravel) e sao cacheados em Redis. O
-- incidente de FLUSHALL de 07/06/2026 e a razao: perder o refresh_token obriga
-- a refazer o fluxo OAuth manualmente no navegador. Redis e cache, nao storage.
CREATE TABLE IF NOT EXISTS bling_credentials (
  id                 text PRIMARY KEY DEFAULT 'default',
  access_token       text,
  refresh_token      text,
  access_expires_at  timestamptz,
  refresh_expires_at timestamptz,
  scope              text,
  updated_at         timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE bling_credentials ENABLE ROW LEVEL SECURITY;
-- Sem policy para authenticated: contem segredo. Somente service_role (que ignora RLS).

-- ===========================================================================
-- 2. Espelhos locais
-- ===========================================================================
CREATE TABLE IF NOT EXISTS bling_products (
  id              bigint PRIMARY KEY,
  codigo          text,
  nome            text NOT NULL,
  preco           numeric(12,2),
  unidade         text,
  tipo            text,
  formato         text,
  situacao        text,
  id_produto_pai  bigint,
  saldo_virtual   numeric(14,3),
  imagem_url      text,
  synced_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS bling_products_nome_trgm
  ON bling_products USING gin (f_unaccent(lower(nome)) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS bling_products_codigo_idx   ON bling_products (codigo);
CREATE INDEX IF NOT EXISTS bling_products_situacao_idx ON bling_products (situacao);

-- telefone_e164/celular_e164 sao gravados JA normalizados por
-- app.leads.service.normalize_phone — a mesma funcao que normaliza leads.phone.
-- E isso que faz os dois lados casarem, em vez de depender do texto livre que o
-- Bling guarda ("(51) 99269-6163").
CREATE TABLE IF NOT EXISTS bling_contacts (
  id                 bigint PRIMARY KEY,
  nome               text NOT NULL,
  fantasia           text,
  tipo               text,
  doc_digits         text,
  telefone_e164      text,
  celular_e164       text,
  email              text,
  situacao           text,
  endereco           jsonb,
  vendedor_id        bigint,
  condicao_pagamento text,
  synced_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS bling_contacts_doc_idx
  ON bling_contacts (doc_digits) WHERE doc_digits IS NOT NULL;
CREATE INDEX IF NOT EXISTS bling_contacts_telefone_idx
  ON bling_contacts (telefone_e164) WHERE telefone_e164 IS NOT NULL;
CREATE INDEX IF NOT EXISTS bling_contacts_celular_idx
  ON bling_contacts (celular_e164) WHERE celular_e164 IS NOT NULL;
CREATE INDEX IF NOT EXISTS bling_contacts_email_idx
  ON bling_contacts (lower(email)) WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS bling_payment_methods (
  id             bigint PRIMARY KEY,
  descricao      text NOT NULL,
  tipo_pagamento integer,
  situacao       integer,
  padrao         integer,
  finalidade     integer,
  synced_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bling_sellers (
  id        bigint PRIMARY KEY,
  nome      text NOT NULL,
  situacao  text,
  synced_at timestamptz NOT NULL DEFAULT now()
);

-- sales.sold_by guarda o e-mail do usuario do CRM; o Bling identifica vendedor
-- por id numerico. Sem vinculo, o pedido vai sem vendedor (nao bloqueia a venda).
CREATE TABLE IF NOT EXISTS bling_seller_map (
  user_email      text PRIMARY KEY,
  bling_seller_id bigint NOT NULL REFERENCES bling_sellers(id),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bling_sync_state (
  resource     text PRIMARY KEY,
  last_sync_at timestamptz,
  last_cursor  text,
  updated_at   timestamptz NOT NULL DEFAULT now()
);

-- ===========================================================================
-- 3. Vinculos e projecao
-- ===========================================================================
ALTER TABLE leads ADD COLUMN IF NOT EXISTS bling_contact_id bigint;
CREATE UNIQUE INDEX IF NOT EXISTS leads_bling_contact_id_key
  ON leads (bling_contact_id) WHERE bling_contact_id IS NOT NULL;

-- Seed: os 1.208 leads da reativacao (aplicados em 17/08/2026) ja carregam o ID
-- do contato do Bling em metadata. Vinculo de graca, sem ambiguidade.
-- length <= 18 blinda o CAST contra overflow de bigint (max 19 digitos): sem
-- o limite, um valor sujo com 20+ digitos passa no regex, estoura o CAST e
-- aborta a migration inteira (o runner executa o arquivo como uma query so).
UPDATE leads
   SET bling_contact_id = (metadata->>'id_bling')::bigint
 WHERE bling_contact_id IS NULL
   AND metadata->>'id_bling' ~ '^[0-9]+$'
   AND length(metadata->>'id_bling') <= 18;

ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_order_id      bigint;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_order_number  integer;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_situacao_id   integer;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_situacao_nome text;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_event_date    timestamptz;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS origin              text NOT NULL DEFAULT 'crm';
ALTER TABLE sales ADD COLUMN IF NOT EXISTS status              text NOT NULL DEFAULT 'registrada';
ALTER TABLE sales ADD COLUMN IF NOT EXISTS payment_method_id   bigint;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS payment_terms       text;

-- Indice UNICO NAO-PARCIAL, de proposito. A versao original tinha
-- `WHERE bling_order_id IS NOT NULL` e quebrava TODO upsert de pedido em
-- producao com SQLSTATE 42P10 ("no unique or exclusion constraint matching the
-- ON CONFLICT specification"): o Postgres so infere um indice PARCIAL se o
-- mesmo predicado for repetido no ON CONFLICT, e o parametro `on_conflict=` do
-- PostgREST (usado por `_upsert_sale` em orders.py) emite apenas a lista de
-- colunas, nunca o WHERE. Sem o predicado o indice parcial e invisivel para a
-- inferencia e o pedido nunca chega em `sales`.
-- O predicado tambem nao agregava nada: no Postgres NULLs nunca conflitam entre
-- si num indice unico, entao as vendas legadas sem `bling_order_id` convivem
-- igual nas duas versoes. A unica diferenca real era quebrar o ON CONFLICT.
-- Os dubles do Supabase nos testes nao pegam isso — e inferencia do Postgres de
-- verdade, so aparece contra o banco real.
--
-- O DROP e obrigatorio: um ambiente que ja tenha a versao PARCIAL do indice
-- passaria batido pelo `IF NOT EXISTS` (o nome existe) e continuaria quebrado.
DROP INDEX IF EXISTS sales_bling_order_id_key;
CREATE UNIQUE INDEX sales_bling_order_id_key
  ON sales (bling_order_id);

-- Vendas que ja existiam antes da integracao nao sao tocadas por nenhuma rotina.
-- Roda uma vez, antes de qualquer venda nova: nao pega nada criado pela integracao.
UPDATE sales SET origin = 'manual' WHERE bling_order_id IS NULL;

CREATE TABLE IF NOT EXISTS sale_items (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sale_id             uuid NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  bling_product_id    bigint,
  codigo              text,
  descricao           text NOT NULL,
  quantidade          numeric(14,3) NOT NULL,
  valor_unitario      numeric(12,2) NOT NULL,
  desconto_percentual numeric(6,3) NOT NULL DEFAULT 0,
  total               numeric(12,2) NOT NULL,
  ordem               integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sale_items_sale_id_idx ON sale_items (sale_id);

-- ===========================================================================
-- 4. Idempotencia de webhook e outbox
-- ===========================================================================
-- O Bling nao garante ordem de entrega e pode repetir o mesmo evento. event_id
-- como PK absorve a repeticao no INSERT; event_date resolve a ordem.
CREATE TABLE IF NOT EXISTS bling_webhook_events (
  event_id     text PRIMARY KEY,
  event        text NOT NULL,
  payload      jsonb NOT NULL,
  event_date   timestamptz,
  status       text NOT NULL DEFAULT 'pending',
  attempts     integer NOT NULL DEFAULT 0,
  last_error   text,
  received_at  timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz
);
CREATE INDEX IF NOT EXISTS bling_webhook_events_pending_idx
  ON bling_webhook_events (received_at) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS bling_jobs (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind       text NOT NULL,
  payload    jsonb NOT NULL,
  status     text NOT NULL DEFAULT 'pending',
  attempts   integer NOT NULL DEFAULT 0,
  last_error text,
  sale_id    uuid REFERENCES sales(id) ON DELETE SET NULL,
  run_after  timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS bling_jobs_pending_idx
  ON bling_jobs (run_after) WHERE status = 'pending';

-- ===========================================================================
-- 5. RLS
-- ===========================================================================
-- Padrao de 20260618_products_catalog.sql: RLS ligado + SELECT para authenticated.
-- Escrita fica so no service_role (backend), que ignora RLS por natureza.
ALTER TABLE bling_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE bling_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE bling_payment_methods ENABLE ROW LEVEL SECURITY;
ALTER TABLE bling_sellers ENABLE ROW LEVEL SECURITY;
ALTER TABLE bling_seller_map ENABLE ROW LEVEL SECURITY;
ALTER TABLE bling_sync_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE bling_webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE bling_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE sale_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bling_products_select        ON bling_products;
DROP POLICY IF EXISTS bling_contacts_select        ON bling_contacts;
DROP POLICY IF EXISTS bling_payment_methods_select ON bling_payment_methods;
DROP POLICY IF EXISTS bling_sellers_select         ON bling_sellers;
DROP POLICY IF EXISTS bling_seller_map_select      ON bling_seller_map;
DROP POLICY IF EXISTS sale_items_select            ON sale_items;

CREATE POLICY bling_products_select        ON bling_products        FOR SELECT TO authenticated, service_role USING (true);
CREATE POLICY bling_contacts_select        ON bling_contacts        FOR SELECT TO authenticated, service_role USING (true);
CREATE POLICY bling_payment_methods_select ON bling_payment_methods FOR SELECT TO authenticated, service_role USING (true);
CREATE POLICY bling_sellers_select         ON bling_sellers         FOR SELECT TO authenticated, service_role USING (true);
CREATE POLICY bling_seller_map_select      ON bling_seller_map      FOR SELECT TO authenticated, service_role USING (true);
CREATE POLICY sale_items_select            ON sale_items            FOR SELECT TO authenticated, service_role USING (true);
-- bling_jobs e bling_webhook_events: sem policy — so backend (service_role).

DROP TRIGGER IF EXISTS bling_jobs_set_updated_at ON bling_jobs;
CREATE TRIGGER bling_jobs_set_updated_at
  BEFORE UPDATE ON bling_jobs
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
