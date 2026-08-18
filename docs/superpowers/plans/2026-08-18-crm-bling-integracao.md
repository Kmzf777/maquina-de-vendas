# Integração CRM ↔ Bling — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O vendedor registra a venda uma vez no CRM e o pedido de venda nasce no Bling; o ERP volta a ser a fonte da verdade do faturamento via webhook `order`.

**Architecture:** Um módulo `backend/app/bling/` é o dono único da conta Bling — segura o JWT, o token-bucket de 3 req/s (limite é por conta, não por endpoint), os jobs de sync e o receiver de webhook. O Next.js só monta a UI e chama o backend. Criação de pedido é síncrona com fallback para uma fila (`bling_jobs`) quando o Bling está indisponível. Identidade de cliente é resolvida por CPF/CNPJ (nunca por telefone), com o vínculo persistido em `leads.bling_contact_id` sob índice UNIQUE.

**Tech Stack:** Python 3 / FastAPI / httpx / redis.asyncio / Supabase (Postgres) / pytest (`asyncio_mode=auto`); Next.js App Router / TypeScript / vitest.

**Spec:** `docs/superpowers/specs/2026-08-18-crm-bling-integracao-design.md`

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `supabase/migrations/20260818_bling_integration.sql` | Todas as tabelas novas + colunas em `leads`/`sales` + seed do `bling_contact_id` |
| `backend/app/bling/config.py` | Leitura de env (`os.getenv`, padrão do `google_ads.py`) e flags |
| `backend/app/bling/errors.py` | Hierarquia de exceções (`BlingError` e filhas) |
| `backend/app/bling/ratelimit.py` | Token-bucket Redis (3 req/s + teto diário), fail-closed |
| `backend/app/bling/auth.py` | OAuth: authorize URL, troca de code, refresh serializado, storage |
| `backend/app/bling/client.py` | `BlingClient`: httpx + auth + rate limit + retry + mapeamento de erro |
| `backend/app/bling/products.py` | Sync do catálogo (completo e incremental) |
| `backend/app/bling/sync.py` | Sync de contatos, formas de pagamento e vendedores; tick do worker |
| `backend/app/bling/contacts.py` | Resolução de identidade, criação de contato, `ensure_lead` |
| `backend/app/bling/orders.py` | Montagem do payload, geração de parcelas, criação, projeção em `sales` |
| `backend/app/bling/jobs.py` | Outbox: enfileirar e drenar `bling_jobs` |
| `backend/app/bling/webhook_router.py` | `POST /webhook/bling` — valida HMAC, persiste, devolve 200 em <5s |
| `backend/app/bling/webhook_processor.py` | Processamento assíncrono dos eventos; tick do worker |
| `backend/app/bling/backfill.py` | Importação dos 12 meses, retomável por janelas |
| `backend/app/bling/router.py` | `/api/bling/*` (oauth, status, products, payment-methods, orders, sync, backfill) |
| `frontend/src/app/api/bling/**` | Proxies do Next para o backend |
| `frontend/src/lib/bling.ts` | Parcelas e totais no cliente (espelha `orders.py`) |
| `frontend/src/lib/bling-order-state.ts` | Lógica do formulário de pedido (linhas, validação, payload) |
| `frontend/src/lib/documento.ts` | Validação de CPF/CNPJ no cliente |
| `frontend/src/lib/sale-display.ts` | Status e deep-link do pedido para a tabela |
| `frontend/src/components/sales/bling-order-form.tsx` | Renderização das linhas de item e do pagamento |
| `frontend/src/components/sales/bling-contact-resolver.tsx` | Fluxo do 409: escolher candidato ou cadastrar |
| `frontend/src/components/sales/sale-create-modal.tsx` | Liga o modo Bling ao modal existente |
| `frontend/src/components/config/bling-settings.tsx` | Conexão OAuth, sync, mapeamento de vendedores |

**Ordem obrigatória:** Tasks 1–5 são fundação e bloqueiam todo o resto. Tasks 6–7 (espelhos) bloqueiam 8–9. Task 12–13 (webhook) dependem de 8. Frontend (15–17) depende de 11.

---

## Fase 1 — Fundação

### Task 1: Migration do schema

**Files:**
- Create: `supabase/migrations/20260818_bling_integration.sql`
- Test: `backend/tests/test_bling_migration.py`

- [ ] **Step 1: Escrever o teste que falha**

O repo já testa migrations por leitura do SQL (`backend/tests/test_apply_migrations.py`). Siga o mesmo caminho: o teste lê o arquivo e afirma o que ele precisa conter.

```python
# backend/tests/test_bling_migration.py
import pathlib

SQL = pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20260818_bling_integration.sql"


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def test_migration_exists():
    assert SQL.exists(), "migration 20260818_bling_integration.sql nao encontrada"


def test_cria_todas_as_tabelas():
    sql = _sql().lower()
    for tabela in (
        "bling_credentials", "bling_products", "bling_contacts",
        "bling_payment_methods", "bling_sellers", "bling_sync_state",
        "bling_seller_map", "bling_webhook_events", "bling_jobs", "sale_items",
    ):
        assert f"create table if not exists {tabela}" in sql, tabela


def test_vinculo_lead_contato_e_unico():
    sql = _sql().lower()
    assert "alter table leads add column if not exists bling_contact_id bigint" in sql
    # UNIQUE parcial: e a garantia estrutural de 1:1 lead <-> contato Bling
    assert "create unique index" in sql and "leads_bling_contact_id_key" in sql
    assert "where bling_contact_id is not null" in sql


def test_pedido_bling_e_unico_em_sales():
    sql = _sql().lower()
    assert "sales_bling_order_id_key" in sql
    assert "unique index" in sql


def test_seed_do_id_bling_vem_do_metadata():
    sql = _sql().lower()
    # os 1.208 leads da reativacao ja carregam metadata->>'id_bling'
    assert "metadata->>'id_bling'" in sql
    assert "~ '^[0-9]+$'" in sql


def test_vendas_legadas_viram_origin_manual():
    sql = _sql().lower()
    assert "update sales set origin = 'manual' where bling_order_id is null" in sql


def test_rls_ligado_em_todas_as_tabelas_novas():
    sql = _sql().lower()
    for tabela in (
        "bling_products", "bling_contacts", "bling_payment_methods",
        "bling_sellers", "bling_credentials", "bling_jobs",
        "bling_webhook_events", "sale_items",
    ):
        assert f"alter table {tabela} enable row level security" in sql, tabela


def test_credentials_nao_expoe_leitura_para_authenticated():
    """bling_credentials guarda refresh_token — so service_role le."""
    sql = _sql()
    bloco = sql[sql.index("bling_credentials"):]
    bloco = bloco[:bloco.index("bling_products")] if "bling_products" in bloco else bloco
    assert "TO authenticated" not in bloco
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_migration.py -v`
Expected: FAIL — `migration 20260818_bling_integration.sql nao encontrada`

- [ ] **Step 3: Escrever a migration**

```sql
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
UPDATE leads
   SET bling_contact_id = (metadata->>'id_bling')::bigint
 WHERE bling_contact_id IS NULL
   AND metadata->>'id_bling' ~ '^[0-9]+$';

ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_order_id      bigint;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_order_number  integer;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_situacao_id   integer;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_situacao_nome text;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_event_date    timestamptz;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS origin              text NOT NULL DEFAULT 'crm';
ALTER TABLE sales ADD COLUMN IF NOT EXISTS status              text NOT NULL DEFAULT 'registrada';
ALTER TABLE sales ADD COLUMN IF NOT EXISTS payment_method_id   bigint;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS payment_terms       text;

CREATE UNIQUE INDEX IF NOT EXISTS sales_bling_order_id_key
  ON sales (bling_order_id) WHERE bling_order_id IS NOT NULL;

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
-- Espaco unico entre as palavras de proposito: o teste desta task faz match de
-- substring exata ("alter table X enable row level security"), entao alinhar
-- por colunas quebraria o teste.
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
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_migration.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260818_bling_integration.sql backend/tests/test_bling_migration.py
git commit -m "feat(bling): schema da integracao (espelhos, vinculos, outbox)"
```

---

### Task 2: Config e erros

**Files:**
- Create: `backend/app/bling/__init__.py`, `backend/app/bling/config.py`, `backend/app/bling/errors.py`
- Test: `backend/tests/test_bling_config.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_bling_config.py
import app.bling.config as cfg
from app.bling.errors import (
    BlingError, BlingAuthError, BlingRateLimitError,
    BlingServerError, BlingValidationError, BlingNotConfigured,
)


def test_desabilitado_por_default(monkeypatch):
    monkeypatch.delenv("BLING_ENABLED", raising=False)
    assert cfg.enabled() is False


def test_habilita_por_env(monkeypatch):
    monkeypatch.setenv("BLING_ENABLED", "true")
    assert cfg.enabled() is True


def test_credenciais_lidas_do_env(monkeypatch):
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    assert cfg.client_id() == "cid"
    assert cfg.client_secret() == "csec"


def test_require_credentials_levanta_quando_falta(monkeypatch):
    monkeypatch.delenv("BLING_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLING_CLIENT_SECRET", raising=False)
    try:
        cfg.require_credentials()
    except BlingNotConfigured:
        return
    raise AssertionError("deveria levantar BlingNotConfigured")


def test_ids_opcionais_viram_none_quando_vazios(monkeypatch):
    monkeypatch.setenv("BLING_STORE_ID", "")
    monkeypatch.setenv("BLING_ORDER_SITUACAO_ID", "  ")
    assert cfg.store_id() is None
    assert cfg.order_situacao_id() is None


def test_ids_opcionais_viram_int(monkeypatch):
    monkeypatch.setenv("BLING_STORE_ID", "203455519")
    assert cfg.store_id() == 203455519


def test_base_url_e_a_v3():
    assert cfg.API_BASE == "https://api.bling.com.br/Api/v3"


def test_hierarquia_de_erros():
    for klass in (BlingAuthError, BlingRateLimitError, BlingServerError,
                  BlingValidationError, BlingNotConfigured):
        assert issubclass(klass, BlingError)
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/__init__.py
"""Integracao com o ERP Bling (API v3).

Este pacote e o DONO UNICO da conta Bling no sistema. O limite de requisicoes do
Bling e por CONTA (3 req/s, 120.000/dia), nao por endpoint nem por processo — se
o Next e o worker chamassem a API por conta propria, um estouraria o orcamento do
outro e o IP seria bloqueado. Toda chamada passa por `client.BlingClient`.
"""
```

```python
# backend/app/bling/errors.py
"""Hierarquia de erros da integracao Bling.

A distincao que importa no fluxo de venda: erro TRANSITORIO (rate limit, 5xx,
timeout) vai para a fila e e retentado; erro de VALIDACAO nao vai — repetir o
mesmo payload invalido nunca conserta.
"""


class BlingError(Exception):
    """Base de todos os erros da integracao."""


class BlingNotConfigured(BlingError):
    """Faltam BLING_CLIENT_ID / BLING_CLIENT_SECRET, ou nunca houve autorizacao."""


class BlingAuthError(BlingError):
    """401 apos tentativa de renovacao — precisa refazer o fluxo OAuth."""


class BlingRateLimitError(BlingError):
    """429 do Bling, ou o token-bucket local recusou. TRANSITORIO."""


class BlingDailyCapError(BlingRateLimitError):
    """Teto diario local atingido. TRANSITORIO (destrava na virada do dia)."""


class BlingServerError(BlingError):
    """5xx ou timeout. TRANSITORIO."""


class BlingValidationError(BlingError):
    """4xx de validacao. NAO retentar.

    Carrega os campos que o Bling devolve em `error` para repassar ao vendedor.
    """

    def __init__(self, message: str, *, type_: str = "", description: str = "",
                 status: int = 400, payload: dict | None = None):
        super().__init__(message)
        self.type = type_
        self.description = description
        self.status = status
        self.payload = payload or {}


TRANSIENT = (BlingRateLimitError, BlingServerError)
```

```python
# backend/app/bling/config.py
"""Configuracao da integracao Bling, lida de os.getenv.

Segue o padrao de `app/campaigns/google_ads.py`: env cru via os.getenv em vez de
campo no Settings do pydantic. Motivo pratico — o Settings tem `extra: allow`, que
aceita a variavel no .env mas NAO cria o atributo, entao `settings.bling_client_id`
levantaria AttributeError.
"""
import os

# A v3 e a unica com OAuth/JWT. A v2 esta descontinuada.
API_BASE = "https://api.bling.com.br/Api/v3"
AUTHORIZE_URL = "https://bling.com.br/Api/v3/oauth/authorize"
TOKEN_URL = "https://api.bling.com.br/Api/v3/oauth/token"

# Limites publicados pelo Bling (developer.bling.com.br/limites), por CONTA.
REQUESTS_PER_SECOND = 3
DAILY_LIMIT = 120_000
# Margem de 8% sobre o teto diario: preferimos recusar localmente (e enfileirar)
# a levar 429 do Bling, porque erro em rajada tambem conta para bloqueio de IP
# (300 erros em 10s => 10 min de bloqueio).
DAILY_SOFT_CAP = 110_000


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _env_int(name: str) -> int | None:
    raw = _env(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def enabled() -> bool:
    return _env("BLING_ENABLED").lower() in ("1", "true", "yes", "on")


def client_id() -> str:
    return _env("BLING_CLIENT_ID")


def client_secret() -> str:
    return _env("BLING_CLIENT_SECRET")


def redirect_uri() -> str:
    return _env("BLING_REDIRECT_URI")


def store_id() -> int | None:
    return _env_int("BLING_STORE_ID")


def order_situacao_id() -> int | None:
    return _env_int("BLING_ORDER_SITUACAO_ID")


def lead_default_stage() -> str:
    return _env("BLING_LEAD_DEFAULT_STAGE") or "novo"


def require_credentials() -> tuple[str, str]:
    """Devolve (client_id, client_secret) ou levanta BlingNotConfigured."""
    from app.bling.errors import BlingNotConfigured

    cid, csec = client_id(), client_secret()
    if not cid or not csec:
        raise BlingNotConfigured(
            "BLING_CLIENT_ID e BLING_CLIENT_SECRET precisam estar configurados"
        )
    return cid, csec
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_config.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/__init__.py backend/app/bling/config.py backend/app/bling/errors.py backend/tests/test_bling_config.py
git commit -m "feat(bling): config e hierarquia de erros"
```

---

### Task 3: Rate limiter (token-bucket Redis)

> **Superado em parte pelo commit `e8dc01f7`.** A revisão de qualidade apontou que
> os dois `_incr` sequenciais custam dois round-trips no caminho quente do modal de
> venda — com um Redis lento-mas-vivo, ~3-4s sem nunca cair no fail-closed. O
> módulo em produção passou a fazer os dois contadores num **único script Lua**
> (`{status, valor}`: 0 ok, 1 estourou o segundo, 2 estourou o dia) e ganhou
> cooldown de 30s após falha de Redis, no padrão de `buffer/lead_lock.py`. Isso
> também eliminou por construção o modo de falha "Redis morreu entre os dois
> contadores". O texto abaixo é o registro do que foi pedido originalmente;
> `backend/app/bling/ratelimit.py` é a verdade.

**Files:**
- Create: `backend/app/bling/ratelimit.py`
- Test: `backend/tests/test_bling_ratelimit.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_bling_ratelimit.py
import asyncio

import pytest

import app.bling.ratelimit as rl
from app.bling.errors import BlingDailyCapError, BlingRateLimitError


class FakeRedis:
    """Redis em memoria com a semantica de INCR/EXPIRE que o script Lua usa."""

    def __init__(self, fail: bool = False):
        self.counts: dict[str, int] = {}
        self.fail = fail

    async def eval(self, script, numkeys, key, *args):
        if self.fail:
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Nao dorme de verdade — so registra que dormiu."""
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(rl.asyncio, "sleep", fake_sleep)
    return slept


def test_tres_chamadas_no_mesmo_segundo_passam(monkeypatch, _no_sleep):
    fake = FakeRedis()
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    async def run():
        for _ in range(3):
            await rl.acquire()

    asyncio.run(run())
    assert _no_sleep == [], "nao deveria esperar dentro do orcamento de 3 req/s"


def test_quarta_chamada_no_mesmo_segundo_espera(monkeypatch, _no_sleep):
    fake = FakeRedis()
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    # Primeiro o relogio fica parado (forca o estouro), depois avanca 1s.
    ticks = iter([1_000_000.0] * 5 + [1_000_001.0] * 5)
    monkeypatch.setattr(rl.time, "time", lambda: next(ticks))

    async def run():
        for _ in range(4):
            await rl.acquire()

    asyncio.run(run())
    assert _no_sleep, "a 4a chamada no mesmo segundo tinha que esperar o proximo segundo"


def test_teto_diario_recusa(monkeypatch, _no_sleep):
    fake = FakeRedis()
    fake.counts[rl._day_key()] = rl.config.DAILY_SOFT_CAP
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    with pytest.raises(BlingDailyCapError):
        asyncio.run(rl.acquire())


def test_redis_fora_do_ar_e_fail_closed(monkeypatch, _no_sleep):
    """Ao contrario do lead_lock (fail-open), aqui seguir sem contagem arrisca
    bloqueio de IP por tempo indeterminado. Melhor recusar e enfileirar."""
    monkeypatch.setattr(rl, "_get_client", lambda: FakeRedis(fail=True))
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    with pytest.raises(BlingRateLimitError):
        asyncio.run(rl.acquire())


class FakeRedisFalhaNaSegunda:
    """Deixa o contador por segundo passar e derruba o diario.

    Sem este fake, o `except` do contador diario fica SEM COBERTURA: o
    FakeRedis(fail=True) ja explode na primeira chamada `eval` (a do contador
    por segundo) e a execucao nunca chega la. Confirmado por teste de mutacao —
    trocar o `raise` daquele except por `return` mantinha a suite verde.
    """

    def __init__(self):
        self.chamadas = 0

    async def eval(self, script, numkeys, key, *args):
        self.chamadas += 1
        if self.chamadas == 1:
            return 1  # contador por segundo: dentro do orcamento
        raise ConnectionError("redis caiu entre os dois contadores")


def test_falha_no_contador_diario_tambem_e_fail_closed(monkeypatch, _no_sleep):
    """Protege o caminho em que o Redis cai NO MEIO dos dois contadores."""
    # Instancia UNICA, ligada fora do lambda. `acquire()` chama _get_client()
    # uma vez por contador; um `lambda: FakeRedisFalhaNaSegunda()` construiria
    # um fake novo a cada chamada, `chamadas` voltaria a zero e o teste nunca
    # alcancaria o caminho que pretende testar (passaria contra codigo quebrado).
    fake = FakeRedisFalhaNaSegunda()
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    with pytest.raises(BlingRateLimitError):
        asyncio.run(rl.acquire())
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_ratelimit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.ratelimit'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/ratelimit.py
"""Token-bucket distribuido para a conta Bling (3 req/s, 120.000/dia).

O limite do Bling e por CONTA, entao a contagem precisa ser central — Redis, nao
memoria de processo. Um contador por segundo (chave `bling:rl:{unix_second}`) se
auto-particiona: a chave do segundo seguinte comeca do zero sem limpeza.

FAIL-CLOSED por design. O `buffer/lead_lock.py` e fail-open porque bloquear o
atendimento e pior que duplicar um turno; aqui e o oposto — seguir sem contagem
arrisca 600 req/10s e bloqueio de IP por tempo INDETERMINADO. Chamada recusada
vai para a fila (`bling_jobs`) e e retentada.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.bling import config
from app.bling.errors import BlingDailyCapError, BlingRateLimitError
from app.config import settings

logger = logging.getLogger(__name__)

# INCR + EXPIRE atomico. EXPIRE 2s (nao 1s) da folga na virada do segundo.
_INCR_LUA = (
    "local c = redis.call('INCR', KEYS[1]) "
    "if c == 1 then redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1])) end "
    "return c"
)

_SECOND_TTL = 2
_DAY_TTL = 172_800  # 48h — cobre fuso e virada sem limpeza manual
# Quantas vezes esperamos o proximo segundo antes de desistir. 5s de espera ja e
# muito para o modal de venda; alem disso, enfileirar e melhor que segurar o request.
_MAX_WAIT_ROUNDS = 5

_client: aioredis.Redis | None = None


def _get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _client


def _second_key(now: float) -> str:
    return f"bling:rl:{int(now)}"


def _day_key() -> str:
    return "bling:rl:day:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _incr(key: str, ttl: int) -> int:
    return int(await _get_client().eval(_INCR_LUA, 1, key, str(ttl)))


async def acquire() -> None:
    """Reserva uma requisicao. Espera o proximo segundo se preciso.

    Levanta BlingDailyCapError (teto diario), BlingRateLimitError (Redis fora ou
    espera longa demais). Ambos sao TRANSIENT — o chamador enfileira.
    """
    for _ in range(_MAX_WAIT_ROUNDS):
        now = time.time()
        try:
            count = await _incr(_second_key(now), _SECOND_TTL)
        except Exception as exc:  # noqa: BLE001 — qualquer falha de Redis e fail-closed
            logger.warning("[BLING RL] Redis indisponivel, recusando chamada: %s", exc)
            raise BlingRateLimitError("rate limiter indisponivel (Redis)") from exc

        if count > config.REQUESTS_PER_SECOND:
            # Ja incrementamos, mas a chave morre no fim do segundo — a proxima
            # janela comeca limpa. Dorme o que falta do segundo corrente.
            await asyncio.sleep(max(0.01, 1.0 - (time.time() - int(now))))
            continue

        try:
            day = await _incr(_day_key(), _DAY_TTL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BLING RL] Redis indisponivel no contador diario: %s", exc)
            raise BlingRateLimitError("rate limiter indisponivel (Redis)") from exc

        if day > config.DAILY_SOFT_CAP:
            raise BlingDailyCapError(
                f"teto diario local atingido ({day}/{config.DAILY_SOFT_CAP})"
            )
        return

    raise BlingRateLimitError("orcamento de 3 req/s saturado apos varias tentativas")
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_ratelimit.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/ratelimit.py backend/tests/test_bling_ratelimit.py
git commit -m "feat(bling): token-bucket Redis 3 req/s fail-closed"
```

---

### Task 4: OAuth (authorize, troca de code, refresh serializado)

**Files:**
- Create: `backend/app/bling/auth.py`
- Test: `backend/tests/test_bling_auth.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_bling_auth.py
import asyncio
import base64
from datetime import datetime, timezone

import pytest

import app.bling.auth as auth
from app.bling.errors import BlingNotConfigured


class FakeTable:
    def __init__(self, store):
        self.store = store

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def upsert(self, payload, on_conflict=None):
        self.store["upserted"] = payload
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row")
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, _name):
        return FakeTable(self.store)


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    monkeypatch.setenv("BLING_REDIRECT_URI", "https://api.exemplo.com/api/bling/oauth/callback")


def test_authorize_url_tem_response_type_client_id_e_state(creds):
    url = auth.authorize_url("abc123")
    assert url.startswith("https://bling.com.br/Api/v3/oauth/authorize?")
    assert "response_type=code" in url
    assert "client_id=cid" in url
    assert "state=abc123" in url


def test_authorize_url_exige_credenciais(monkeypatch):
    monkeypatch.delenv("BLING_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLING_CLIENT_SECRET", raising=False)
    with pytest.raises(BlingNotConfigured):
        auth.authorize_url("abc")


def test_basic_header_e_base64_de_id_dois_pontos_secret(creds):
    header = auth._basic_auth_header()
    esperado = base64.b64encode(b"cid:csec").decode()
    assert header == f"Basic {esperado}"


def test_troca_de_code_manda_enable_jwt_e_persiste(creds, monkeypatch):
    """enable-jwt: 1 e OBRIGATORIO — o token opaco esta descontinuado no Bling."""
    capturado = {}
    store = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "access_token": "jwt-aaa", "refresh_token": "ref-bbb",
                "expires_in": 21600, "token_type": "Bearer", "scope": "1 2 3",
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, data=None):
            capturado["url"] = url
            capturado["headers"] = headers
            capturado["data"] = data
            return FakeResponse()

    async def noop_cache(*_a, **_k):
        return None

    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr(auth, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(auth, "_cache_set", noop_cache)

    out = asyncio.run(auth.exchange_code("code-xyz"))

    assert capturado["headers"]["enable-jwt"] == "1"
    assert capturado["headers"]["Authorization"].startswith("Basic ")
    assert capturado["data"]["grant_type"] == "authorization_code"
    assert capturado["data"]["code"] == "code-xyz"
    assert out["access_token"] == "jwt-aaa"
    assert store["upserted"]["refresh_token"] == "ref-bbb"
    assert store["upserted"]["access_expires_at"] > datetime.now(timezone.utc).isoformat()


def test_refresh_usa_grant_type_refresh_token(creds, monkeypatch):
    capturado = {}
    store = {"row": {"refresh_token": "ref-antigo"}}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "jwt-novo", "refresh_token": "ref-novo",
                    "expires_in": 21600, "scope": ""}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, data=None):
            capturado["data"] = data
            capturado["headers"] = headers
            return FakeResponse()

    async def noop_cache(*_a, **_k):
        return None

    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr(auth, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(auth, "_cache_set", noop_cache)

    asyncio.run(auth._refresh_now("ref-antigo"))

    assert capturado["data"]["grant_type"] == "refresh_token"
    assert capturado["data"]["refresh_token"] == "ref-antigo"
    assert capturado["headers"]["enable-jwt"] == "1"


def test_refresh_e_serializado_por_lock(creds, monkeypatch):
    """20 chamadas a /oauth/token em 60s bloqueiam o IP por 60 MINUTOS.
    Duas corrotinas renovando ao mesmo tempo nao podem virar duas chamadas."""
    chamadas = []
    estado = {"token": None}

    async def fake_refresh_now(token):
        chamadas.append(token)
        await fake_cache_set("jwt-novo", 60)
        return "jwt-novo"

    # O fake precisa de exclusao mutua DE VERDADE. Um _Ctx cujo __aenter__ so
    # devolve True nao serializa nada: sob asyncio.gather as duas corrotinas
    # entram juntas, ambas releem o cache como None no unico ponto de suspensao
    # (o to_thread do _stored_refresh_token) e chamam _refresh_now duas vezes —
    # o teste falha contra codigo CORRETO. O lock real do Redis serializa porque
    # o `set(nx=True)` e o polling sao pontos de suspensao genuinos; o asyncio.Lock
    # abaixo reproduz essa semantica.
    trava = asyncio.Lock()

    async def fake_lock():
        class _Ctx:
            async def __aenter__(self):
                await trava.acquire()
                return True

            async def __aexit__(self, *a):
                trava.release()
                return False
        return _Ctx()

    async def fake_cache_get():
        return estado["token"]

    async def fake_cache_set(token, ttl):
        estado["token"] = token

    monkeypatch.setattr(auth, "_refresh_now", fake_refresh_now)
    monkeypatch.setattr(auth, "_stored_refresh_token", lambda: "ref-x")
    monkeypatch.setattr(auth, "_refresh_lock", fake_lock)
    monkeypatch.setattr(auth, "_cache_get", fake_cache_get)
    monkeypatch.setattr(auth, "_cache_set", fake_cache_set)

    async def run():
        return await asyncio.gather(auth.get_access_token(), auth.get_access_token())

    asyncio.run(run())
    assert len(chamadas) == 1, "o refresh tinha que acontecer uma unica vez"


def test_tokens_nunca_aparecem_no_log(creds, caplog, monkeypatch):
    store = {}

    async def noop_cache(*_a, **_k):
        return None

    monkeypatch.setattr(auth, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(auth, "_cache_set", noop_cache)
    with caplog.at_level("DEBUG"):
        asyncio.run(auth._persist({
            "access_token": "SEGREDO-AAA", "refresh_token": "SEGREDO-BBB",
            "expires_in": 21600, "scope": "",
        }))
    assert "SEGREDO-AAA" not in caplog.text
    assert "SEGREDO-BBB" not in caplog.text
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.auth'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/auth.py
"""OAuth 2.0 do Bling: authorization_code, refresh e storage dos tokens.

Tres decisoes que este modulo materializa:

1. `enable-jwt: 1` em TODA chamada ao /oauth/token. O token opaco esta
   descontinuado; sem o header o Bling devolve o formato antigo, que vai parar
   de funcionar.
2. Refresh SERIALIZADO por lock Redis. O Bling bloqueia o IP por 60 MINUTOS
   apos 20 chamadas ao /oauth/token em 60s — refresh concorrente entre workers
   derruba a integracao inteira.
3. Tokens no Postgres, cache no Redis. O FLUSHALL de 07/06/2026 mostrou que
   Redis nao e storage: perder o refresh_token (30 dias de validade) obriga a
   refazer o fluxo OAuth manualmente no navegador.
"""
import asyncio
import base64
import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
import redis.asyncio as aioredis

from app.bling import config
from app.bling.errors import BlingAuthError, BlingNotConfigured
from app.config import settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_CACHE_KEY = "bling:access_token"
_LOCK_KEY = "lock:bling_token_refresh"
_STATE_PREFIX = "bling:oauth_state:"
_LOCK_TTL = 30
_STATE_TTL = 600
# Renova quando faltar menos que isso para expirar (access_token dura 6h).
_RENEW_MARGIN_SECONDS = 300

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _redis


def _basic_auth_header() -> str:
    cid, csec = config.require_credentials()
    return "Basic " + base64.b64encode(f"{cid}:{csec}".encode()).decode()


# --------------------------------------------------------------------------
# Fluxo de autorizacao
# --------------------------------------------------------------------------
async def new_state() -> str:
    """Gera e guarda o state (anti-CSRF). TTL de 10 min."""
    state = secrets.token_urlsafe(24)
    await _get_redis().setex(_STATE_PREFIX + state, _STATE_TTL, "1")
    return state


async def consume_state(state: str) -> bool:
    """Valida e queima o state. False se invalido ou ja usado."""
    if not state:
        return False
    return bool(await _get_redis().delete(_STATE_PREFIX + state))


def authorize_url(state: str) -> str:
    cid, _ = config.require_credentials()
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": cid,
        "state": state,
    })
    return f"{config.AUTHORIZE_URL}?{params}"


async def _token_request(data: dict) -> dict:
    headers = {
        "Authorization": _basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "1.0",
        "enable-jwt": "1",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(config.TOKEN_URL, headers=headers, data=data)
    if resp.status_code != 200:
        # Nunca logar o corpo: pode conter o code ou o refresh_token.
        logger.error("[BLING AUTH] /oauth/token devolveu %s", resp.status_code)
        raise BlingAuthError(f"/oauth/token devolveu {resp.status_code}")
    return resp.json()


async def exchange_code(code: str) -> dict:
    """Troca o authorization_code pelos tokens. O code expira em 1 MINUTO."""
    payload = await _token_request({"grant_type": "authorization_code", "code": code})
    await _persist(payload)
    return payload


async def _refresh_now(refresh_token: str) -> str:
    payload = await _token_request({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    })
    await _persist(payload)
    return payload["access_token"]


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
async def _persist(payload: dict) -> None:
    now = datetime.now(timezone.utc)
    expires_in = int(payload.get("expires_in") or 21600)
    row = {
        "id": "default",
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "access_expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
        "refresh_expires_at": (now + timedelta(days=30)).isoformat(),
        "scope": payload.get("scope") or "",
        "updated_at": now.isoformat(),
    }
    await asyncio.to_thread(
        lambda: get_supabase().table("bling_credentials")
        .upsert(row, on_conflict="id").execute()
    )
    logger.info("[BLING AUTH] tokens renovados; access expira em %ss", expires_in)
    await _cache_set(row["access_token"], max(60, expires_in - _RENEW_MARGIN_SECONDS))


def _stored_row() -> dict | None:
    res = (get_supabase().table("bling_credentials")
           .select("*").eq("id", "default").limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _stored_refresh_token() -> str | None:
    row = _stored_row() or {}
    return row.get("refresh_token")


async def _cache_get() -> str | None:
    try:
        return await _get_redis().get(_CACHE_KEY)
    except Exception:  # noqa: BLE001 — cache indisponivel cai para o Postgres
        return None


async def _cache_set(token: str | None, ttl: int) -> None:
    if not token:
        return
    try:
        await _get_redis().setex(_CACHE_KEY, ttl, token)
    except Exception:  # noqa: BLE001
        logger.warning("[BLING AUTH] nao foi possivel cachear o access_token")


async def _refresh_lock():
    """Lock de refresh. Devolve um context manager que entrega True se pegou."""
    client = _get_redis()
    token = secrets.token_hex(8)

    class _Ctx:
        owned = False

        async def __aenter__(self):
            for _ in range(60):  # ate ~30s esperando quem esta renovando
                if await client.set(_LOCK_KEY, token, nx=True, ex=_LOCK_TTL):
                    self.owned = True
                    return True
                await asyncio.sleep(0.5)
            return False

        async def __aexit__(self, *_a):
            if self.owned:
                # Libera so se a trava ainda e nossa (mesmo padrao do lead_lock).
                lua = ("if redis.call('get', KEYS[1]) == ARGV[1] then "
                       "return redis.call('del', KEYS[1]) else return 0 end")
                await client.eval(lua, 1, _LOCK_KEY, token)
            return False

    return _Ctx()


async def get_access_token() -> str:
    """Devolve um access_token valido, renovando se preciso (serializado)."""
    cached = await _cache_get()
    if cached:
        return cached

    ctx = await _refresh_lock()
    async with ctx as owned:
        # Quem esperou o lock rele o cache: o dono anterior ja renovou.
        cached = await _cache_get()
        if cached:
            return cached
        if not owned:
            raise BlingAuthError("nao foi possivel obter o lock de refresh")
        refresh_token = await asyncio.to_thread(_stored_refresh_token)
        if not refresh_token:
            raise BlingNotConfigured(
                "nenhum refresh_token salvo — refaca o fluxo OAuth em /config"
            )
        return await _refresh_now(refresh_token)


async def invalidate_cache() -> None:
    """Descarta o access_token cacheado (usado no retry de 401)."""
    try:
        await _get_redis().delete(_CACHE_KEY)
    except Exception:  # noqa: BLE001
        pass


async def status() -> dict:
    """Resumo para /api/bling/status: conectado, expiracoes, escopos."""
    row = await asyncio.to_thread(_stored_row) or {}
    return {
        # Fonte unica da regra "o que conta como configurado" (config.is_configured).
        # Repetir a condicao aqui faria os dois lados divergirem no dia em que a
        # integracao passar a exigir tambem o redirect_uri.
        "configured": config.is_configured(),
        "connected": bool(row.get("refresh_token")),
        "access_expires_at": row.get("access_expires_at"),
        "refresh_expires_at": row.get("refresh_expires_at"),
        "scope": row.get("scope"),
    }
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_auth.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/auth.py backend/tests/test_bling_auth.py
git commit -m "feat(bling): OAuth com JWT e refresh serializado por lock"
```

---

### Task 5: BlingClient

**Files:**
- Create: `backend/app/bling/client.py`
- Test: `backend/tests/test_bling_client.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_bling_client.py
import asyncio

import pytest

import app.bling.client as bc
from app.bling.errors import (
    BlingAuthError, BlingRateLimitError, BlingServerError, BlingValidationError,
)


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeHTTP:
    """Devolve respostas de uma fila e grava as requisicoes feitas."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.requests = []

    async def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        return self.respostas.pop(0)

    async def aclose(self):
        pass


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    async def noop(*_a, **_k):
        return None
    monkeypatch.setattr(bc.asyncio, "sleep", noop)
    monkeypatch.setattr(bc.ratelimit, "acquire", noop)


@pytest.fixture
def token(monkeypatch):
    async def fake_token():
        return "jwt-aaa"

    async def fake_invalidate():
        return None

    monkeypatch.setattr(bc.auth, "get_access_token", fake_token)
    monkeypatch.setattr(bc.auth, "invalidate_cache", fake_invalidate)


def test_headers_carregam_bearer_e_enable_jwt(token):
    http = FakeHTTP([FakeResponse(200, {"data": {"id": 1}})])
    client = bc.BlingClient(http=http)

    out = asyncio.run(client.get("/produtos"))

    assert out == {"data": {"id": 1}}
    headers = http.requests[0]["headers"]
    assert headers["Authorization"] == "Bearer jwt-aaa"
    assert headers["enable-jwt"] == "1"
    assert http.requests[0]["url"].endswith("/Api/v3/produtos")


def test_401_renova_uma_vez_e_repete(token, monkeypatch):
    http = FakeHTTP([FakeResponse(401), FakeResponse(200, {"data": []})])
    invalidado = []

    async def fake_invalidate():
        invalidado.append(True)

    monkeypatch.setattr(bc.auth, "invalidate_cache", fake_invalidate)
    client = bc.BlingClient(http=http)

    assert asyncio.run(client.get("/produtos")) == {"data": []}
    assert len(invalidado) == 1
    assert len(http.requests) == 2


def test_401_duas_vezes_levanta_auth_error(token):
    http = FakeHTTP([FakeResponse(401), FakeResponse(401)])
    client = bc.BlingClient(http=http)
    with pytest.raises(BlingAuthError):
        asyncio.run(client.get("/produtos"))


def test_429_faz_backoff_e_desiste(token):
    http = FakeHTTP([FakeResponse(429), FakeResponse(429), FakeResponse(429)])
    client = bc.BlingClient(http=http)
    with pytest.raises(BlingRateLimitError):
        asyncio.run(client.get("/produtos"))
    assert len(http.requests) == 3


def test_5xx_repete_e_depois_levanta_server_error(token):
    http = FakeHTTP([FakeResponse(500), FakeResponse(502), FakeResponse(503)])
    client = bc.BlingClient(http=http)
    with pytest.raises(BlingServerError):
        asyncio.run(client.get("/produtos"))
    assert len(http.requests) == 3


def test_5xx_seguido_de_sucesso_devolve_o_sucesso(token):
    http = FakeHTTP([FakeResponse(500), FakeResponse(200, {"data": {"ok": True}})])
    client = bc.BlingClient(http=http)
    assert asyncio.run(client.get("/produtos")) == {"data": {"ok": True}}


def test_400_de_validacao_nao_repete_e_carrega_a_mensagem(token):
    corpo = {"error": {"type": "VALIDATION_ERROR",
                       "message": "Nao foi possivel executar a operacao",
                       "description": "itens[0].quantidade invalida"}}
    http = FakeHTTP([FakeResponse(400, corpo)])
    client = bc.BlingClient(http=http)

    with pytest.raises(BlingValidationError) as exc:
        asyncio.run(client.post("/pedidos/vendas", json={"x": 1}))

    assert len(http.requests) == 1, "erro de validacao nao pode ser retentado"
    assert exc.value.type == "VALIDATION_ERROR"
    assert "quantidade invalida" in exc.value.description


def test_rate_limiter_e_chamado_antes_de_cada_request(token, monkeypatch):
    chamadas = []

    async def fake_acquire():
        chamadas.append(True)

    monkeypatch.setattr(bc.ratelimit, "acquire", fake_acquire)
    http = FakeHTTP([FakeResponse(500), FakeResponse(200, {"data": []})])
    client = bc.BlingClient(http=http)

    asyncio.run(client.get("/produtos"))
    assert len(chamadas) == 2, "cada tentativa consome uma vaga do orcamento"


def test_paginate_percorre_ate_pagina_incompleta(token):
    http = FakeHTTP([
        FakeResponse(200, {"data": [{"id": 1}, {"id": 2}]}),
        FakeResponse(200, {"data": [{"id": 3}]}),
    ])
    client = bc.BlingClient(http=http)

    async def run():
        return [item async for item in client.paginate("/produtos", {"criterio": 5}, limite=2)]

    assert asyncio.run(run()) == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert http.requests[0]["params"]["pagina"] == 1
    assert http.requests[1]["params"]["pagina"] == 2
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.client'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/client.py
"""Cliente HTTP unico da API v3 do Bling.

Toda chamada ao Bling no sistema passa por aqui — e o que garante que o
token-bucket de 3 req/s (limite por CONTA) seja respeitado de verdade.

Politica de retry, derivada da pagina de erros do Bling:
  401 -> invalida o cache do token, renova UMA vez e repete. Segunda falha e
         BlingAuthError (precisa refazer o OAuth).
  429 -> backoff exponencial 1s/2s/4s, 3 tentativas.
  5xx / timeout -> mesmo backoff.
  4xx de validacao -> levanta na hora, SEM retry. Repetir o mesmo payload
         invalido so queima orcamento e conta para o bloqueio de IP
         (300 erros em 10s = 10 min bloqueado).
"""
import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

from app.bling import auth, config, ratelimit
from app.bling.errors import (
    BlingAuthError, BlingRateLimitError, BlingServerError, BlingValidationError,
)

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 1.0
_PAGE_LIMIT = 100


class BlingClient:
    """Wrapper de httpx com auth, rate limit e retry.

    `http` existe para os testes injetarem um duble; em producao o cliente cria
    o proprio httpx.AsyncClient.
    """

    def __init__(self, http: Any | None = None, timeout: float = 30.0):
        self._http = http
        self._owns_http = http is None
        self._timeout = timeout

    async def _client(self):
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        await self.aclose()
        return False

    async def _headers(self) -> dict:
        token = await auth.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            # Obrigatorio: sem isso o Bling devolve o token opaco descontinuado.
            "enable-jwt": "1",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def request(self, method: str, path: str, *, params: dict | None = None,
                      json: dict | None = None) -> dict:
        url = f"{config.API_BASE}{path}"
        renovou = False

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            # Consome uma vaga do orcamento a CADA tentativa — a tentativa
            # repetida tambem e uma requisicao real para o Bling.
            await ratelimit.acquire()
            http = await self._client()
            try:
                resp = await http.request(
                    method, url, headers=await self._headers(),
                    params=params, json=json,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == _MAX_ATTEMPTS:
                    raise BlingServerError(f"{method} {path}: {exc}") from exc
                await asyncio.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            status = resp.status_code

            if 200 <= status < 300:
                try:
                    return resp.json()
                except Exception:  # noqa: BLE001 — 204 e afins
                    return {}

            if status == 401:
                if renovou:
                    raise BlingAuthError(
                        f"{method} {path}: 401 apos renovar o token — refaca o OAuth"
                    )
                renovou = True
                await auth.invalidate_cache()
                continue

            if status == 429:
                if attempt == _MAX_ATTEMPTS:
                    raise BlingRateLimitError(f"{method} {path}: 429 do Bling")
                await asyncio.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            if status >= 500:
                if attempt == _MAX_ATTEMPTS:
                    raise BlingServerError(f"{method} {path}: HTTP {status}")
                await asyncio.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            # 4xx de validacao: nunca retenta.
            body = {}
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                pass
            err = (body or {}).get("error") or {}
            raise BlingValidationError(
                err.get("message") or f"{method} {path}: HTTP {status}",
                type_=err.get("type") or "",
                description=err.get("description") or "",
                status=status,
                payload=body,
            )

        raise BlingServerError(f"{method} {path}: tentativas esgotadas")

    async def get(self, path: str, params: dict | None = None) -> dict:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: dict | None = None) -> dict:
        return await self.request("POST", path, json=json)

    async def put(self, path: str, json: dict | None = None) -> dict:
        return await self.request("PUT", path, json=json)

    async def paginate(self, path: str, params: dict | None = None,
                       limite: int = _PAGE_LIMIT) -> AsyncIterator[dict]:
        """Itera todas as paginas ate a pagina vir incompleta ou vazia."""
        pagina = 1
        while True:
            page_params = dict(params or {})
            page_params.update({"pagina": pagina, "limite": limite})
            body = await self.get(path, page_params)
            itens = body.get("data") or []
            for item in itens:
                yield item
            if len(itens) < limite:
                return
            pagina += 1
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_client.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/client.py backend/tests/test_bling_client.py
git commit -m "feat(bling): cliente HTTP com retry, rate limit e mapeamento de erros"
```

---

## Fase 2 — Espelhos locais

### Task 6: Sync do catálogo de produtos

**Files:**
- Create: `backend/app/bling/products.py`
- Test: `backend/tests/test_bling_products.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_bling_products.py
import asyncio

import app.bling.products as prod


class FakeTable:
    def __init__(self, store, name):
        self.store = store
        self.name = name
        self._filters = {}

    def upsert(self, rows, on_conflict=None):
        self.store.setdefault(self.name, []).extend(rows)
        self.store["on_conflict"] = on_conflict
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row_" + self.name)
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeTable(self.store, name)


class FakeClient:
    def __init__(self, itens):
        self.itens = itens
        self.params = None

    async def paginate(self, path, params=None, limite=100):
        self.params = params
        for item in self.itens:
            yield item


def test_mapeia_campos_do_bling_para_a_tabela():
    bruto = {
        "id": 123, "nome": "Cafe Canastra Classico Moido 250g", "codigo": "CAN-CLA-250",
        "preco": 26.7, "tipo": "P", "situacao": "A", "formato": "S",
        "idProdutoPai": 0, "descricaoCurta": "", "imagemURL": "https://x/y.jpg",
        "estoque": {"saldoVirtualTotal": 480.0},
    }
    row = prod.map_product(bruto)
    assert row["id"] == 123
    assert row["codigo"] == "CAN-CLA-250"
    assert row["nome"] == "Cafe Canastra Classico Moido 250g"
    assert row["preco"] == 26.7
    assert row["situacao"] == "A"
    assert row["saldo_virtual"] == 480.0
    assert row["imagem_url"] == "https://x/y.jpg"
    # idProdutoPai 0 significa "sem pai" no Bling — nao pode virar FK falsa
    assert row["id_produto_pai"] is None


def test_sync_completo_usa_criterio_5_e_faz_upsert(monkeypatch):
    store = {}
    client = FakeClient([
        {"id": 1, "nome": "A", "situacao": "A"},
        {"id": 2, "nome": "B", "situacao": "I"},
    ])
    monkeypatch.setattr(prod, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(prod, "_save_sync_state", lambda *a, **k: None)

    n = asyncio.run(prod.sync_products(client, full=True))

    assert n == 2
    # criterio=5 => "Todos" (inclui inativos). Produto inativo precisa ficar no
    # espelho para pedidos antigos e o backfill resolverem a descricao.
    assert client.params["criterio"] == 5
    assert store["on_conflict"] == "id"
    assert len(store["bling_products"]) == 2


def test_sync_incremental_manda_data_alteracao_inicial(monkeypatch):
    store = {"row_bling_sync_state": {"last_sync_at": "2026-08-17T00:00:00+00:00"}}
    client = FakeClient([{"id": 9, "nome": "C", "situacao": "A"}])
    monkeypatch.setattr(prod, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(prod, "_save_sync_state", lambda *a, **k: None)

    asyncio.run(prod.sync_products(client, full=False))

    assert client.params["dataAlteracaoInicial"] == "2026-08-17T00:00:00+00:00"
    assert "criterio" not in client.params


def test_sem_estado_anterior_cai_para_sync_completo(monkeypatch):
    store = {}
    client = FakeClient([{"id": 1, "nome": "A", "situacao": "A"}])
    monkeypatch.setattr(prod, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(prod, "_save_sync_state", lambda *a, **k: None)

    asyncio.run(prod.sync_products(client, full=False))

    assert client.params["criterio"] == 5


def test_apply_webhook_product_faz_upsert(monkeypatch):
    store = {}
    monkeypatch.setattr(prod, "get_supabase", lambda: FakeSupabase(store))
    payload = {"id": 55, "nome": "Novo", "codigo": "X", "preco": 9.9,
               "situacao": "A", "tipo": "P", "formato": "S"}
    asyncio.run(prod.apply_product_event("product.updated", payload))
    assert store["bling_products"][0]["id"] == 55


def test_apply_webhook_deleted_marca_inativo(monkeypatch):
    store = {}
    monkeypatch.setattr(prod, "get_supabase", lambda: FakeSupabase(store))
    asyncio.run(prod.apply_product_event("product.deleted", {"id": 55}))
    assert store["bling_products"][0]["situacao"] == "I"
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_products.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.products'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/products.py
"""Espelho local do catalogo de produtos do Bling.

Por que espelho e nao consulta ao vivo: o combobox do modal de venda dispara uma
busca a cada tecla. Consultar o Bling ali queimaria o orcamento de 3 req/s da
CONTA INTEIRA — o job de sync e o processamento de webhook ficariam sem vaga.
O espelho tambem torna o modal instantaneo e imune a instabilidade do Bling.
"""
import asyncio
import logging
from datetime import datetime, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_RESOURCE = "products"
# criterio=5 => "Todos". Inclui inativos de proposito: pedido antigo e backfill
# precisam do produto no espelho para resolver descricao e SKU.
_CRITERIO_TODOS = 5


def map_product(bruto: dict) -> dict:
    """Traduz o objeto do Bling para a linha de `bling_products`."""
    pai = bruto.get("idProdutoPai")
    estoque = bruto.get("estoque") or {}
    return {
        "id": int(bruto["id"]),
        "codigo": bruto.get("codigo") or None,
        "nome": bruto.get("nome") or "",
        "preco": bruto.get("preco"),
        "unidade": bruto.get("unidade") or None,
        "tipo": bruto.get("tipo") or None,
        "formato": bruto.get("formato") or None,
        "situacao": bruto.get("situacao") or None,
        # O Bling manda 0 para "sem pai"; 0 nao e um id valido.
        "id_produto_pai": int(pai) if pai else None,
        "saldo_virtual": estoque.get("saldoVirtualTotal"),
        "imagem_url": bruto.get("imagemURL") or None,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_sync_state(resource: str) -> dict | None:
    res = (get_supabase().table("bling_sync_state")
           .select("*").eq("resource", resource).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _save_sync_state(resource: str, *, last_sync_at: str, cursor: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    (get_supabase().table("bling_sync_state").upsert(
        {"resource": resource, "last_sync_at": last_sync_at,
         "last_cursor": cursor, "updated_at": now},
        on_conflict="resource").execute())


async def _upsert(rows: list[dict]) -> None:
    if not rows:
        return
    await asyncio.to_thread(
        lambda: get_supabase().table("bling_products")
        .upsert(rows, on_conflict="id").execute()
    )


async def sync_products(client, *, full: bool = False, batch_size: int = 200) -> int:
    """Sincroniza o catalogo. `full=True` traz tudo; senao, so o que mudou.

    Sem estado anterior, cai para completo — e o primeiro sync.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    params: dict = {}
    if not full:
        estado = await asyncio.to_thread(_load_sync_state, _RESOURCE)
        desde = (estado or {}).get("last_sync_at")
        if desde:
            params["dataAlteracaoInicial"] = desde
        else:
            full = True
    if full:
        params["criterio"] = _CRITERIO_TODOS

    total, buffer = 0, []
    async for bruto in client.paginate("/produtos", params):
        buffer.append(map_product(bruto))
        if len(buffer) >= batch_size:
            await _upsert(buffer)
            total += len(buffer)
            buffer = []
    if buffer:
        await _upsert(buffer)
        total += len(buffer)

    await asyncio.to_thread(_save_sync_state, _RESOURCE, last_sync_at=started_at)
    logger.info("[BLING] catalogo sincronizado: %d produtos (full=%s)", total, full)
    return total


async def apply_product_event(event: str, payload: dict) -> None:
    """Aplica um webhook `product.*` no espelho."""
    if event.endswith(".deleted"):
        row = {
            "id": int(payload["id"]),
            "situacao": "I",  # nunca apaga: pedidos historicos referenciam o produto
            "nome": payload.get("nome") or "(removido)",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        row = map_product(payload)
    await _upsert([row])
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_products.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/products.py backend/tests/test_bling_products.py
git commit -m "feat(bling): espelho do catalogo de produtos"
```

---

### Task 7: Sync de contatos, formas de pagamento e vendedores + tick do worker

**Files:**
- Create: `backend/app/bling/sync.py`
- Modify: `backend/app/worker/main.py` (registrar `bling-sync` em `TASK_SPECS`)
- Test: `backend/tests/test_bling_sync.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_bling_sync.py
import asyncio

import app.bling.sync as sync


class FakeTable:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def upsert(self, rows, on_conflict=None):
        self.store.setdefault(self.name, []).extend(rows)
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row_" + self.name)
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeTable(self.store, name)


class FakeClient:
    def __init__(self, por_path):
        self.por_path = por_path
        self.params = {}

    async def paginate(self, path, params=None, limite=100):
        self.params[path] = params
        for item in self.por_path.get(path, []):
            yield item


def test_contato_normaliza_telefone_com_a_funcao_do_crm():
    """O casamento lead <-> contato depende de a normalizacao ser a MESMA dos dois
    lados. O Bling guarda '(51) 99269-6163'; leads.phone guarda '5551992696163'."""
    bruto = {
        "id": 5845664414, "nome": "360 IMP E DISTRIBUIDORA LTDA",
        "fantasia": "360 ALIMENTOS", "tipo": "J",
        "numeroDocumento": "29.860.598/0001-70",
        "telefone": "(51) 99269-6163", "celular": "51 3714-1000",
        "email": "adm@projetos360.com.br", "situacao": "A",
    }
    row = sync.map_contact(bruto)
    assert row["doc_digits"] == "29860598000170"
    assert row["telefone_e164"] == "5551992696163"
    assert row["celular_e164"] == "555137141000"
    assert row["email"] == "adm@projetos360.com.br"


def test_contato_sem_documento_fica_com_doc_digits_nulo():
    row = sync.map_contact({"id": 1, "nome": "X", "tipo": "F"})
    assert row["doc_digits"] is None


def test_contato_extrai_endereco_para_jsonb():
    bruto = {
        "id": 2, "nome": "Y", "tipo": "J",
        "endereco": {"geral": {"endereco": "Rua A", "numero": "255", "bairro": "Centro",
                               "municipio": "Uberlandia", "uf": "MG", "cep": "38400084"}},
    }
    row = sync.map_contact(bruto)
    assert row["endereco"]["municipio"] == "Uberlandia"
    assert row["endereco"]["cep"] == "38400084"


def test_sync_contacts_incremental_usa_data_alteracao(monkeypatch):
    store = {"row_bling_sync_state": {"last_sync_at": "2026-08-17T00:00:00+00:00"}}
    client = FakeClient({"/contatos": [{"id": 1, "nome": "A", "tipo": "J"}]})
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    n = asyncio.run(sync.sync_contacts(client))

    assert n == 1
    assert client.params["/contatos"]["dataAlteracaoInicial"] == "2026-08-17T00:00:00+00:00"


def test_sync_contacts_completo_usa_criterio_1_todos(monkeypatch):
    """criterio=3 (default do Bling) traz so os 'ultimos incluidos' — no primeiro
    sync isso deixaria a base incompleta silenciosamente."""
    store = {}
    client = FakeClient({"/contatos": [{"id": 1, "nome": "A", "tipo": "J"}]})
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    asyncio.run(sync.sync_contacts(client))

    assert client.params["/contatos"]["criterio"] == 1


def test_sync_payment_methods_e_sellers(monkeypatch):
    store = {}
    client = FakeClient({
        "/formas-pagamentos": [{"id": 45, "descricao": "Boleto", "tipoPagamento": 15,
                                "situacao": 1, "padrao": 1, "finalidade": 2}],
        "/vendedores": [{"id": 7, "contato": {"nome": "Joao Bras"}, "situacao": "A"}],
    })
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    asyncio.run(sync.sync_payment_methods(client))
    asyncio.run(sync.sync_sellers(client))

    assert store["bling_payment_methods"][0]["descricao"] == "Boleto"
    assert store["bling_sellers"][0]["nome"] == "Joao Bras"


def test_tick_nao_faz_nada_quando_desabilitado(monkeypatch):
    monkeypatch.setattr(sync.config, "enabled", lambda: False)
    chamou = []
    monkeypatch.setattr(sync, "sync_all", lambda *a, **k: chamou.append(True))
    asyncio.run(sync.bling_sync_tick())
    assert chamou == []


def test_worker_registra_o_tick_de_sync():
    from app.worker.main import TASK_SPECS
    spec = next(s for s in TASK_SPECS if s[0] == "bling-sync")
    assert spec[1] == "periodic"
    assert callable(spec[2])
    assert spec[3] == 86400
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.sync'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/sync.py
"""Espelhos de contatos, formas de pagamento e vendedores + tick diario.

Contatos precisam de POLLING: a lista de recursos de webhook do Bling e
`order`, `product`, `stock`, `virtual_stock`, `product_supplier`, `invoice` e
`consumer_invoice` — nao existe webhook de contato.
"""
import asyncio
import logging
from datetime import datetime, timezone

from app.bling import config
from app.bling.products import sync_products
from app.db.supabase import get_supabase
from app.leads.service import normalize_phone

logger = logging.getLogger(__name__)

# criterio=1 => "Todos". O default da API e 3 ("ultimos incluidos"), que no
# primeiro sync deixaria a base incompleta sem avisar.
_CRITERIO_TODOS = 1


def _digits(value: str | None) -> str | None:
    if not value:
        return None
    out = "".join(ch for ch in value if ch.isdigit())
    return out or None


def map_contact(bruto: dict) -> dict:
    """Traduz o contato do Bling para `bling_contacts`, ja normalizado.

    `telefone_e164`/`celular_e164` usam `app.leads.service.normalize_phone` — a
    MESMA funcao que normaliza `leads.phone`. E isso que faz os dois lados
    casarem; o formato de texto livre do Bling nunca casaria sozinho.
    """
    endereco = ((bruto.get("endereco") or {}).get("geral")) or None
    financeiro = bruto.get("financeiro") or {}
    vendedor = bruto.get("vendedor") or {}
    return {
        "id": int(bruto["id"]),
        "nome": bruto.get("nome") or "",
        "fantasia": bruto.get("fantasia") or None,
        "tipo": bruto.get("tipo") or None,
        "doc_digits": _digits(bruto.get("numeroDocumento")),
        "telefone_e164": normalize_phone(bruto.get("telefone")) or None,
        "celular_e164": normalize_phone(bruto.get("celular")) or None,
        "email": (bruto.get("email") or "").strip() or None,
        "situacao": bruto.get("situacao") or None,
        "endereco": endereco,
        "vendedor_id": int(vendedor["id"]) if vendedor.get("id") else None,
        "condicao_pagamento": financeiro.get("condicaoPagamento") or None,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_sync_state(resource: str) -> dict | None:
    res = (get_supabase().table("bling_sync_state")
           .select("*").eq("resource", resource).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _save_sync_state(resource: str, *, last_sync_at: str, cursor: str | None = None) -> None:
    (get_supabase().table("bling_sync_state").upsert(
        {"resource": resource, "last_sync_at": last_sync_at, "last_cursor": cursor,
         "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="resource").execute())


async def _upsert(table: str, rows: list[dict]) -> None:
    if not rows:
        return
    await asyncio.to_thread(
        lambda: get_supabase().table(table).upsert(rows, on_conflict="id").execute()
    )


async def sync_contacts(client, *, batch_size: int = 200) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    estado = await asyncio.to_thread(_load_sync_state, "contacts")
    desde = (estado or {}).get("last_sync_at")
    params = {"dataAlteracaoInicial": desde} if desde else {"criterio": _CRITERIO_TODOS}

    total, buffer = 0, []
    async for bruto in client.paginate("/contatos", params):
        buffer.append(map_contact(bruto))
        if len(buffer) >= batch_size:
            await _upsert("bling_contacts", buffer)
            total += len(buffer)
            buffer = []
    if buffer:
        await _upsert("bling_contacts", buffer)
        total += len(buffer)

    await asyncio.to_thread(_save_sync_state, "contacts", last_sync_at=started_at)
    logger.info("[BLING] contatos sincronizados: %d", total)
    return total


async def sync_payment_methods(client) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    rows = []
    async for b in client.paginate("/formas-pagamentos", {}):
        rows.append({
            "id": int(b["id"]),
            "descricao": b.get("descricao") or "",
            "tipo_pagamento": b.get("tipoPagamento"),
            "situacao": b.get("situacao"),
            "padrao": b.get("padrao"),
            "finalidade": b.get("finalidade"),
            "synced_at": started_at,
        })
    await _upsert("bling_payment_methods", rows)
    await asyncio.to_thread(_save_sync_state, "payment_methods", last_sync_at=started_at)
    return len(rows)


async def sync_sellers(client) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    rows = []
    async for b in client.paginate("/vendedores", {}):
        # O nome do vendedor vem aninhado em `contato` na API de vendedores.
        nome = (b.get("contato") or {}).get("nome") or b.get("nome") or ""
        rows.append({
            "id": int(b["id"]),
            "nome": nome,
            "situacao": b.get("situacao"),
            "synced_at": started_at,
        })
    await _upsert("bling_sellers", rows)
    await asyncio.to_thread(_save_sync_state, "sellers", last_sync_at=started_at)
    return len(rows)


async def sync_all(*, full: bool = False) -> dict:
    """Roda os quatro syncs em sequencia (nunca em paralelo: 3 req/s e da conta)."""
    from app.bling.client import BlingClient

    async with BlingClient() as client:
        produtos = await sync_products(client, full=full)
        contatos = await sync_contacts(client)
        formas = await sync_payment_methods(client)
        vendedores = await sync_sellers(client)
    return {"produtos": produtos, "contatos": contatos,
            "formas_pagamento": formas, "vendedores": vendedores}


async def bling_sync_tick() -> None:
    """Tick do worker. Silencioso e sem excecao quando desligado ou sem OAuth."""
    if not config.enabled():
        return
    try:
        resultado = await sync_all()
        logger.info("[BLING] sync diario: %s", resultado)
    except Exception as exc:  # noqa: BLE001 — worker nunca morre por causa do Bling
        logger.warning("[BLING] sync diario falhou: %s", exc)
```

- [ ] **Step 4: Registrar o tick no worker**

Em `backend/app/worker/main.py`, adicione a função junto das outras `_*_tick` (logo
após `_ad_spend_sync_tick`):

```python
async def _bling_sync_tick() -> None:
    from app.bling.sync import bling_sync_tick
    await bling_sync_tick()
```

E acrescente a linha em `TASK_SPECS`, depois de `("ad-spend-sync", ...)`:

```python
    ("bling-sync", "periodic", _bling_sync_tick, 86400),
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_sync.py -v`
Expected: PASS — 8 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/sync.py backend/app/worker/main.py backend/tests/test_bling_sync.py
git commit -m "feat(bling): espelho de contatos, formas de pagamento e vendedores"
```

---

## Fase 3 — Identidade de cliente

### Task 8: Resolução e criação de contato

Esta é a task mais importante do plano. É ela que impede contato duplicado no ERP.

**Files:**
- Create: `backend/app/bling/contacts.py`
- Test: `backend/tests/test_bling_contacts.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
# backend/tests/test_bling_contacts.py
import asyncio

import pytest

import app.bling.contacts as ct
from app.bling.errors import BlingValidationError


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def in_(self, col, vals):
        self.filters[col] = vals
        return self

    def or_(self, expr):
        self.filters["or"] = expr
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def update(self, payload):
        self.filters["update"] = payload
        return self

    def insert(self, payload):
        self.filters["insert"] = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.filters["upsert"] = payload
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.rows
        return r


class FakeSupabase:
    """Devolve linhas por tabela; guarda o que foi escrito."""

    def __init__(self, por_tabela=None):
        self.por_tabela = por_tabela or {}
        self.queries = []

    def table(self, name):
        q = FakeQuery(self.por_tabela.get(name, []))
        q.name = name
        self.queries.append(q)
        return q


def test_digits_limpa_pontuacao():
    assert ct.doc_digits("29.860.598/0001-70") == "29860598000170"
    assert ct.doc_digits("123.456.789-09") == "12345678909"
    assert ct.doc_digits("") is None
    assert ct.doc_digits(None) is None


def test_documento_valido_so_com_11_ou_14_digitos():
    assert ct.is_valid_document("29860598000170") is True   # CNPJ real
    assert ct.is_valid_document("12345678909") is True      # CPF valido
    assert ct.is_valid_document("11111111111") is False     # repetido
    assert ct.is_valid_document("123") is False
    assert ct.is_valid_document("12345678901234") is False  # CNPJ com DV errado


def test_resolve_usa_o_vinculo_ja_gravado(monkeypatch):
    lead = {"id": "L1", "bling_contact_id": 999, "cnpj": "29860598000170"}
    monkeypatch.setattr(ct, "get_supabase", lambda: FakeSupabase())

    out = asyncio.run(ct.resolve(lead))

    assert out.contact_id == 999
    assert out.status == "linked"


def test_resolve_por_documento_vincula_sozinho(monkeypatch):
    lead = {"id": "L1", "bling_contact_id": None, "cnpj": "29.860.598/0001-70",
            "phone": "5551992696163"}
    sb = FakeSupabase({"bling_contacts": [{"id": 5845664414, "nome": "360 LTDA"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "linked"
    assert out.contact_id == 5845664414
    # o vinculo tem que ser PERSISTIDO — resolvido uma vez por cliente, para sempre
    assert any(q.filters.get("update", {}).get("bling_contact_id") == 5845664414
               for q in sb.queries)


def test_documento_com_dois_contatos_nao_vincula(monkeypatch):
    """Ambiguidade nunca vira palpite: devolve candidatos e para."""
    lead = {"id": "L1", "bling_contact_id": None, "cnpj": "29860598000170"}
    sb = FakeSupabase({"bling_contacts": [{"id": 1, "nome": "A"}, {"id": 2, "nome": "B"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "ambiguous"
    assert out.contact_id is None
    assert len(out.candidates) == 2
    assert not any("update" in q.filters for q in sb.queries)


def test_telefone_apenas_sugere_nunca_vincula(monkeypatch):
    """O telefone do lead costuma ser o do COMPRADOR; o contato do Bling e a
    EMPRESA. Casar por telefone sem confirmacao humana e chute."""
    lead = {"id": "L1", "bling_contact_id": None, "cnpj": None, "phone": "5551992696163"}
    sb = FakeSupabase({"bling_contacts": [{"id": 77, "nome": "Empresa X"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "suggested"
    assert out.contact_id is None
    assert out.candidates[0]["id"] == 77
    assert not any("update" in q.filters for q in sb.queries)


def test_sem_nenhum_match_devolve_missing(monkeypatch):
    lead = {"id": "L1", "bling_contact_id": None, "cnpj": None, "phone": "5511999999999"}
    monkeypatch.setattr(ct, "get_supabase", lambda: FakeSupabase())

    out = asyncio.run(ct.resolve(lead))

    assert out.status == "missing"
    assert out.candidates == []


def test_create_recusa_sem_documento(monkeypatch):
    lead = {"id": "L1", "name": "Fulano", "phone": "5511999999999"}
    with pytest.raises(BlingValidationError) as exc:
        asyncio.run(ct.create_contact(None, lead, {"nome": "Fulano"}))
    assert "documento" in str(exc.value).lower()


def test_create_recheca_ao_vivo_e_vincula_em_vez_de_criar(monkeypatch):
    """O espelho pode estar minutos atrasado. Antes do POST, pergunta ao Bling."""
    lead = {"id": "L1", "name": "360 LTDA"}
    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)
    monkeypatch.setattr(ct, "_lock", _fake_lock)

    class FakeClient:
        def __init__(self):
            self.posts = []

        async def get(self, path, params=None):
            assert params["numeroDocumento"] == "29860598000170"
            return {"data": [{"id": 424242, "nome": "360 LTDA"}]}

        async def post(self, path, json=None):
            self.posts.append(json)
            return {"data": {"id": 999999}}

    client = FakeClient()
    out = asyncio.run(ct.create_contact(
        client, lead, {"nome": "360 LTDA", "numeroDocumento": "29.860.598/0001-70",
                       "tipo": "J"}))

    assert out == 424242
    assert client.posts == [], "nao pode criar quando o contato ja existe no Bling"


def test_create_faz_post_quando_realmente_nao_existe(monkeypatch):
    lead = {"id": "L1", "name": "Novo Cliente"}
    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)
    monkeypatch.setattr(ct, "_lock", _fake_lock)

    class FakeClient:
        def __init__(self):
            self.posts = []

        async def get(self, path, params=None):
            return {"data": []}

        async def post(self, path, json=None):
            self.posts.append(json)
            return {"data": {"id": 999999}}

    client = FakeClient()
    out = asyncio.run(ct.create_contact(
        client, lead, {"nome": "Novo Cliente", "numeroDocumento": "12345678909",
                       "tipo": "F", "email": "a@b.com"}))

    assert out == 999999
    enviado = client.posts[0]
    assert enviado["situacao"] == "A"
    assert enviado["numeroDocumento"] == "12345678909"
    assert enviado["tipo"] == "F"


def test_ensure_lead_reaproveita_lead_existente_por_documento(monkeypatch):
    contato = {"id": 55, "nome": "Empresa", "doc_digits": "29860598000170",
               "celular_e164": "5551992696163"}
    sb = FakeSupabase({"leads": [{"id": "LEAD-X"}]})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    out = asyncio.run(ct.ensure_lead(contato))

    assert out == "LEAD-X"


def test_ensure_lead_cria_com_placeholder_quando_contato_nao_tem_telefone(monkeypatch):
    """leads.phone e UNIQUE NOT NULL — precisa de valor sempre."""
    contato = {"id": 55, "nome": "Sem Telefone", "doc_digits": "12345678909",
               "telefone_e164": None, "celular_e164": None}
    sb = FakeSupabase({"leads": []})
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)

    asyncio.run(ct.ensure_lead(contato))

    inseridos = [q.filters["insert"] for q in sb.queries if "insert" in q.filters]
    assert inseridos[0]["phone"] == "bling-55"
    assert inseridos[0]["bling_contact_id"] == 55
    assert inseridos[0]["metadata"]["origem"] == "bling_webhook"


def _fake_lock(_key):
    class _Ctx:
        async def __aenter__(self):
            return True

        async def __aexit__(self, *_a):
            return False
    return _Ctx()
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `cd backend && python -m pytest tests/test_bling_contacts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.contacts'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/contacts.py
"""Identidade de cliente: casar lead do CRM com contato do Bling sem duplicar.

O PROBLEMA: o CRM normaliza telefone para E.164 ("5551992696163"); o Bling
guarda texto livre formatado ("(51) 99269-6163"). Casar por telefone criaria
contatos duplicados no ERP. Pior: o telefone do lead costuma ser o do COMPRADOR
(uma pessoa), enquanto o contato do Bling e a EMPRESA.

A SOLUCAO, em quatro camadas:
  1. CPF/CNPJ (so digitos) e a chave. Unico identificador canonico dos dois lados.
  2. O vinculo e PERSISTIDO em `leads.bling_contact_id`, sob indice UNIQUE
     parcial. Resolvido uma vez por cliente, para sempre.
  3. Telefone e e-mail apenas SUGEREM — exigem confirmacao humana.
  4. Antes de criar, lock por documento + re-checagem AO VIVO na API.
"""
import asyncio
import logging
import secrets
from dataclasses import dataclass, field

import redis.asyncio as aioredis

from app.bling import config
from app.bling.errors import BlingValidationError
from app.config import settings
from app.db.supabase import get_supabase
from app.leads.service import normalize_phone

logger = logging.getLogger(__name__)

_LOCK_TTL = 30
_redis: aioredis.Redis | None = None


@dataclass
class Resolution:
    """Resultado da resolucao de identidade.

    status:
      linked    — vinculado (determinístico). `contact_id` preenchido.
      ambiguous — mais de um contato com o mesmo documento. Decide o humano.
      suggested — casou por telefone/e-mail. Precisa de confirmacao.
      missing   — nao existe contato correspondente. Fluxo de criacao.
    """
    status: str
    contact_id: int | None = None
    candidates: list[dict] = field(default_factory=list)
    reason: str = ""


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _redis


def _lock(key: str):
    """Lock Redis simples com liberacao por token (padrao do buffer/lead_lock)."""
    client = _get_redis()
    token = secrets.token_hex(8)

    class _Ctx:
        owned = False

        async def __aenter__(self):
            for _ in range(60):
                if await client.set(key, token, nx=True, ex=_LOCK_TTL):
                    self.owned = True
                    return True
                await asyncio.sleep(0.5)
            return False

        async def __aexit__(self, *_a):
            if self.owned:
                lua = ("if redis.call('get', KEYS[1]) == ARGV[1] then "
                       "return redis.call('del', KEYS[1]) else return 0 end")
                await client.eval(lua, 1, key, token)
            return False

    return _Ctx()


# --------------------------------------------------------------------------
# Documento
# --------------------------------------------------------------------------
def doc_digits(value: str | None) -> str | None:
    if not value:
        return None
    out = "".join(ch for ch in value if ch.isdigit())
    return out or None


def _cpf_ok(d: str) -> bool:
    if len(set(d)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d[i]) * ((tamanho + 1) - i) for i in range(tamanho))
        dv = (soma * 10) % 11 % 10
        if dv != int(d[tamanho]):
            return False
    return True


def _cnpj_ok(d: str) -> bool:
    if len(set(d)) == 1:
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    for pesos, pos in ((pesos1, 12), (pesos2, 13)):
        soma = sum(int(d[i]) * pesos[i] for i in range(pos))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(d[pos]):
            return False
    return True


def is_valid_document(value: str | None) -> bool:
    """CPF (11) ou CNPJ (14) com digito verificador correto.

    Validar o DV importa: um documento digitado errado nao acha o contato
    existente e cria um duplicado — exatamente o que queremos evitar.
    """
    d = doc_digits(value)
    if not d:
        return False
    if len(d) == 11:
        return _cpf_ok(d)
    if len(d) == 14:
        return _cnpj_ok(d)
    return False


# --------------------------------------------------------------------------
# Resolucao
# --------------------------------------------------------------------------
def _phone_variants(lead: dict) -> list[str]:
    brutos = [lead.get("phone"), lead.get("telefone_comercial")]
    saida = []
    for bruto in brutos:
        norm = normalize_phone(bruto)
        if norm and norm not in saida:
            saida.append(norm)
    return saida


def _query_by_doc(doc: str) -> list[dict]:
    res = (get_supabase().table("bling_contacts")
           .select("id, nome, fantasia, doc_digits, email, telefone_e164, celular_e164")
           .eq("doc_digits", doc).limit(10).execute())
    return getattr(res, "data", None) or []


def _query_by_phones(phones: list[str]) -> list[dict]:
    if not phones:
        return []
    lista = ",".join(phones)
    res = (get_supabase().table("bling_contacts")
           .select("id, nome, fantasia, doc_digits, email, telefone_e164, celular_e164")
           .or_(f"telefone_e164.in.({lista}),celular_e164.in.({lista})")
           .limit(10).execute())
    return getattr(res, "data", None) or []


def _query_by_email(email: str) -> list[dict]:
    res = (get_supabase().table("bling_contacts")
           .select("id, nome, fantasia, doc_digits, email, telefone_e164, celular_e164")
           .eq("email", email).limit(10).execute())
    return getattr(res, "data", None) or []


def _link(lead_id: str, contact_id: int) -> None:
    (get_supabase().table("leads")
     .update({"bling_contact_id": contact_id}).eq("id", lead_id).execute())


async def resolve(lead: dict) -> Resolution:
    """Resolve o contato Bling de um lead. Ver docstring do modulo."""
    if lead.get("bling_contact_id"):
        return Resolution("linked", int(lead["bling_contact_id"]), reason="vinculo_existente")

    doc = doc_digits(lead.get("cnpj"))
    if doc:
        achados = await asyncio.to_thread(_query_by_doc, doc)
        if len(achados) == 1:
            contact_id = int(achados[0]["id"])
            await asyncio.to_thread(_link, lead["id"], contact_id)
            return Resolution("linked", contact_id, reason="documento")
        if len(achados) > 1:
            # Dois contatos com o mesmo CPF/CNPJ e sujeira no ERP. Escolher um
            # por conta propria significa lancar a venda no cadastro errado.
            return Resolution("ambiguous", None, achados, reason="documento_duplicado")

    achados = await asyncio.to_thread(_query_by_phones, _phone_variants(lead))
    if achados:
        return Resolution("suggested", None, achados, reason="telefone")

    email = (lead.get("email") or "").strip().lower()
    if email:
        achados = await asyncio.to_thread(_query_by_email, email)
        if achados:
            return Resolution("suggested", None, achados, reason="email")

    return Resolution("missing", None, [], reason="sem_correspondencia")


async def link(lead_id: str, contact_id: int) -> None:
    """Confirma manualmente o vinculo (usado quando o vendedor escolhe candidato)."""
    await asyncio.to_thread(_link, lead_id, contact_id)


# --------------------------------------------------------------------------
# Criacao
# --------------------------------------------------------------------------
def _upsert_mirror(row: dict) -> None:
    from app.bling.sync import map_contact
    (get_supabase().table("bling_contacts")
     .upsert(map_contact(row), on_conflict="id").execute())


async def create_contact(client, lead: dict, dados: dict) -> int:
    """Cria (ou reaproveita) o contato no Bling e devolve o id.

    `dados` vem do modal: nome, numeroDocumento, tipo, email, telefone, celular,
    endereco{geral{...}}.
    """
    doc = doc_digits(dados.get("numeroDocumento"))
    if not is_valid_document(doc):
        raise BlingValidationError(
            "CPF/CNPJ valido e obrigatorio para cadastrar o cliente no Bling",
            type_="MISSING_REQUIRED_FIELD_ERROR",
            description="Sem documento nao ha chave unica e o contato duplicaria no ERP.",
            status=422,
        )

    async with _lock(f"lock:bling_contact:{doc}") as owned:
        if not owned:
            raise BlingValidationError(
                "outro cadastro deste mesmo cliente esta em andamento; tente de novo",
                status=409,
            )

        # Re-checagem AO VIVO: o espelho pode estar minutos atrasado.
        vivo = await client.get("/contatos", {"numeroDocumento": doc})
        existentes = vivo.get("data") or []
        if existentes:
            contact_id = int(existentes[0]["id"])
            logger.info("[BLING] contato %s ja existia para doc %s — vinculando",
                        contact_id, doc)
        else:
            payload = {
                "nome": dados.get("nome") or lead.get("name") or "",
                "tipo": dados.get("tipo") or ("J" if len(doc) == 14 else "F"),
                "situacao": "A",
                "numeroDocumento": doc,
            }
            for campo in ("fantasia", "email", "telefone", "celular", "ie",
                          "indicadorIe", "endereco"):
                if dados.get(campo):
                    payload[campo] = dados[campo]
            criado = await client.post("/contatos", payload)
            contact_id = int((criado.get("data") or {})["id"])
            logger.info("[BLING] contato %s criado para doc %s", contact_id, doc)

        await asyncio.to_thread(_upsert_mirror, {
            "id": contact_id,
            "nome": dados.get("nome") or lead.get("name") or "",
            "tipo": dados.get("tipo"),
            "numeroDocumento": doc,
            "telefone": dados.get("telefone"),
            "celular": dados.get("celular"),
            "email": dados.get("email"),
            "situacao": "A",
            "endereco": dados.get("endereco"),
        })
        await asyncio.to_thread(_link, lead["id"], contact_id)
        return contact_id


# --------------------------------------------------------------------------
# Caminho inverso: contato do Bling sem lead no CRM
# --------------------------------------------------------------------------
def _find_lead(coluna: str, valor) -> str | None:
    res = (get_supabase().table("leads").select("id")
           .eq(coluna, valor).limit(1).execute())
    linhas = getattr(res, "data", None) or []
    return linhas[0]["id"] if linhas else None


def _insert_lead(payload: dict) -> str | None:
    res = get_supabase().table("leads").insert(payload).execute()
    linhas = getattr(res, "data", None) or []
    return linhas[0]["id"] if linhas else None


async def ensure_lead(contato: dict) -> str | None:
    """Devolve o lead_id do contato, criando o lead se preciso (decisao D6)."""
    contact_id = int(contato["id"])

    achado = await asyncio.to_thread(_find_lead, "bling_contact_id", contact_id)
    if achado:
        return achado

    doc = contato.get("doc_digits")
    if doc:
        achado = await asyncio.to_thread(_find_lead, "cnpj", doc)
        if achado:
            await asyncio.to_thread(_link, achado, contact_id)
            return achado

    telefone = contato.get("celular_e164") or contato.get("telefone_e164")
    if telefone:
        achado = await asyncio.to_thread(_find_lead, "phone", telefone)
        if achado:
            await asyncio.to_thread(_link, achado, contact_id)
            return achado

    endereco = contato.get("endereco") or {}
    partes = [endereco.get("municipio"), endereco.get("uf")]
    payload = {
        # leads.phone e UNIQUE NOT NULL. Sem telefone, um placeholder unico por
        # construcao. A coluna ja aceita valores nao-E.164 (BSUIDs do WhatsApp).
        "phone": telefone or f"bling-{contact_id}",
        "name": contato.get("fantasia") or contato.get("nome"),
        "company": contato.get("nome"),
        "razao_social": contato.get("nome"),
        "nome_fantasia": contato.get("fantasia"),
        "cnpj": doc,
        "email": contato.get("email"),
        "endereco": " - ".join([p for p in partes if p]) or None,
        "stage": config.lead_default_stage(),
        "status": "ativo",
        "channel": "bling",
        "bling_contact_id": contact_id,
        "metadata": {"origem": "bling_webhook", "id_bling": str(contact_id)},
    }
    lead_id = await asyncio.to_thread(_insert_lead, payload)
    logger.info("[BLING] lead %s criado a partir do contato %s", lead_id, contact_id)
    return lead_id
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `cd backend && python -m pytest tests/test_bling_contacts.py -v`
Expected: PASS — 12 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/contacts.py backend/tests/test_bling_contacts.py
git commit -m "feat(bling): resolucao de identidade por documento (anti-duplicacao)"
```

---

## Fase 4 — Criação do pedido de venda

### Task 9: Montagem do payload, parcelas e projeção em `sales`

**Files:**
- Create: `backend/app/bling/orders.py`
- Test: `backend/tests/test_bling_orders.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
# backend/tests/test_bling_orders.py
import asyncio
from decimal import Decimal

import pytest

import app.bling.orders as orders
from app.bling.errors import BlingValidationError


# ---------- parcelas ----------

def test_a_vista_gera_uma_parcela_na_data_da_venda():
    p = orders.build_installments(Decimal("500.00"), [0], 45, "2026-08-18")
    assert p == [{"dataVencimento": "2026-08-18", "valor": 500.0,
                  "formaPagamento": {"id": 45}}]


def test_30_60_divide_em_duas_e_soma_datas():
    p = orders.build_installments(Decimal("500.00"), [30, 60], 45, "2026-08-18")
    assert [x["dataVencimento"] for x in p] == ["2026-09-17", "2026-10-17"]
    assert [x["valor"] for x in p] == [250.0, 250.0]


def test_ultima_parcela_absorve_o_arredondamento():
    """100,00 em 3x = 33,33 + 33,33 + 33,34. A soma tem que fechar EXATO —
    se sobrar 1 centavo, o Bling recusa o pedido."""
    p = orders.build_installments(Decimal("100.00"), [30, 60, 90], 45, "2026-08-18")
    assert [x["valor"] for x in p] == [33.33, 33.33, 33.34]
    assert round(sum(x["valor"] for x in p), 2) == 100.00


def test_arredondamento_para_baixo_tambem_fecha():
    p = orders.build_installments(Decimal("10.00"), [0, 30, 60], 45, "2026-08-18")
    assert round(sum(x["valor"] for x in p), 2) == 10.00


def test_parcelas_exige_forma_de_pagamento():
    with pytest.raises(BlingValidationError):
        orders.build_installments(Decimal("100.00"), [0], None, "2026-08-18")


def test_parcelas_exige_pelo_menos_um_prazo():
    with pytest.raises(BlingValidationError):
        orders.build_installments(Decimal("100.00"), [], 45, "2026-08-18")


def test_parse_terms_aceita_string_do_bling():
    assert orders.parse_terms("30/60/90") == [30, 60, 90]
    assert orders.parse_terms("0") == [0]
    assert orders.parse_terms("") == [0]
    assert orders.parse_terms("a vista") == [0]


# ---------- total e itens ----------

def test_total_do_item_aplica_desconto_percentual():
    total = orders.item_total({"quantidade": 10, "valor_unitario": 26.70,
                               "desconto_percentual": 10})
    assert total == Decimal("240.30")


def test_total_do_pedido_soma_itens():
    itens = [
        {"quantidade": 10, "valor_unitario": 26.70, "desconto_percentual": 0},
        {"quantidade": 2, "valor_unitario": 50.00, "desconto_percentual": 0},
    ]
    assert orders.order_total(itens) == Decimal("367.00")


def test_resumo_de_produto_para_a_coluna_product():
    assert orders.product_summary([{"descricao": "Cafe Classico 250g"}]) == "Cafe Classico 250g"
    assert orders.product_summary([
        {"descricao": "Cafe Classico 250g"}, {"descricao": "Cafe Suave 500g"},
        {"descricao": "Drip Coffee"},
    ]) == "Cafe Classico 250g +2 itens"
    assert orders.product_summary([]) == "Pedido Bling"


# ---------- payload ----------

def test_payload_tem_os_campos_obrigatorios_do_bling(monkeypatch):
    monkeypatch.setattr(orders.config, "store_id", lambda: 203455519)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: 6)

    payload = orders.build_order_payload(
        contact_id=5845664414,
        sold_at="2026-08-18",
        itens=[{"bling_product_id": 123, "codigo": "CAN-250", "descricao": "Cafe 250g",
                "unidade": "UN", "quantidade": 10, "valor_unitario": 26.70,
                "desconto_percentual": 0}],
        payment={"method_id": 45, "terms": [30]},
        seller_id=7,
        notes="obs do cliente",
        internal_notes="CRM lead L1",
    )

    # obrigatorios segundo o OpenAPI: contato, data, dataSaida, dataPrevista, itens, parcelas
    assert payload["contato"] == {"id": 5845664414}
    assert payload["data"] == payload["dataSaida"] == payload["dataPrevista"] == "2026-08-18"
    assert payload["itens"][0]["produto"] == {"id": 123}
    assert payload["itens"][0]["descricao"] == "Cafe 250g"
    assert payload["itens"][0]["quantidade"] == 10
    assert payload["itens"][0]["valor"] == 26.70
    assert payload["parcelas"][0]["formaPagamento"] == {"id": 45}
    assert payload["vendedor"] == {"id": 7}
    assert payload["loja"] == {"id": 203455519}
    assert payload["situacao"]["id"] == 6
    assert payload["observacoes"] == "obs do cliente"
    assert payload["observacoesInternas"] == "CRM lead L1"


def test_payload_omite_loja_e_situacao_quando_nao_configurados(monkeypatch):
    monkeypatch.setattr(orders.config, "store_id", lambda: None)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: None)

    payload = orders.build_order_payload(
        contact_id=1, sold_at="2026-08-18",
        itens=[{"bling_product_id": 1, "descricao": "X", "quantidade": 1,
                "valor_unitario": 10.0, "desconto_percentual": 0}],
        payment={"method_id": 45, "terms": [0]}, seller_id=None,
    )
    assert "loja" not in payload
    assert "situacao" not in payload
    assert "vendedor" not in payload


def test_payload_recusa_pedido_sem_itens():
    with pytest.raises(BlingValidationError):
        orders.build_order_payload(contact_id=1, sold_at="2026-08-18", itens=[],
                                   payment={"method_id": 45, "terms": [0]}, seller_id=None)
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `cd backend && python -m pytest tests/test_bling_orders.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.orders'`

- [ ] **Step 3: Implementar as funções puras**

```python
# backend/app/bling/orders.py
"""Montagem e criacao do pedido de venda no Bling, e projecao em `sales`.

Campos obrigatorios do POST /pedidos/vendas (OpenAPI v3): contato.id, data,
dataSaida, dataPrevista, itens[] e parcelas[]. O contato PRECISA existir antes.

Dinheiro e tratado em Decimal do inicio ao fim. Float acumula erro de
arredondamento e a soma das parcelas precisa fechar EXATAMENTE com o total —
um centavo de diferenca e recusa do Bling.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from app.bling import config
from app.bling.errors import BlingValidationError

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def parse_terms(raw: str | None) -> list[int]:
    """"30/60/90" -> [30, 60, 90]. Vazio ou nao numerico -> [0] (a vista)."""
    if not raw:
        return [0]
    partes = [p.strip() for p in str(raw).replace(",", "/").split("/")]
    dias = [int(p) for p in partes if p.isdigit()]
    return dias or [0]


def item_total(item: dict) -> Decimal:
    bruto = _dec(item["quantidade"]) * _dec(item["valor_unitario"])
    desconto = _dec(item.get("desconto_percentual"))
    return _money(bruto * (Decimal("1") - desconto / Decimal("100")))


def order_total(itens: list[dict]) -> Decimal:
    return _money(sum((item_total(i) for i in itens), Decimal("0")))


def product_summary(itens: list[dict]) -> str:
    """Resumo derivado para `sales.product`, que continua NOT NULL e alimenta a busca."""
    if not itens:
        return "Pedido Bling"
    primeiro = itens[0].get("descricao") or "Item"
    if len(itens) == 1:
        return primeiro
    return f"{primeiro} +{len(itens) - 1} itens"


def build_installments(total: Decimal, terms: list[int], method_id: int | None,
                       sold_at: str) -> list[dict]:
    """Divide o total nas parcelas. A ULTIMA absorve o resto do arredondamento."""
    if not method_id:
        raise BlingValidationError(
            "forma de pagamento e obrigatoria",
            type_="MISSING_REQUIRED_FIELD_ERROR", status=422,
        )
    if not terms:
        raise BlingValidationError(
            "informe ao menos um prazo de pagamento",
            type_="MISSING_REQUIRED_FIELD_ERROR", status=422,
        )

    base = datetime.strptime(sold_at, "%Y-%m-%d").date()
    n = len(terms)
    valor_base = _money(total / Decimal(n))
    parcelas = []
    for i, dias in enumerate(terms):
        if i < n - 1:
            valor = valor_base
        else:
            # Fecha exato: o resto de 100/3 vai para a ultima parcela.
            valor = _money(total - valor_base * Decimal(n - 1))
        parcelas.append({
            "dataVencimento": (base + timedelta(days=int(dias))).isoformat(),
            "valor": float(valor),
            "formaPagamento": {"id": int(method_id)},
        })
    return parcelas


def build_order_payload(*, contact_id: int, sold_at: str, itens: list[dict],
                        payment: dict, seller_id: int | None,
                        discount: dict | None = None, notes: str = "",
                        internal_notes: str = "") -> dict:
    """Monta o corpo do POST /pedidos/vendas."""
    if not itens:
        raise BlingValidationError(
            "o pedido precisa de pelo menos um item",
            type_="MISSING_REQUIRED_FIELD_ERROR", status=422,
        )

    total = order_total(itens)
    payload: dict = {
        "contato": {"id": int(contact_id)},
        # O Bling exige as tres datas; sem prazo de entrega definido no CRM,
        # todas recebem a data da venda.
        "data": sold_at,
        "dataSaida": sold_at,
        "dataPrevista": sold_at,
        "itens": [
            {
                "produto": {"id": int(i["bling_product_id"])},
                "codigo": i.get("codigo") or "",
                "unidade": i.get("unidade") or "UN",
                "descricao": i["descricao"],
                "quantidade": float(_dec(i["quantidade"])),
                "valor": float(_dec(i["valor_unitario"])),
                "desconto": float(_dec(i.get("desconto_percentual"))),
            }
            for i in itens
        ],
        "parcelas": build_installments(
            total, payment.get("terms") or [0], payment.get("method_id"), sold_at
        ),
    }

    if seller_id:
        payload["vendedor"] = {"id": int(seller_id)}
    store = config.store_id()
    if store:
        payload["loja"] = {"id": store}
    situacao = config.order_situacao_id()
    if situacao:
        payload["situacao"] = {"id": situacao}
    if discount and _dec(discount.get("valor")) > 0:
        payload["desconto"] = {
            "valor": float(_dec(discount["valor"])),
            "unidade": discount.get("unidade") or "REAL",
        }
    if notes:
        payload["observacoes"] = notes
    if internal_notes:
        payload["observacoesInternas"] = internal_notes
    return payload
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `cd backend && python -m pytest tests/test_bling_orders.py -v`
Expected: PASS — 13 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/orders.py backend/tests/test_bling_orders.py
git commit -m "feat(bling): montagem do pedido e geracao de parcelas"
```

- [ ] **Step 6: Escrever os testes da criação e da projeção**

Acrescente ao mesmo arquivo `backend/tests/test_bling_orders.py`:

```python
# ---------- criacao e projecao ----------

class FakeQuery:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self.captured = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.captured.setdefault("eq", {})[col] = val
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def insert(self, payload):
        self.captured["insert"] = payload
        self.store.setdefault(self.name + "_inserts", []).append(payload)
        return self

    def update(self, payload):
        self.captured["update"] = payload
        self.store.setdefault(self.name + "_updates", []).append(payload)
        return self

    def upsert(self, payload, on_conflict=None):
        self.captured["upsert"] = payload
        self.store.setdefault(self.name + "_upserts", []).append(payload)
        self.store["on_conflict_" + self.name] = on_conflict
        return self

    def delete(self):
        self.captured["delete"] = True
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row_" + self.name, [{"id": "SALE-1"}])
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeQuery(self.store, name)


def test_create_order_persiste_venda_e_itens(monkeypatch):
    store = {}
    monkeypatch.setattr(orders, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(orders.config, "store_id", lambda: None)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: None)

    class FakeClient:
        async def post(self, path, json=None):
            assert path == "/pedidos/vendas"
            return {"data": {"id": 34215992}}

        async def get(self, path, params=None):
            assert path == "/pedidos/vendas/34215992"
            return {"data": {"id": 34215992, "numero": 1234,
                             "situacao": {"id": 6, "valor": 6}, "total": 267.0}}

    itens = [{"bling_product_id": 123, "codigo": "CAN-250", "descricao": "Cafe 250g",
              "quantidade": 10, "valor_unitario": 26.70, "desconto_percentual": 0}]

    out = asyncio.run(orders.create_order(
        FakeClient(),
        lead_id="L1", deal_id="D1", contact_id=555, sold_at="2026-08-18",
        sold_by="v@e.com", itens=itens,
        payment={"method_id": 45, "terms": [30]}, seller_id=None,
    ))

    assert out["bling_order_id"] == 34215992
    assert out["bling_order_number"] == 1234
    venda = store["sales_inserts"][0]
    assert venda["origin"] == "crm"
    assert venda["status"] == "registrada"
    assert venda["value"] == 267.0
    assert venda["product"] == "Cafe 250g"
    assert venda["bling_order_id"] == 34215992
    assert len(store["sale_items_inserts"][0]) == 1


def test_upsert_from_bling_marca_origin_bling_para_venda_nova(monkeypatch):
    store = {"row_sales": []}
    monkeypatch.setattr(orders, "get_supabase", lambda: FakeSupabase(store))

    pedido = {
        "id": 999, "numero": 77, "data": "2026-08-10", "total": 150.0,
        "contato": {"id": 555}, "situacao": {"id": 9, "valor": 9},
        "itens": [{"produto": {"id": 1}, "codigo": "A", "descricao": "Item A",
                   "quantidade": 3, "valor": 50.0, "desconto": 0}],
    }
    asyncio.run(orders.upsert_from_bling(pedido, lead_id="L1",
                                         event_date="2026-08-10T10:00:00Z"))

    linha = store["sales_upserts"][0]
    assert linha["origin"] == "bling"
    assert linha["bling_order_id"] == 999
    assert linha["deal_id"] is None, "venda vinda do ERP entra sem deal (decisao D7)"
    assert store["on_conflict_sales"] == "bling_order_id"


def test_upsert_from_bling_preserva_origin_crm_de_venda_existente(monkeypatch):
    store = {"row_sales": [{"id": "SALE-1", "origin": "crm", "deal_id": "D1"}]}
    monkeypatch.setattr(orders, "get_supabase", lambda: FakeSupabase(store))

    pedido = {"id": 999, "numero": 77, "data": "2026-08-10", "total": 150.0,
              "contato": {"id": 555}, "situacao": {"id": 9}, "itens": []}
    asyncio.run(orders.upsert_from_bling(pedido, lead_id="L1",
                                         event_date="2026-08-10T10:00:00Z"))

    linha = store["sales_upserts"][0]
    assert linha["origin"] == "crm", "o webhook de volta nao pode reescrever a origem"
    assert linha["deal_id"] == "D1"


def test_cancel_marca_status_sem_apagar(monkeypatch):
    store = {}
    monkeypatch.setattr(orders, "get_supabase", lambda: FakeSupabase(store))
    asyncio.run(orders.cancel_from_bling(999, event_date="2026-08-11T10:00:00Z"))
    assert store["sales_updates"][0]["status"] == "cancelada"
```

- [ ] **Step 7: Rodar e confirmar que falham**

Run: `cd backend && python -m pytest tests/test_bling_orders.py -k "create_order or upsert_from_bling or cancel" -v`
Expected: FAIL — `AttributeError: module 'app.bling.orders' has no attribute 'create_order'`

- [ ] **Step 8: Implementar a criação e a projeção**

Acrescente ao fim de `backend/app/bling/orders.py`:

```python
# --------------------------------------------------------------------------
# Criacao e projecao em sales
# --------------------------------------------------------------------------
import asyncio  # noqa: E402 — agrupado aqui para manter as funcoes puras acima isoladas

from app.db.supabase import get_supabase  # noqa: E402


def _map_bling_items(pedido: dict) -> list[dict]:
    """Traduz itens do pedido do Bling para linhas de `sale_items`."""
    saida = []
    for ordem, item in enumerate(pedido.get("itens") or []):
        quantidade = _dec(item.get("quantidade"))
        valor = _dec(item.get("valor"))
        desconto = _dec(item.get("desconto"))
        total = _money(quantidade * valor * (Decimal("1") - desconto / Decimal("100")))
        saida.append({
            "bling_product_id": (item.get("produto") or {}).get("id"),
            "codigo": item.get("codigo") or None,
            "descricao": item.get("descricao") or "Item",
            "quantidade": float(quantidade),
            "valor_unitario": float(valor),
            "desconto_percentual": float(desconto),
            "total": float(total),
            "ordem": ordem,
        })
    return saida


def _insert_sale(row: dict) -> str:
    res = get_supabase().table("sales").insert(row).execute()
    return (getattr(res, "data", None) or [{}])[0].get("id")


def _insert_items(sale_id: str, itens: list[dict]) -> None:
    if not itens:
        return
    linhas = [{**i, "sale_id": sale_id} for i in itens]
    get_supabase().table("sale_items").insert(linhas).execute()


async def create_order(client, *, lead_id: str, deal_id: str | None, contact_id: int,
                       sold_at: str, sold_by: str | None, itens: list[dict],
                       payment: dict, seller_id: int | None,
                       discount: dict | None = None, notes: str = "") -> dict:
    """Cria o pedido no Bling e projeta em `sales` + `sale_items`."""
    payload = build_order_payload(
        contact_id=contact_id, sold_at=sold_at, itens=itens, payment=payment,
        seller_id=seller_id, discount=discount, notes=notes,
        internal_notes=f"CRM lead {lead_id}" + (f" - deal {deal_id}" if deal_id else ""),
    )

    criado = await client.post("/pedidos/vendas", payload)
    order_id = int((criado.get("data") or {})["id"])

    # O POST devolve so o id. `numero` e `situacao` resolvidos vem no GET.
    detalhe = (await client.get(f"/pedidos/vendas/{order_id}")).get("data") or {}

    total = order_total(itens)
    linha = {
        "lead_id": lead_id,
        "deal_id": deal_id,
        "sold_at": f"{sold_at}T12:00:00+00:00",
        "value": float(total),
        "product": product_summary(itens),
        "sold_by": sold_by,
        "origin": "crm",
        "status": "registrada",
        "bling_order_id": order_id,
        "bling_order_number": detalhe.get("numero"),
        "bling_situacao_id": (detalhe.get("situacao") or {}).get("id"),
        "payment_method_id": payment.get("method_id"),
        "payment_terms": "/".join(str(d) for d in (payment.get("terms") or [0])),
        "notes": notes or None,
    }
    sale_id = await asyncio.to_thread(_insert_sale, linha)
    await asyncio.to_thread(_insert_items, sale_id, [
        {
            "bling_product_id": i["bling_product_id"],
            "codigo": i.get("codigo"),
            "descricao": i["descricao"],
            "quantidade": float(_dec(i["quantidade"])),
            "valor_unitario": float(_dec(i["valor_unitario"])),
            "desconto_percentual": float(_dec(i.get("desconto_percentual"))),
            "total": float(item_total(i)),
            "ordem": ordem,
        }
        for ordem, i in enumerate(itens)
    ])

    logger.info("[BLING] pedido %s (numero %s) criado para o lead %s",
                order_id, detalhe.get("numero"), lead_id)
    return {
        "sale_id": sale_id,
        "bling_order_id": order_id,
        "bling_order_number": detalhe.get("numero"),
    }


def _existing_sale(order_id: int) -> dict | None:
    res = (get_supabase().table("sales").select("id, origin, deal_id, lead_id")
           .eq("bling_order_id", order_id).limit(1).execute())
    linhas = getattr(res, "data", None) or []
    return linhas[0] if linhas else None


def _upsert_sale(row: dict) -> str | None:
    res = (get_supabase().table("sales")
           .upsert(row, on_conflict="bling_order_id").execute())
    return (getattr(res, "data", None) or [{}])[0].get("id")


def _replace_items(sale_id: str, itens: list[dict]) -> None:
    get_supabase().table("sale_items").delete().eq("sale_id", sale_id).execute()
    if itens:
        get_supabase().table("sale_items").insert(
            [{**i, "sale_id": sale_id} for i in itens]).execute()


async def upsert_from_bling(pedido: dict, *, lead_id: str | None,
                            event_date: str | None) -> str | None:
    """Projeta um pedido do Bling em `sales` (webhook e backfill).

    O UNIQUE em `bling_order_id` faz o pedido que o CRM acabou de criar casar com
    a linha ja gravada — nao duplica quando o webhook volta.
    """
    order_id = int(pedido["id"])
    existente = await asyncio.to_thread(_existing_sale, order_id)

    linha = {
        "bling_order_id": order_id,
        "lead_id": (existente or {}).get("lead_id") or lead_id,
        # Venda vinda do ERP entra sem deal (D7); venda do CRM mantem o dela.
        "deal_id": (existente or {}).get("deal_id"),
        "sold_at": f"{pedido.get('data')}T12:00:00+00:00",
        "value": float(_dec(pedido.get("total"))),
        "product": product_summary(_map_bling_items(pedido)),
        # A origem e imutavel depois de definida: o webhook de volta nao pode
        # reescrever 'crm' para 'bling'.
        "origin": (existente or {}).get("origin") or "bling",
        "status": "registrada",
        "bling_order_number": pedido.get("numero"),
        "bling_situacao_id": (pedido.get("situacao") or {}).get("id"),
        "bling_event_date": event_date,
    }
    sale_id = await asyncio.to_thread(_upsert_sale, linha)
    if sale_id:
        await asyncio.to_thread(_replace_items, sale_id, _map_bling_items(pedido))
    return sale_id


def _update_sale(order_id: int, payload: dict) -> None:
    (get_supabase().table("sales").update(payload)
     .eq("bling_order_id", order_id).execute())


async def cancel_from_bling(order_id: int, *, event_date: str | None) -> None:
    """`order.deleted`: marca cancelada, preserva linha e itens."""
    await asyncio.to_thread(_update_sale, int(order_id), {
        "status": "cancelada", "bling_event_date": event_date,
    })
```

- [ ] **Step 9: Rodar a suíte do módulo e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_orders.py -v`
Expected: PASS — 17 passed

- [ ] **Step 10: Commit**

```bash
git add backend/app/bling/orders.py backend/tests/test_bling_orders.py
git commit -m "feat(bling): criacao de pedido e projecao em sales"
```

---

### Task 10: Outbox (`bling_jobs`) e drain no worker

**Files:**
- Create: `backend/app/bling/jobs.py`
- Modify: `backend/app/worker/main.py`
- Test: `backend/tests/test_bling_jobs.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
# backend/tests/test_bling_jobs.py
import asyncio

import app.bling.jobs as jobs
from app.bling.errors import BlingServerError, BlingValidationError


class FakeQuery:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def lte(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.store.setdefault(self.name + "_inserts", []).append(payload)
        return self

    def update(self, payload):
        self.store.setdefault(self.name + "_updates", []).append(payload)
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row_" + self.name, [])
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeQuery(self.store, name)


def test_enqueue_grava_job_pendente(monkeypatch):
    store = {}
    monkeypatch.setattr(jobs, "get_supabase", lambda: FakeSupabase(store))

    asyncio.run(jobs.enqueue("create_order", {"lead_id": "L1"}, sale_id="S1"))

    job = store["bling_jobs_inserts"][0]
    assert job["kind"] == "create_order"
    assert job["status"] == "pending"
    assert job["sale_id"] == "S1"


def test_drain_marca_done_no_sucesso(monkeypatch):
    store = {"row_bling_jobs": [{"id": "J1", "kind": "create_order",
                                 "payload": {"lead_id": "L1"}, "attempts": 0}]}
    monkeypatch.setattr(jobs, "get_supabase", lambda: FakeSupabase(store))

    async def handler(payload, job):
        return {"ok": True}

    monkeypatch.setattr(jobs, "_HANDLERS", {"create_order": handler})

    asyncio.run(jobs.drain())

    assert store["bling_jobs_updates"][0]["status"] == "done"


def test_erro_transitorio_reagenda_com_backoff(monkeypatch):
    store = {"row_bling_jobs": [{"id": "J1", "kind": "create_order",
                                 "payload": {}, "attempts": 1}]}
    monkeypatch.setattr(jobs, "get_supabase", lambda: FakeSupabase(store))

    async def handler(payload, job):
        raise BlingServerError("bling fora do ar")

    monkeypatch.setattr(jobs, "_HANDLERS", {"create_order": handler})

    asyncio.run(jobs.drain())

    upd = store["bling_jobs_updates"][0]
    assert upd["status"] == "pending"
    assert upd["attempts"] == 2
    assert upd["run_after"] > ""


def test_erro_de_validacao_marca_failed_sem_retentar(monkeypatch):
    """Repetir um payload invalido nunca conserta e ainda queima orcamento."""
    store = {"row_bling_jobs": [{"id": "J1", "kind": "create_order",
                                 "payload": {}, "attempts": 0}]}
    monkeypatch.setattr(jobs, "get_supabase", lambda: FakeSupabase(store))

    async def handler(payload, job):
        raise BlingValidationError("itens invalidos")

    monkeypatch.setattr(jobs, "_HANDLERS", {"create_order": handler})

    asyncio.run(jobs.drain())

    upd = store["bling_jobs_updates"][0]
    assert upd["status"] == "failed"
    assert "itens invalidos" in upd["last_error"]


def test_desiste_apos_o_maximo_de_tentativas(monkeypatch):
    store = {"row_bling_jobs": [{"id": "J1", "kind": "create_order",
                                 "payload": {}, "attempts": jobs.MAX_ATTEMPTS - 1}]}
    monkeypatch.setattr(jobs, "get_supabase", lambda: FakeSupabase(store))

    async def handler(payload, job):
        raise BlingServerError("ainda fora")

    monkeypatch.setattr(jobs, "_HANDLERS", {"create_order": handler})

    asyncio.run(jobs.drain())

    assert store["bling_jobs_updates"][0]["status"] == "failed"


def test_worker_registra_o_drain():
    from app.worker.main import TASK_SPECS
    spec = next(s for s in TASK_SPECS if s[0] == "bling-jobs")
    assert spec[1] == "periodic"
    assert spec[3] == 30
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `cd backend && python -m pytest tests/test_bling_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.jobs'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/jobs.py
"""Outbox da integracao: o que nao entrou sincrono entra pela fila.

O caminho feliz do modal de venda e SINCRONO — o vendedor precisa ver o numero
do pedido na hora, senao ele abre o Bling para conferir e a dor volta. A fila
existe so para o caminho triste: Bling fora do ar, 429, timeout.

Erro de VALIDACAO nunca entra aqui: repetir o mesmo payload invalido nao
conserta e ainda conta para o bloqueio de IP (300 erros em 10s).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.bling import config
from app.bling.errors import TRANSIENT
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
BATCH = 10
# Backoff exponencial limitado a 30 min: 1, 2, 4, 8, 16, 30, 30, 30 minutos.
_BACKOFF_MINUTES = (1, 2, 4, 8, 16, 30, 30, 30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _insert(row: dict) -> None:
    get_supabase().table("bling_jobs").insert(row).execute()


async def enqueue(kind: str, payload: dict, *, sale_id: str | None = None) -> None:
    await asyncio.to_thread(_insert, {
        "kind": kind,
        "payload": payload,
        "status": "pending",
        "attempts": 0,
        "sale_id": sale_id,
        "run_after": _now().isoformat(),
    })
    logger.info("[BLING JOBS] enfileirado %s (sale=%s)", kind, sale_id)


def _claim() -> list[dict]:
    res = (get_supabase().table("bling_jobs")
           .select("*").eq("status", "pending")
           .lte("run_after", _now().isoformat())
           .order("run_after").limit(BATCH).execute())
    return getattr(res, "data", None) or []


def _update(job_id: str, payload: dict) -> None:
    get_supabase().table("bling_jobs").update(payload).eq("id", job_id).execute()


async def _handle_create_order(payload: dict, job: dict) -> dict:
    """Retenta a criacao do pedido e casa com a `sales` que ja existe."""
    from app.bling.client import BlingClient
    from app.bling.orders import create_order

    async with BlingClient() as client:
        return await create_order(client, **payload)


_HANDLERS = {"create_order": _handle_create_order}


async def drain() -> int:
    """Processa um lote de jobs pendentes. Devolve quantos foram concluidos."""
    pendentes = await asyncio.to_thread(_claim)
    concluidos = 0

    for job in pendentes:
        handler = _HANDLERS.get(job["kind"])
        if handler is None:
            await asyncio.to_thread(_update, job["id"], {
                "status": "failed",
                "last_error": f"kind desconhecido: {job['kind']}",
            })
            continue

        tentativas = int(job.get("attempts") or 0) + 1
        try:
            await handler(job.get("payload") or {}, job)
        except TRANSIENT as exc:
            if tentativas >= MAX_ATTEMPTS:
                await asyncio.to_thread(_update, job["id"], {
                    "status": "failed", "attempts": tentativas, "last_error": str(exc),
                })
                logger.error("[BLING JOBS] job %s desistiu apos %d tentativas: %s",
                             job["id"], tentativas, exc)
                continue
            atraso = _BACKOFF_MINUTES[min(tentativas - 1, len(_BACKOFF_MINUTES) - 1)]
            await asyncio.to_thread(_update, job["id"], {
                "status": "pending", "attempts": tentativas, "last_error": str(exc),
                "run_after": (_now() + timedelta(minutes=atraso)).isoformat(),
            })
        except Exception as exc:  # noqa: BLE001 — validacao e qualquer outro: nao retenta
            await asyncio.to_thread(_update, job["id"], {
                "status": "failed", "attempts": tentativas, "last_error": str(exc),
            })
            logger.error("[BLING JOBS] job %s falhou definitivamente: %s", job["id"], exc)
        else:
            # `bling_jobs` nao tem processed_at (so bling_webhook_events tem);
            # updated_at e mantido pelo trigger da migration.
            await asyncio.to_thread(_update, job["id"], {
                "status": "done", "attempts": tentativas,
            })
            concluidos += 1

    return concluidos


async def bling_jobs_tick() -> None:
    if not config.enabled():
        return
    try:
        await drain()
    except Exception as exc:  # noqa: BLE001 — worker nunca morre por causa do Bling
        logger.warning("[BLING JOBS] drain falhou: %s", exc)
```

- [ ] **Step 4: Registrar o drain no worker**

Em `backend/app/worker/main.py`, junto das outras `_*_tick`:

```python
async def _bling_jobs_tick() -> None:
    from app.bling.jobs import bling_jobs_tick
    await bling_jobs_tick()
```

E em `TASK_SPECS`, logo após `("bling-sync", ...)`:

```python
    ("bling-jobs", "periodic", _bling_jobs_tick, 30),
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_jobs.py -v`
Expected: PASS — 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/jobs.py backend/app/worker/main.py backend/tests/test_bling_jobs.py
git commit -m "feat(bling): outbox de pedidos com backoff no worker"
```

---

## Fase 5 — Webhook (ERP → CRM)

### Task 11: Receiver com HMAC e ack rápido

**Files:**
- Create: `backend/app/bling/webhook_router.py`
- Modify: `backend/app/main.py` (registrar o router)
- Modify: `backend/app/events/bus.py` (acrescentar `"bling-webhook"` a `DOMAINS`)
- Test: `backend/tests/test_bling_webhook.py`

> `DOMAINS` em `app/events/bus.py` é allow-list fechada. Sem acrescentar
> `"bling-webhook"` ali, `emit_event` recusa o domínio, devolve `False`, e o
> wake-up nunca dispara — os eventos ficariam esperando a varredura de fallback
> de 60s. O nome tem que ser idêntico ao da task em `TASK_SPECS`, porque
> `run_event_driven(name, fn, name, seconds)` usa o nome como stream.

- [ ] **Step 1: Escrever os testes que falham**

```python
# backend/tests/test_bling_webhook.py
import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.bling.webhook_router as wr

SECRET = "csec-super-secreto"


def _assinar(corpo: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), corpo, hashlib.sha256).hexdigest()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("BLING_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("BLING_ENABLED", "true")
    app = FastAPI()
    app.include_router(wr.router)
    return TestClient(app)


@pytest.fixture
def gravados(monkeypatch):
    linhas = []

    def fake_insert(row):
        # ON CONFLICT DO NOTHING: event_id repetido nao grava de novo
        if any(l["event_id"] == row["event_id"] for l in linhas):
            return False
        linhas.append(row)
        return True

    monkeypatch.setattr(wr, "_insert_event", fake_insert)

    async def noop_publish():
        return None

    monkeypatch.setattr(wr, "_notify_worker", noop_publish)
    return linhas


EVENTO = {
    "eventId": "01945027-150e-72b4-e7cf-4943a042cd9c",
    "date": "2026-08-18T12:18:46Z",
    "version": "v1",
    "event": "order.created",
    "companyId": "d4475854366a36c86a37e792f9634a51",
    "data": {"id": 34215992, "numero": 1234, "total": 267.0,
             "contato": {"id": 5845664414}, "situacao": {"id": 6, "valor": 6}},
}


def test_assinatura_valida_e_aceita(client, gravados):
    corpo = json.dumps(EVENTO).encode()
    resp = client.post("/webhook/bling", content=corpo,
                       headers={"X-Bling-Signature-256": _assinar(corpo),
                                "Content-Type": "application/json"})
    assert resp.status_code == 200
    assert gravados[0]["event"] == "order.created"
    assert gravados[0]["status"] == "pending"


def test_assinatura_invalida_e_rejeitada(client, gravados):
    corpo = json.dumps(EVENTO).encode()
    resp = client.post("/webhook/bling", content=corpo,
                       headers={"X-Bling-Signature-256": "sha256=" + "0" * 64,
                                "Content-Type": "application/json"})
    assert resp.status_code == 401
    assert gravados == []


def test_assinatura_ausente_e_rejeitada(client, gravados):
    corpo = json.dumps(EVENTO).encode()
    resp = client.post("/webhook/bling", content=corpo,
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 401


def test_hmac_e_sobre_os_BYTES_CRUS(client, gravados):
    """Reserializar o JSON muda os bytes e quebraria a assinatura. O receiver
    tem que hashear o corpo exatamente como chegou."""
    corpo = b'{"eventId":"e1","date":"2026-08-18T12:00:00Z","event":"order.created","data":{"id":1}}'
    resp = client.post("/webhook/bling", content=corpo,
                       headers={"X-Bling-Signature-256": _assinar(corpo),
                                "Content-Type": "application/json"})
    assert resp.status_code == 200


def test_evento_repetido_devolve_200_e_nao_duplica(client, gravados):
    """Idempotencia: o Bling pode reenviar; ambas as chamadas tem que dar 2xx."""
    corpo = json.dumps(EVENTO).encode()
    headers = {"X-Bling-Signature-256": _assinar(corpo),
               "Content-Type": "application/json"}
    assert client.post("/webhook/bling", content=corpo, headers=headers).status_code == 200
    assert client.post("/webhook/bling", content=corpo, headers=headers).status_code == 200
    assert len(gravados) == 1


def test_nao_faz_io_com_o_bling_dentro_do_request(client, gravados, monkeypatch):
    """O Bling exige 2xx em ate 5s, senao retenta por 3 dias e DESABILITA o
    webhook. Buscar o pedido completo aqui arriscaria estourar o prazo."""
    chamou = []

    class Explode:
        def __init__(self, *a, **k):
            chamou.append(True)
            raise AssertionError("o receiver nao pode instanciar BlingClient")

    monkeypatch.setattr("app.bling.client.BlingClient", Explode)
    corpo = json.dumps(EVENTO).encode()
    resp = client.post("/webhook/bling", content=corpo,
                       headers={"X-Bling-Signature-256": _assinar(corpo),
                                "Content-Type": "application/json"})
    assert resp.status_code == 200
    assert chamou == []


def test_router_registrado_no_app():
    from app.main import app as fastapi_app
    rotas = {getattr(r, "path", "") for r in fastapi_app.routes}
    assert "/webhook/bling" in rotas
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `cd backend && python -m pytest tests/test_bling_webhook.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.webhook_router'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/webhook_router.py
"""Receiver dos webhooks do Bling.

REGRA DE OURO: responder 2xx em ate 5 SEGUNDOS. Passou disso, o Bling retenta
por ate 3 dias e depois DESABILITA a configuracao do webhook — a integracao
para em silencio ate alguem reabilitar na mao no painel.

Por isso o receiver so faz tres coisas: valida a assinatura, grava o evento e
devolve 200. Buscar o pedido completo (`GET /pedidos/vendas/{id}`, necessario
porque o payload do webhook nao traz itens) acontece no worker.
"""
import asyncio
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Request, Response

from app.bling import config
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bling"])

_SIG_HEADER = "x-bling-signature-256"
_PREFIX = "sha256="


def verify_signature(corpo: bytes, header: str | None, secret: str) -> bool:
    """HMAC-SHA256 hex do corpo CRU com o client_secret do aplicativo."""
    if not header or not header.startswith(_PREFIX) or not secret:
        return False
    esperado = hmac.new(secret.encode("utf-8"), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, header[len(_PREFIX):])


def _insert_event(row: dict) -> bool:
    """Insere o evento. False se o event_id ja existia (repeticao do Bling)."""
    try:
        res = get_supabase().table("bling_webhook_events").insert(row).execute()
        return bool(getattr(res, "data", None))
    except Exception as exc:  # noqa: BLE001 — violacao de PK e o caminho esperado
        if "duplicate key" in str(exc).lower() or "23505" in str(exc):
            return False
        raise


async def _notify_worker() -> None:
    """Acorda o tick de processamento (o worker tambem varre por fallback).

    `emit_event` e SINCRONA e faz I/O no Redis — precisa de to_thread para nao
    bloquear o event loop dentro do request, que tem 5s de orcamento.

    O dominio e o NOME DA TASK no worker ("bling-webhook", com hifen), porque
    run_event_driven em app/worker/main.py usa o nome como stream. E o dominio
    precisa estar em bus.DOMAINS, que e allow-list fechada: fora dela,
    emit_event recusa e devolve False sem emitir nada.
    """
    try:
        from app.events.bus import emit_event
        await asyncio.to_thread(emit_event, "bling-webhook")
    except Exception:  # noqa: BLE001 — o fallback periodico cobre
        pass


@router.post("/webhook/bling")
async def bling_webhook(request: Request) -> Response:
    corpo = await request.body()

    if not verify_signature(corpo, request.headers.get(_SIG_HEADER),
                            config.client_secret()):
        logger.warning("[BLING WEBHOOK] assinatura invalida — descartado")
        return Response(status_code=401)

    try:
        evento = json.loads(corpo)
    except Exception:  # noqa: BLE001
        # Corpo ilegivel com assinatura valida nao deve virar retentativa eterna.
        logger.error("[BLING WEBHOOK] corpo nao e JSON valido")
        return Response(status_code=200)

    event_id = evento.get("eventId")
    if not event_id:
        logger.error("[BLING WEBHOOK] evento sem eventId: %s", evento.get("event"))
        return Response(status_code=200)

    novo = await asyncio.to_thread(_insert_event, {
        "event_id": event_id,
        "event": evento.get("event") or "",
        "payload": evento,
        "event_date": evento.get("date"),
        "status": "pending",
    })

    if novo:
        await _notify_worker()
    else:
        logger.info("[BLING WEBHOOK] evento %s repetido — absorvido", event_id)

    # Sempre 200: repeticao tambem precisa de 2xx (contrato de idempotencia).
    return Response(status_code=200)
```

- [ ] **Step 4: Registrar o router**

Em `backend/app/main.py`, junto dos outros imports de router, adicione:

```python
from app.bling.webhook_router import router as bling_webhook_router
```

E na lista de `include_router`, depois de `app.include_router(lp_webhook_router)`:

```python
app.include_router(bling_webhook_router)
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_webhook.py -v`
Expected: PASS — 7 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/webhook_router.py backend/app/main.py backend/tests/test_bling_webhook.py
git commit -m "feat(bling): receiver de webhook com HMAC e ack em menos de 5s"
```

---

### Task 12: Processamento assíncrono dos eventos

**Files:**
- Create: `backend/app/bling/webhook_processor.py`
- Modify: `backend/app/worker/main.py`
- Test: `backend/tests/test_bling_webhook_processor.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
# backend/tests/test_bling_webhook_processor.py
import asyncio

import app.bling.webhook_processor as wp


class FakeQuery:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.store.setdefault("eq_" + self.name, {})[col] = val
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def update(self, payload):
        self.store.setdefault(self.name + "_updates", []).append(payload)
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row_" + self.name, [])
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeQuery(self.store, name)


class FakeClient:
    def __init__(self, pedido):
        self.pedido = pedido
        self.gets = []

    async def get(self, path, params=None):
        self.gets.append(path)
        return {"data": self.pedido}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


PEDIDO = {"id": 34215992, "numero": 1234, "data": "2026-08-18", "total": 267.0,
          "contato": {"id": 5845664414}, "situacao": {"id": 6},
          "itens": [{"produto": {"id": 123}, "codigo": "CAN-250",
                     "descricao": "Cafe 250g", "quantidade": 10,
                     "valor": 26.70, "desconto": 0}]}


def _evento(event="order.created", date="2026-08-18T12:00:00Z", data=None):
    return {"event_id": "E1", "event": event, "event_date": date, "attempts": 0,
            "payload": {"event": event, "date": date,
                        "data": data or {"id": 34215992, "contato": {"id": 5845664414}}}}


def test_created_busca_o_pedido_completo_e_projeta(monkeypatch):
    """O payload do webhook nao traz itens — o GET e obrigatorio."""
    store = {"row_bling_webhook_events": [_evento()]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))
    client = FakeClient(PEDIDO)
    monkeypatch.setattr(wp, "_new_client", lambda: client)

    projetados = []

    async def fake_upsert(pedido, lead_id, event_date):
        projetados.append((pedido["id"], lead_id, event_date))
        return "SALE-1"

    async def fake_ensure_lead(contato):
        return "LEAD-1"

    async def fake_last_event(order_id):
        return None

    monkeypatch.setattr(wp, "upsert_from_bling", fake_upsert)
    monkeypatch.setattr(wp, "_resolve_lead", fake_ensure_lead)
    monkeypatch.setattr(wp, "_last_event_date", fake_last_event)

    asyncio.run(wp.process_pending())

    assert client.gets == ["/pedidos/vendas/34215992"]
    assert projetados == [(34215992, "LEAD-1", "2026-08-18T12:00:00Z")]
    assert store["bling_webhook_events_updates"][0]["status"] == "done"


def test_evento_fora_de_ordem_e_descartado(monkeypatch):
    """A entrega do Bling nao e ordenada: um `updated` antigo pode chegar depois
    de um mais novo e reverteria a situacao do pedido."""
    store = {"row_bling_webhook_events": [_evento(date="2026-08-18T10:00:00Z")]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(wp, "_new_client", lambda: FakeClient(PEDIDO))

    async def fake_last_event(order_id):
        return "2026-08-18T12:00:00Z"   # ja aplicamos um evento mais novo

    chamou = []

    async def fake_upsert(*a, **k):
        chamou.append(True)

    monkeypatch.setattr(wp, "_last_event_date", fake_last_event)
    monkeypatch.setattr(wp, "upsert_from_bling", fake_upsert)

    asyncio.run(wp.process_pending())

    assert chamou == []
    assert store["bling_webhook_events_updates"][0]["status"] == "skipped"


def test_deleted_cancela_sem_buscar_o_pedido(monkeypatch):
    store = {"row_bling_webhook_events": [
        _evento(event="order.deleted", data={"id": 34215992})]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))
    client = FakeClient(PEDIDO)
    monkeypatch.setattr(wp, "_new_client", lambda: client)

    cancelados = []

    async def fake_cancel(order_id, event_date):
        cancelados.append(order_id)

    async def fake_last_event(order_id):
        return None

    monkeypatch.setattr(wp, "cancel_from_bling", fake_cancel)
    monkeypatch.setattr(wp, "_last_event_date", fake_last_event)

    asyncio.run(wp.process_pending())

    assert cancelados == [34215992]
    assert client.gets == [], "deleted nao precisa buscar o pedido"


def test_product_event_atualiza_o_espelho(monkeypatch):
    store = {"row_bling_webhook_events": [
        {"event_id": "E2", "event": "product.updated", "attempts": 0,
         "event_date": "2026-08-18T12:00:00Z",
         "payload": {"event": "product.updated", "date": "2026-08-18T12:00:00Z",
                     "data": {"id": 123, "nome": "Cafe", "situacao": "A"}}}]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))
    aplicados = []

    async def fake_apply(event, payload):
        aplicados.append((event, payload["id"]))

    monkeypatch.setattr(wp, "apply_product_event", fake_apply)

    asyncio.run(wp.process_pending())

    assert aplicados == [("product.updated", 123)]


def test_falha_incrementa_attempts_e_mantem_pending(monkeypatch):
    store = {"row_bling_webhook_events": [_evento()]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))

    def explode():
        raise RuntimeError("bling fora")

    monkeypatch.setattr(wp, "_new_client", lambda: explode())

    asyncio.run(wp.process_pending())

    upd = store["bling_webhook_events_updates"][0]
    assert upd["status"] == "pending"
    assert upd["attempts"] == 1


def test_desiste_apos_o_maximo_de_tentativas(monkeypatch):
    evt = _evento()
    evt["attempts"] = wp.MAX_ATTEMPTS - 1
    store = {"row_bling_webhook_events": [evt]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))

    def explode():
        raise RuntimeError("bling fora")

    monkeypatch.setattr(wp, "_new_client", lambda: explode())

    asyncio.run(wp.process_pending())

    assert store["bling_webhook_events_updates"][0]["status"] == "failed"


def test_worker_registra_o_tick_de_webhook():
    from app.worker.main import TASK_SPECS
    spec = next(s for s in TASK_SPECS if s[0] == "bling-webhook")
    assert spec[1] == "event"
    assert spec[3] == 60
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `cd backend && python -m pytest tests/test_bling_webhook_processor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.webhook_processor'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/webhook_processor.py
"""Processa os eventos que o receiver gravou.

Fica fora do request porque o Bling exige 2xx em 5s e aqui precisamos de
`GET /pedidos/vendas/{id}` — o payload do webhook nao traz os itens do pedido.

Duas garantias que este modulo implementa:
  - Idempotencia ja veio do receiver (event_id e PK).
  - ORDEM: a entrega do Bling nao e ordenada. Um `order.updated` antigo pode
    chegar depois de um mais novo e reverteria a situacao do pedido. Comparamos
    `event_date` com o `bling_event_date` ja gravado na venda e descartamos o
    atrasado.
"""
import asyncio
import logging
from datetime import datetime, timezone

from app.bling import config
from app.bling.orders import cancel_from_bling, upsert_from_bling
from app.bling.products import apply_product_event
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
BATCH = 20


def _new_client():
    from app.bling.client import BlingClient
    return BlingClient()


def _claim() -> list[dict]:
    res = (get_supabase().table("bling_webhook_events")
           .select("*").eq("status", "pending")
           .order("received_at").limit(BATCH).execute())
    return getattr(res, "data", None) or []


def _update(event_id: str, payload: dict) -> None:
    (get_supabase().table("bling_webhook_events").update(payload)
     .eq("event_id", event_id).execute())


def _sale_event_date(order_id: int) -> str | None:
    res = (get_supabase().table("sales").select("bling_event_date")
           .eq("bling_order_id", order_id).limit(1).execute())
    linhas = getattr(res, "data", None) or []
    return (linhas[0] or {}).get("bling_event_date") if linhas else None


async def _last_event_date(order_id: int) -> str | None:
    return await asyncio.to_thread(_sale_event_date, order_id)


def _contact_row(contact_id: int) -> dict | None:
    res = (get_supabase().table("bling_contacts").select("*")
           .eq("id", contact_id).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


async def _resolve_lead(contato: dict) -> str | None:
    from app.bling.contacts import ensure_lead
    return await ensure_lead(contato)


async def _handle_order(evento: dict, corpo: dict) -> str:
    dados = corpo.get("data") or {}
    order_id = int(dados["id"])
    event_date = corpo.get("date") or evento.get("event_date")

    anterior = await _last_event_date(order_id)
    if anterior and event_date and event_date < anterior:
        logger.info("[BLING WEBHOOK] evento %s fora de ordem (%s < %s) — descartado",
                    evento["event_id"], event_date, anterior)
        return "skipped"

    if evento["event"].endswith(".deleted"):
        await cancel_from_bling(order_id, event_date=event_date)
        return "done"

    async with _new_client() as client:
        pedido = (await client.get(f"/pedidos/vendas/{order_id}")).get("data") or {}

    contact_id = (pedido.get("contato") or dados.get("contato") or {}).get("id")
    lead_id = None
    if contact_id:
        contato = await asyncio.to_thread(_contact_row, int(contact_id))
        if contato:
            lead_id = await _resolve_lead(contato)
        else:
            logger.warning("[BLING WEBHOOK] contato %s ausente do espelho", contact_id)

    await upsert_from_bling(pedido, lead_id=lead_id, event_date=event_date)
    return "done"


async def _handle_product(evento: dict, corpo: dict) -> str:
    await apply_product_event(evento["event"], corpo.get("data") or {})
    return "done"


async def process_pending() -> int:
    """Processa um lote de eventos pendentes. Devolve quantos concluiram."""
    pendentes = await asyncio.to_thread(_claim)
    concluidos = 0

    for evento in pendentes:
        corpo = evento.get("payload") or {}
        nome = evento.get("event") or ""
        tentativas = int(evento.get("attempts") or 0) + 1

        try:
            if nome.startswith("order."):
                status = await _handle_order(evento, corpo)
            elif nome.startswith("product."):
                status = await _handle_product(evento, corpo)
            else:
                logger.info("[BLING WEBHOOK] recurso nao tratado: %s", nome)
                status = "skipped"
        except Exception as exc:  # noqa: BLE001
            if tentativas >= MAX_ATTEMPTS:
                await asyncio.to_thread(_update, evento["event_id"], {
                    "status": "failed", "attempts": tentativas, "last_error": str(exc),
                })
                logger.error("[BLING WEBHOOK] evento %s desistiu: %s",
                             evento["event_id"], exc)
            else:
                await asyncio.to_thread(_update, evento["event_id"], {
                    "status": "pending", "attempts": tentativas, "last_error": str(exc),
                })
            continue

        await asyncio.to_thread(_update, evento["event_id"], {
            "status": status, "attempts": tentativas,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        })
        if status == "done":
            concluidos += 1

    return concluidos


async def bling_webhook_tick() -> None:
    if not config.enabled():
        return
    try:
        await process_pending()
    except Exception as exc:  # noqa: BLE001 — worker nunca morre por causa do Bling
        logger.warning("[BLING WEBHOOK] processamento falhou: %s", exc)
```

- [ ] **Step 4: Registrar o tick no worker**

Em `backend/app/worker/main.py`:

```python
async def _bling_webhook_tick() -> None:
    from app.bling.webhook_processor import bling_webhook_tick
    await bling_webhook_tick()
```

E em `TASK_SPECS`, depois de `("bling-jobs", ...)`:

```python
    ("bling-webhook", "event", _bling_webhook_tick, 60),
```

É `"event"` (não `"periodic"`) porque o receiver publica no event bus — o processamento
acorda na hora, com varredura de fallback a cada 60s.

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_webhook_processor.py -v`
Expected: PASS — 7 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/webhook_processor.py backend/app/worker/main.py backend/tests/test_bling_webhook_processor.py
git commit -m "feat(bling): processamento de eventos com guarda de ordem"
```

---

## Fase 6 — API do backend

### Task 13: Router `/api/bling/*`

**Files:**
- Create: `backend/app/bling/router.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_bling_router.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
# backend/tests/test_bling_router.py
import asyncio

import pytest

import app.bling.router as br
from app.bling.contacts import Resolution
from app.bling.errors import BlingServerError, BlingValidationError


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.captured = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self.captured.setdefault("eq", {})[c] = v
        return self

    def or_(self, expr):
        self.captured["or"] = expr
        return self

    def ilike(self, c, v):
        self.captured["ilike"] = (c, v)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.rows
        return r


class FakeSupabase:
    def __init__(self, por_tabela):
        self.por_tabela = por_tabela
        self.queries = []

    def table(self, name):
        q = FakeQuery(self.por_tabela.get(name, []))
        self.queries.append(q)
        return q


def test_products_filtra_por_ativos_e_busca(monkeypatch):
    sb = FakeSupabase({"bling_products": [{"id": 1, "nome": "Cafe Classico 250g"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    out = asyncio.run(br.list_products(q="classico"))

    assert out["data"][0]["nome"] == "Cafe Classico 250g"
    assert sb.queries[0].captured["eq"]["situacao"] == "A"


def test_products_sem_busca_nao_aplica_filtro_de_texto(monkeypatch):
    sb = FakeSupabase({"bling_products": []})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)
    asyncio.run(br.list_products(q=None))
    assert "or" not in sb.queries[0].captured


def test_payment_methods_so_recebimentos_e_ativas(monkeypatch):
    sb = FakeSupabase({"bling_payment_methods": [
        {"id": 45, "descricao": "Boleto", "situacao": 1, "finalidade": 2},
        {"id": 46, "descricao": "Fornecedor", "situacao": 1, "finalidade": 1},
        {"id": 47, "descricao": "Antiga", "situacao": 0, "finalidade": 2},
    ]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    out = asyncio.run(br.list_payment_methods())

    ids = [m["id"] for m in out["data"]]
    assert ids == [45], "so formas ativas com finalidade de recebimento"


def test_criar_pedido_devolve_409_quando_contato_nao_resolve(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "cnpj": None})

    async def fake_resolve(lead):
        return Resolution("suggested", None, [{"id": 77, "nome": "Empresa X"}], "telefone")

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 409
    corpo = resp.body.decode()
    assert "contact_unresolved" in corpo
    assert "Empresa X" in corpo


def test_criar_pedido_enfileira_quando_bling_esta_fora(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})

    async def fake_resolve(lead):
        return Resolution("linked", 555)

    async def fake_create(*a, **k):
        raise BlingServerError("bling fora do ar")

    enfileirados = []

    async def fake_enqueue(kind, payload, sale_id=None):
        enfileirados.append(kind)

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "create_order", fake_create)
    monkeypatch.setattr(br.jobs, "enqueue", fake_enqueue)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email: None)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 202
    assert enfileirados == ["create_order"]


def test_erro_de_validacao_nao_enfileira_e_devolve_422(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})

    async def fake_resolve(lead):
        return Resolution("linked", 555)

    async def fake_create(*a, **k):
        raise BlingValidationError("quantidade invalida", description="itens[0]")

    enfileirados = []

    async def fake_enqueue(kind, payload, sale_id=None):
        enfileirados.append(kind)

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "create_order", fake_create)
    monkeypatch.setattr(br.jobs, "enqueue", fake_enqueue)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email: None)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 422
    assert enfileirados == [], "erro de validacao nao pode virar retentativa"


def test_sucesso_devolve_201_com_numero_do_pedido(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})

    async def fake_resolve(lead):
        return Resolution("linked", 555)

    async def fake_create(*a, **k):
        return {"sale_id": "S1", "bling_order_id": 34215992, "bling_order_number": 1234}

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "create_order", fake_create)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email: None)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", sold_at="2026-08-18", sold_by="v@e.com",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 201
    assert "1234" in resp.body.decode()


def test_oauth_callback_rejeita_state_invalido(monkeypatch):
    async def fake_consume(state):
        return False

    monkeypatch.setattr(br.auth, "consume_state", fake_consume)
    resp = asyncio.run(br.oauth_callback(code="c", state="ruim"))
    assert resp.status_code == 400


def test_router_registrado_no_app():
    from app.main import app as fastapi_app
    rotas = {getattr(r, "path", "") for r in fastapi_app.routes}
    assert "/api/bling/products" in rotas
    assert "/api/bling/orders" in rotas
    assert "/api/bling/status" in rotas
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `cd backend && python -m pytest tests/test_bling_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.router'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/router.py
"""Endpoints da integracao Bling consumidos pelo Next.

Contrato de POST /api/bling/orders:
  201 -> pedido criado no Bling (o vendedor ve o numero na hora)
  202 -> Bling indisponivel; job enfileirado, a UI mostra "processando"
  409 -> contato nao resolvido; devolve candidatos para o vendedor decidir
  422 -> erro de validacao do Bling, repassado com a mensagem original
"""
import asyncio
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.bling import auth, config, contacts, jobs
from app.bling.errors import TRANSIENT, BlingError, BlingValidationError
from app.bling.orders import create_order
from app.config import settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bling", tags=["bling"])


class OrderItemIn(BaseModel):
    bling_product_id: int
    quantidade: float
    valor_unitario: float
    desconto_percentual: float = 0
    codigo: str | None = None
    descricao: str | None = None
    unidade: str | None = None


class PaymentIn(BaseModel):
    method_id: int
    terms: list[int] = Field(default_factory=lambda: [0])


class OrderIn(BaseModel):
    lead_id: str
    deal_id: str | None = None
    sold_at: str
    sold_by: str | None = None
    items: list[OrderItemIn]
    payment: PaymentIn
    notes: str = ""


class ContactIn(BaseModel):
    lead_id: str
    nome: str
    numeroDocumento: str
    tipo: str | None = None
    email: str | None = None
    telefone: str | None = None
    celular: str | None = None
    endereco: dict | None = None


# --------------------------------------------------------------------------
# Leitura dos espelhos
# --------------------------------------------------------------------------
def _query_products(q: str | None, limit: int):
    query = (get_supabase().table("bling_products")
             .select("id, codigo, nome, preco, unidade, saldo_virtual, imagem_url")
             .eq("situacao", "A"))
    if q:
        alvo = f"%{q}%"
        query = query.or_(f"nome.ilike.{alvo},codigo.ilike.{alvo}")
    return getattr(query.order("nome").limit(limit).execute(), "data", None) or []


@router.get("/products")
async def list_products(q: str | None = Query(None), limit: int = Query(50, le=200)):
    """Busca no ESPELHO, nunca no Bling — o combobox dispara a cada tecla."""
    data = await asyncio.to_thread(_query_products, q, limit)
    return {"data": data}


def _query_payment_methods():
    rows = getattr(get_supabase().table("bling_payment_methods")
                   .select("*").order("descricao").execute(), "data", None) or []
    # finalidade: 1 pagamentos, 2 recebimentos, 3 ambos. Venda usa 2 ou 3.
    return [m for m in rows
            if m.get("situacao") == 1 and m.get("finalidade") in (2, 3)]


@router.get("/payment-methods")
async def list_payment_methods():
    return {"data": await asyncio.to_thread(_query_payment_methods)}


def _query_sellers():
    return getattr(get_supabase().table("bling_sellers").select("*")
                   .order("nome").execute(), "data", None) or []


@router.get("/sellers")
async def list_sellers():
    return {"data": await asyncio.to_thread(_query_sellers)}


# --------------------------------------------------------------------------
# Pedido
# --------------------------------------------------------------------------
def _load_lead(lead_id: str) -> dict | None:
    res = (get_supabase().table("leads")
           .select("id, name, phone, telefone_comercial, email, cnpj, bling_contact_id")
           .eq("id", lead_id).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _seller_id_for(email: str | None) -> int | None:
    if not email:
        return None
    res = (get_supabase().table("bling_seller_map").select("bling_seller_id")
           .eq("user_email", email).limit(1).maybe_single().execute())
    row = getattr(res, "data", None) or {}
    return row.get("bling_seller_id")


@router.post("/orders")
async def create_order_endpoint(body: OrderIn):
    lead = await asyncio.to_thread(_load_lead, body.lead_id)
    if not lead:
        return JSONResponse({"error": "lead_not_found"}, status_code=404)

    resolucao = await contacts.resolve(lead)
    if resolucao.status != "linked":
        # Nunca chuta o contato: sem match unico por documento, decide o humano.
        return JSONResponse({
            "error": "contact_unresolved",
            "status": resolucao.status,
            "reason": resolucao.reason,
            "candidates": resolucao.candidates,
        }, status_code=409)

    itens = [{
        "bling_product_id": i.bling_product_id,
        "codigo": i.codigo,
        "descricao": i.descricao or "",
        "unidade": i.unidade,
        "quantidade": i.quantidade,
        "valor_unitario": i.valor_unitario,
        "desconto_percentual": i.desconto_percentual,
    } for i in body.items]

    # Descricao e obrigatoria no item mesmo com produto.id — completa do espelho.
    faltando = [i for i in itens if not i["descricao"]]
    if faltando:
        espelho = await asyncio.to_thread(
            lambda: getattr(get_supabase().table("bling_products")
                            .select("id, nome, codigo, unidade").execute(), "data", None) or []
        )
        por_id = {int(p["id"]): p for p in espelho}
        for item in faltando:
            p = por_id.get(item["bling_product_id"]) or {}
            item["descricao"] = p.get("nome") or "Item"
            item["codigo"] = item["codigo"] or p.get("codigo")
            item["unidade"] = item["unidade"] or p.get("unidade")

    kwargs = {
        "lead_id": body.lead_id,
        "deal_id": body.deal_id,
        "contact_id": resolucao.contact_id,
        "sold_at": body.sold_at,
        "sold_by": body.sold_by,
        "itens": itens,
        "payment": {"method_id": body.payment.method_id, "terms": body.payment.terms},
        "seller_id": await asyncio.to_thread(_seller_id_for, body.sold_by),
        "notes": body.notes,
    }

    from app.bling.client import BlingClient
    try:
        async with BlingClient() as client:
            out = await create_order(client, **kwargs)
    except BlingValidationError as exc:
        # Repetir payload invalido nunca conserta — nao vai para a fila.
        return JSONResponse({
            "error": "validation", "message": str(exc),
            "detail": exc.description, "type": exc.type,
        }, status_code=422)
    except TRANSIENT as exc:
        await jobs.enqueue("create_order", kwargs)
        logger.warning("[BLING] pedido enfileirado (Bling indisponivel): %s", exc)
        return JSONResponse({"status": "queued", "reason": str(exc)}, status_code=202)
    except BlingError as exc:
        return JSONResponse({"error": "bling", "message": str(exc)}, status_code=502)

    return JSONResponse({**out, "status": "created"}, status_code=201)


@router.post("/contacts")
async def create_contact_endpoint(body: ContactIn):
    """Cria o contato no Bling e vincula ao lead (fluxo do 409)."""
    lead = await asyncio.to_thread(_load_lead, body.lead_id)
    if not lead:
        return JSONResponse({"error": "lead_not_found"}, status_code=404)

    from app.bling.client import BlingClient
    dados = body.model_dump(exclude={"lead_id"}, exclude_none=True)
    try:
        async with BlingClient() as client:
            contact_id = await contacts.create_contact(client, lead, dados)
    except BlingValidationError as exc:
        return JSONResponse({"error": "validation", "message": str(exc),
                             "detail": exc.description}, status_code=exc.status)
    return {"bling_contact_id": contact_id}


@router.post("/contacts/link")
async def link_contact_endpoint(lead_id: str, contact_id: int):
    """Confirma manualmente um candidato sugerido."""
    await contacts.link(lead_id, contact_id)
    return {"linked": True}


# --------------------------------------------------------------------------
# OAuth e operacao
# --------------------------------------------------------------------------
@router.get("/oauth/authorize")
async def oauth_authorize():
    state = await auth.new_state()
    return {"url": auth.authorize_url(state)}


@router.get("/oauth/callback")
async def oauth_callback(code: str = "", state: str = ""):
    if not await auth.consume_state(state):
        return JSONResponse({"error": "invalid_state"}, status_code=400)
    # O authorization_code expira em 1 MINUTO — troca imediata.
    await auth.exchange_code(code)
    destino = (settings.frontend_url or "").rstrip("/") + "/config?bling=ok"
    return RedirectResponse(destino, status_code=302)


@router.get("/status")
async def bling_status():
    estado = await auth.status()
    return {**estado, "enabled": config.enabled()}


@router.post("/sync")
async def sync_endpoint(full: bool = False):
    from app.bling.sync import sync_all
    return await sync_all(full=full)
```

- [ ] **Step 4: Registrar o router**

Em `backend/app/main.py`:

```python
from app.bling.router import router as bling_router
```

E na lista de `include_router`, depois de `app.include_router(bling_webhook_router)`:

```python
app.include_router(bling_router)
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_router.py -v`
Expected: PASS — 9 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/router.py backend/app/main.py backend/tests/test_bling_router.py
git commit -m "feat(bling): endpoints /api/bling (produtos, pedido, oauth, status)"
```

---

### Task 14: Backfill de 12 meses

**Files:**
- Create: `backend/app/bling/backfill.py`
- Modify: `backend/app/bling/router.py` (endpoint)
- Test: `backend/tests/test_bling_backfill.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
# backend/tests/test_bling_backfill.py
import asyncio
from datetime import date

import app.bling.backfill as bf


def test_janelas_de_30_dias_cobrem_o_periodo_sem_buraco():
    janelas = bf.build_windows(date(2026, 1, 1), date(2026, 3, 2), dias=30)
    assert janelas[0] == ("2026-01-01", "2026-01-30")
    assert janelas[1] == ("2026-01-31", "2026-03-01")
    assert janelas[-1][1] == "2026-03-02"
    # sem sobreposicao nem lacuna entre janelas consecutivas
    for anterior, seguinte in zip(janelas, janelas[1:]):
        assert date.fromisoformat(seguinte[0]) == date.fromisoformat(anterior[1]) + \
            __import__("datetime").timedelta(days=1)


def test_janela_nunca_passa_de_um_ano():
    """Filtro de periodo com intervalo > 1 ano devolve 400 no Bling."""
    janelas = bf.build_windows(date(2025, 1, 1), date(2026, 8, 18), dias=30)
    for inicio, fim in janelas:
        delta = date.fromisoformat(fim) - date.fromisoformat(inicio)
        assert delta.days < 365


def test_periodo_de_um_dia_gera_uma_janela():
    assert bf.build_windows(date(2026, 8, 18), date(2026, 8, 18), dias=30) == \
        [("2026-08-18", "2026-08-18")]


def test_run_projeta_cada_pedido_e_salva_progresso(monkeypatch):
    pedidos_listados = [{"id": 1}, {"id": 2}]
    detalhes = {1: {"id": 1, "data": "2026-08-01", "total": 10.0,
                    "contato": {"id": 55}, "itens": []},
                2: {"id": 2, "data": "2026-08-02", "total": 20.0,
                    "contato": {"id": 66}, "itens": []}}

    class FakeClient:
        async def paginate(self, path, params=None, limite=100):
            for p in pedidos_listados:
                yield p

        async def get(self, path, params=None):
            oid = int(path.rsplit("/", 1)[-1])
            return {"data": detalhes[oid]}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    projetados = []

    async def fake_upsert(pedido, lead_id, event_date):
        projetados.append(pedido["id"])
        return "S"

    async def fake_lead(contact_id):
        return "LEAD-1"

    progresso = []
    monkeypatch.setattr(bf, "_new_client", lambda: FakeClient())
    monkeypatch.setattr(bf, "upsert_from_bling", fake_upsert)
    monkeypatch.setattr(bf, "_lead_for_contact", fake_lead)
    monkeypatch.setattr(bf, "_save_progress", lambda cursor: progresso.append(cursor))

    out = asyncio.run(bf.run(months=1))

    assert out["pedidos"] == 2
    assert projetados == [1, 2]
    assert progresso, "o progresso tem que ser salvo para o job ser retomavel"


def test_run_retoma_da_ultima_janela_concluida(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.params = []

        async def paginate(self, path, params=None, limite=100):
            self.params.append(params)
            return
            yield  # pragma: no cover

        async def get(self, path, params=None):
            return {"data": {}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    client = FakeClient()
    monkeypatch.setattr(bf, "_new_client", lambda: client)
    monkeypatch.setattr(bf, "_save_progress", lambda cursor: None)
    monkeypatch.setattr(bf, "_load_progress", lambda: "2026-06-30")

    asyncio.run(bf.run(months=12))

    primeiras = [p["dataInicial"] for p in client.params]
    assert all(d > "2026-06-30" for d in primeiras), \
        "janelas ja concluidas nao podem ser refeitas"
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `cd backend && python -m pytest tests/test_bling_backfill.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.bling.backfill'`

- [ ] **Step 3: Implementar**

```python
# backend/app/bling/backfill.py
"""Importacao dos pedidos historicos (decisao D8: 12 meses).

Janelas de 30 dias por dois motivos: o filtro de periodo do Bling rejeita
intervalos maiores que 1 ano (HTTP 400), e janelas curtas tornam o job
retomavel — se cair no meio, recomeca da ultima janela concluida, nao do zero.

Custo: ~2 chamadas por pedido (listagem paginada + GET do detalhe, que e a
unica forma de obter os itens). Com 3 req/s, ~1,5 pedido por segundo.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from app.bling.orders import upsert_from_bling
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_RESOURCE = "backfill"
_WINDOW_DAYS = 30


def _new_client():
    from app.bling.client import BlingClient
    return BlingClient()


def build_windows(inicio: date, fim: date, dias: int = _WINDOW_DAYS) -> list[tuple[str, str]]:
    """Fatia [inicio, fim] em janelas contiguas de `dias`, sem lacuna nem sobreposicao."""
    janelas = []
    atual = inicio
    while atual <= fim:
        termino = min(atual + timedelta(days=dias - 1), fim)
        janelas.append((atual.isoformat(), termino.isoformat()))
        atual = termino + timedelta(days=1)
    return janelas


def _load_progress() -> str | None:
    res = (get_supabase().table("bling_sync_state").select("last_cursor")
           .eq("resource", _RESOURCE).limit(1).maybe_single().execute())
    return (getattr(res, "data", None) or {}).get("last_cursor")


def _save_progress(cursor: str) -> None:
    (get_supabase().table("bling_sync_state").upsert(
        {"resource": _RESOURCE, "last_cursor": cursor,
         "last_sync_at": datetime.now(timezone.utc).isoformat(),
         "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="resource").execute())


def _contact_row(contact_id: int) -> dict | None:
    res = (get_supabase().table("bling_contacts").select("*")
           .eq("id", contact_id).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


async def _lead_for_contact(contact_id: int | None) -> str | None:
    if not contact_id:
        return None
    from app.bling.contacts import ensure_lead
    contato = await asyncio.to_thread(_contact_row, int(contact_id))
    return await ensure_lead(contato) if contato else None


async def run(months: int = 12, hoje: date | None = None) -> dict:
    """Importa os pedidos dos ultimos `months` meses. Retomavel."""
    fim = hoje or datetime.now(timezone.utc).date()
    inicio = fim - timedelta(days=30 * months)

    concluido_ate = await asyncio.to_thread(_load_progress)
    janelas = build_windows(inicio, fim)
    if concluido_ate:
        janelas = [j for j in janelas if j[0] > concluido_ate]
        logger.info("[BLING BACKFILL] retomando apos %s (%d janelas restantes)",
                    concluido_ate, len(janelas))

    total = 0
    async with _new_client() as client:
        for win_inicio, win_fim in janelas:
            params = {"dataInicial": win_inicio, "dataFinal": win_fim}
            ids = [int(p["id"]) async for p in client.paginate("/pedidos/vendas", params)]
            for order_id in ids:
                # A listagem nao traz itens; o detalhe e obrigatorio.
                pedido = (await client.get(f"/pedidos/vendas/{order_id}")).get("data") or {}
                if not pedido:
                    continue
                contact_id = (pedido.get("contato") or {}).get("id")
                lead_id = await _lead_for_contact(contact_id)
                await upsert_from_bling(
                    pedido, lead_id=lead_id,
                    event_date=f"{pedido.get('data')}T00:00:00+00:00",
                )
                total += 1
            await asyncio.to_thread(_save_progress, win_fim)
            logger.info("[BLING BACKFILL] janela %s..%s: %d pedidos (total %d)",
                        win_inicio, win_fim, len(ids), total)

    return {"pedidos": total, "janelas": len(janelas)}
```

- [ ] **Step 4: Expor o endpoint**

Ao fim de `backend/app/bling/router.py`:

```python
@router.post("/backfill")
async def backfill_endpoint(months: int = 12):
    """Importacao historica sob demanda (nao roda automatico)."""
    from app.bling.backfill import run
    return await run(months=months)
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_backfill.py -v`
Expected: PASS — 5 passed

- [ ] **Step 6: Rodar a suíte inteira do backend**

Run: `cd backend && python -m pytest -q`
Expected: todos os testes existentes continuam passando (baseline 3.010) + os novos.

- [ ] **Step 7: Commit**

```bash
git add backend/app/bling/backfill.py backend/app/bling/router.py backend/tests/test_bling_backfill.py
git commit -m "feat(bling): backfill retomavel de 12 meses"
```

---

## Fase 7 — Frontend

> **Antes de qualquer task desta fase:** invoque a skill `frontend-design`.
> É preferência registrada do usuário — sempre antes de mexer no frontend.

> **Convenção de teste do frontend (verificada no repo):** toda a suíte é de
> LÓGICA PURA em arquivos `.test.ts` colocados ao lado do fonte. Não existe
> `@testing-library/react`, nem jsdom/happy-dom, nem um único `.test.tsx`.
> Instalar um runner de DOM só para esta feature mexeria na configuração de uma
> suíte de 3.010 testes por um ganho que a separação lógica/componente já entrega.
> Por isso, nesta fase, **toda regra de negócio sai do componente** para módulos
> em `src/lib/`, que são os testados; o componente fica só com renderização e é
> validado por `type-check` e pelo teste manual do checklist final.

### Task 15: Helpers de cálculo e proxies do Next

**Files:**
- Create: `frontend/src/lib/bling.ts`
- Create: `frontend/src/app/api/bling/products/route.ts`
- Create: `frontend/src/app/api/bling/payment-methods/route.ts`
- Create: `frontend/src/app/api/bling/orders/route.ts`
- Create: `frontend/src/app/api/bling/contacts/route.ts`
- Create: `frontend/src/app/api/bling/status/route.ts`
- Test: `frontend/src/lib/bling.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
// frontend/src/lib/bling.test.ts
import { describe, expect, it } from "vitest";
import {
  buildInstallments,
  itemTotal,
  orderTotal,
  parseTerms,
  productSummary,
} from "@/lib/bling";

describe("parseTerms", () => {
  it("interpreta a condicao do Bling", () => {
    expect(parseTerms("30/60/90")).toEqual([30, 60, 90]);
    expect(parseTerms("30")).toEqual([30]);
    expect(parseTerms("")).toEqual([0]);
    expect(parseTerms("a vista")).toEqual([0]);
  });
});

describe("itemTotal", () => {
  it("aplica desconto percentual", () => {
    expect(itemTotal({ quantidade: 10, valorUnitario: 26.7, descontoPercentual: 10 }))
      .toBe(240.3);
  });
  it("sem desconto multiplica direto", () => {
    expect(itemTotal({ quantidade: 3, valorUnitario: 50, descontoPercentual: 0 }))
      .toBe(150);
  });
});

describe("orderTotal", () => {
  it("soma os itens", () => {
    expect(orderTotal([
      { quantidade: 10, valorUnitario: 26.7, descontoPercentual: 0 },
      { quantidade: 2, valorUnitario: 50, descontoPercentual: 0 },
    ])).toBe(367);
  });
  it("pedido vazio vale zero", () => {
    expect(orderTotal([])).toBe(0);
  });
});

describe("buildInstallments", () => {
  it("a vista gera uma parcela na data da venda", () => {
    expect(buildInstallments(500, [0], "2026-08-18")).toEqual([
      { dataVencimento: "2026-08-18", valor: 500 },
    ]);
  });

  it("30/60 divide em duas e soma os dias", () => {
    const p = buildInstallments(500, [30, 60], "2026-08-18");
    expect(p.map((x) => x.dataVencimento)).toEqual(["2026-09-17", "2026-10-17"]);
    expect(p.map((x) => x.valor)).toEqual([250, 250]);
  });

  it("a ultima parcela absorve o arredondamento", () => {
    // Precisa bater com o backend: 100,00 em 3x = 33,33 + 33,33 + 33,34.
    const p = buildInstallments(100, [30, 60, 90], "2026-08-18");
    expect(p.map((x) => x.valor)).toEqual([33.33, 33.33, 33.34]);
    const soma = p.reduce((acc, x) => acc + x.valor, 0);
    expect(Math.round(soma * 100) / 100).toBe(100);
  });

  it("usa arredondamento half-up, nao floor — paridade com o backend", () => {
    // ESTE TESTE EXISTE PARA IMPEDIR UMA "SIMPLIFICACAO" ESPECIFICA.
    // Trocar Math.round por Math.floor no calculo de `base` parece inofensivo e
    // a soma continua fechando — mas divide diferente em 46,7% dos totais
    // realistas (medido em ~1M de combinacoes de R$1 a R$2.000). O backend usa
    // Decimal com ROUND_HALF_UP; com floor, o vendedor veria na tela uma divisao
    // diferente da que foi gravada no ERP, e sem erro nenhum para denunciar.
    //
    // R$10,01 em 2x: half-up da [5.01, 5.00]; floor daria [5.00, 5.01].
    expect(buildInstallments(10.01, [0, 30], "2026-08-18").map((x) => x.valor))
      .toEqual([5.01, 5.0]);
    // R$10,00 em 6x: half-up da 1.67 x5 + 1.65; floor daria 1.66 x5 + 1.70.
    expect(buildInstallments(10, [0, 30, 60, 90, 120, 150], "2026-08-18")
      .map((x) => x.valor)).toEqual([1.67, 1.67, 1.67, 1.67, 1.67, 1.65]);
  });

  it("a ultima parcela pode ser MENOR que as demais", () => {
    // Consequencia do half-up que contraria a leitura literal de "a ultima
    // absorve o resto". O espelho TS precisa reproduzir isso, nao "consertar".
    const p = buildInstallments(10, [0, 30, 60, 90, 120, 150], "2026-08-18");
    expect(p[p.length - 1].valor).toBeLessThan(p[0].valor);
  });

  it("nunca deixa centavo sobrando", () => {
    for (const total of [10, 99.99, 1234.56, 0.03]) {
      const p = buildInstallments(total, [0, 30, 60], "2026-08-18");
      const soma = p.reduce((acc, x) => acc + x.valor, 0);
      expect(Math.round(soma * 100) / 100).toBe(total);
    }
  });
});

describe("productSummary", () => {
  it("um item usa a descricao", () => {
    expect(productSummary([{ descricao: "Cafe 250g" }])).toBe("Cafe 250g");
  });
  it("varios itens somam o contador", () => {
    expect(productSummary([
      { descricao: "Cafe 250g" }, { descricao: "Cafe 500g" }, { descricao: "Drip" },
    ])).toBe("Cafe 250g +2 itens");
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/__tests__/bling.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/bling"`

- [ ] **Step 3: Implementar os helpers**

```ts
// frontend/src/lib/bling.ts
/**
 * Cálculos do pedido Bling no cliente.
 *
 * A divisão de parcelas aqui precisa produzir EXATAMENTE o mesmo resultado que
 * `build_installments` em `backend/app/bling/orders.py` — o vendedor vê o valor
 * das parcelas antes de salvar, e o backend recalcula na hora de montar o
 * payload. Divergência de um centavo entre os dois vira recusa do Bling.
 *
 * Toda a aritmética é feita em CENTAVOS (inteiros) para não acumular erro de
 * ponto flutuante.
 */

export interface BlingLineItem {
  quantidade: number;
  valorUnitario: number;
  descontoPercentual: number;
}

export interface BlingInstallment {
  dataVencimento: string;
  valor: number;
}

const cents = (valor: number): number => Math.round(valor * 100);
const reais = (centavos: number): number => Math.round(centavos) / 100;

/** "30/60/90" -> [30, 60, 90]. Vazio ou não numérico -> [0] (à vista). */
export function parseTerms(raw: string | null | undefined): number[] {
  if (!raw) return [0];
  const dias = String(raw)
    .replace(/,/g, "/")
    .split("/")
    .map((p) => p.trim())
    .filter((p) => /^\d+$/.test(p))
    .map((p) => parseInt(p, 10));
  return dias.length ? dias : [0];
}

export function itemTotal(item: BlingLineItem): number {
  const bruto = cents(item.quantidade * item.valorUnitario);
  const desconto = (item.descontoPercentual || 0) / 100;
  return reais(bruto * (1 - desconto));
}

export function orderTotal(itens: BlingLineItem[]): number {
  return reais(itens.reduce((acc, i) => acc + cents(itemTotal(i)), 0));
}

export function buildInstallments(
  total: number,
  terms: number[],
  soldAt: string,
): BlingInstallment[] {
  const prazos = terms.length ? terms : [0];
  const totalCentavos = cents(total);
  const n = prazos.length;
  const base = Math.round(totalCentavos / n);
  // O backend RECUSA divisões em que alguma parcela ficaria sem valor
  // (`base > 0 && ultima > 0` em `build_installments`). Só acontece abaixo de
  // R$0,66 — nenhuma venda real — mas sem esta checagem o modal exibiria uma
  // parcela de R$0,00 e o backend devolveria 422 sem o vendedor entender por quê.
  const ultimaCentavos = totalCentavos - base * (n - 1);
  if (base <= 0 || ultimaCentavos <= 0) return [];

  return prazos.map((dias, i) => {
    // A última parcela absorve o resto: 100,00/3 = 33,33 + 33,33 + 33,34.
    // `base` usa Math.round (half-up), NUNCA Math.floor — ver o teste de
    // paridade. Floor fecha a soma igual, mas divide diferente do backend em
    // quase metade dos totais, e a divergência é silenciosa.
    const valorCentavos = i < n - 1 ? base : totalCentavos - base * (n - 1);
    const vencimento = new Date(`${soldAt}T12:00:00Z`);
    vencimento.setUTCDate(vencimento.getUTCDate() + dias);
    return {
      dataVencimento: vencimento.toISOString().slice(0, 10),
      valor: reais(valorCentavos),
    };
  });
}

export function productSummary(itens: { descricao: string }[]): string {
  if (!itens.length) return "Pedido Bling";
  const primeiro = itens[0].descricao || "Item";
  return itens.length === 1 ? primeiro : `${primeiro} +${itens.length - 1} itens`;
}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd frontend && npx vitest run src/lib/__tests__/bling.test.ts`
Expected: PASS — 10 passed

- [ ] **Step 5: Criar os proxies**

Todos seguem o padrão de `frontend/src/app/api/traffic/report/route.ts`.

```ts
// frontend/src/app/api/bling/products/route.ts
const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const q = searchParams.get("q") || "";
  const limit = searchParams.get("limit") || "50";
  const url = `${backend()}/api/bling/products?limit=${encodeURIComponent(limit)}${
    q ? `&q=${encodeURIComponent(q)}` : ""
  }`;
  try {
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "products_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
```

```ts
// frontend/src/app/api/bling/payment-methods/route.ts
const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function GET() {
  try {
    const resp = await fetch(`${backend()}/api/bling/payment-methods`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
```

```ts
// frontend/src/app/api/bling/orders/route.ts
const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function POST(req: Request) {
  const body = await req.json();
  try {
    const resp = await fetch(`${backend()}/api/bling/orders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    // Repassa o status TAL QUAL: o modal distingue 201 (criado), 202 (na fila),
    // 409 (contato não resolvido) e 422 (validação do Bling).
    return Response.json(await resp.json(), { status: resp.status });
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
```

```ts
// frontend/src/app/api/bling/contacts/route.ts
const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function POST(req: Request) {
  const body = await req.json();
  try {
    const resp = await fetch(`${backend()}/api/bling/contacts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return Response.json(await resp.json(), { status: resp.status });
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
```

```ts
// frontend/src/app/api/bling/status/route.ts
import { getCurrentUser } from "@/lib/supabase/pipeline-access";

const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function GET() {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  try {
    const resp = await fetch(`${backend()}/api/bling/status`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
```

- [ ] **Step 6: Type-check e commit**

Run: `cd frontend && npm run type-check`
Expected: sem erros

```bash
git add frontend/src/lib/bling.ts frontend/src/lib/bling.test.ts frontend/src/app/api/bling
git commit -m "feat(bling): helpers de calculo e proxies do Next"
```

---

### Task 16: Modal de venda em modo Bling

**Files:**
- Modify: `frontend/src/components/sales/sale-create-modal.tsx`
- Create: `frontend/src/lib/bling-order-state.ts`
- Create: `frontend/src/components/sales/bling-order-form.tsx`
- Create: `frontend/src/components/sales/bling-contact-resolver.tsx`
- Test: `frontend/src/lib/bling-order-state.test.ts`

- [ ] **Step 1: Invocar a skill de design**

Invoque `frontend-design` antes de escrever qualquer componente. O modal existente
usa um sistema visual próprio (`#dedbd6` nas bordas, `#111111` no texto, raio de
4px, `text-[11px] uppercase tracking-[0.6px]` nos rótulos) — o novo bloco tem que
parecer parte dele, não um enxerto.

- [ ] **Step 2: Escrever o teste que falha**

Toda a lógica do formulário (linhas de item, preenchimento a partir do produto,
validação, montagem do payload) vive num módulo puro. O componente só renderiza.

```ts
// frontend/src/lib/bling-order-state.ts — testado aqui
import { describe, expect, it } from "vitest";
import {
  addLine,
  applyProduct,
  blankLine,
  buildOrderPayload,
  removeLine,
  updateLine,
} from "@/lib/bling-order-state";

const PRODUTOS = [
  { id: 123, codigo: "CAN-CLA-250", nome: "Cafe Canastra Classico Moido 250g",
    preco: 26.7, unidade: "UN", saldo_virtual: 480 },
  { id: 124, codigo: "CAN-SUA-500", nome: "Cafe Canastra Suave Moido 500g",
    preco: 44.9, unidade: "UN", saldo_virtual: 120 },
];

describe("linhas de item", () => {
  it("comeca com uma linha vazia", () => {
    expect(blankLine()).toMatchObject({
      blingProductId: null, quantidade: 1, valorUnitario: 0, descontoPercentual: 0,
    });
  });

  it("adiciona e remove linhas", () => {
    let linhas = [blankLine()];
    linhas = addLine(linhas);
    expect(linhas).toHaveLength(2);
    linhas = removeLine(linhas, 1);
    expect(linhas).toHaveLength(1);
  });

  it("nunca remove a ultima linha", () => {
    const linhas = removeLine([blankLine()], 0);
    expect(linhas).toHaveLength(1);
  });

  it("escolher o produto preenche preco, descricao, codigo e unidade", () => {
    const linhas = applyProduct([blankLine()], 0, 123, PRODUTOS);
    expect(linhas[0]).toMatchObject({
      blingProductId: 123,
      descricao: "Cafe Canastra Classico Moido 250g",
      codigo: "CAN-CLA-250",
      unidade: "UN",
      valorUnitario: 26.7,
    });
  });

  it("produto desconhecido nao apaga o que ja estava", () => {
    const antes = applyProduct([blankLine()], 0, 123, PRODUTOS);
    const depois = applyProduct(antes, 0, 999, PRODUTOS);
    expect(depois[0].valorUnitario).toBe(26.7);
  });

  it("updateLine mexe so na linha alvo", () => {
    const linhas = updateLine([blankLine(), blankLine()], 1, { quantidade: 10 });
    expect(linhas[0].quantidade).toBe(1);
    expect(linhas[1].quantidade).toBe(10);
  });
});

describe("buildOrderPayload", () => {
  const base = {
    leadId: "L1", dealId: "D1", soldAt: "2026-08-18", soldBy: "v@e.com",
    paymentMethodId: 45, terms: [30, 60], notes: "",
  };

  it("monta o payload da API com total e parcelas", () => {
    const linhas = updateLine(applyProduct([blankLine()], 0, 123, PRODUTOS), 0,
      { quantidade: 10 });
    const out = buildOrderPayload(linhas, base);

    expect(out.valid).toBe(true);
    expect(out.total).toBe(267);
    expect(out.payload.items[0]).toMatchObject({
      bling_product_id: 123, quantidade: 10, valor_unitario: 26.7,
    });
    expect(out.payload.payment).toMatchObject({ method_id: 45, terms: [30, 60] });
    expect(out.payload.lead_id).toBe("L1");
    expect(out.installments.map((p) => p.valor)).toEqual([133.5, 133.5]);
    expect(out.installments[0].dataVencimento).toBe("2026-09-17");
  });

  it("invalido sem forma de pagamento", () => {
    const linhas = updateLine(applyProduct([blankLine()], 0, 123, PRODUTOS), 0,
      { quantidade: 10 });
    expect(buildOrderPayload(linhas, { ...base, paymentMethodId: null }).valid).toBe(false);
  });

  it("invalido enquanto nenhuma linha tem produto", () => {
    expect(buildOrderPayload([blankLine()], base).valid).toBe(false);
  });

  it("invalido com quantidade zero", () => {
    const linhas = updateLine(applyProduct([blankLine()], 0, 123, PRODUTOS), 0,
      { quantidade: 0 });
    expect(buildOrderPayload(linhas, base).valid).toBe(false);
  });

  it("descarta linhas incompletas do payload", () => {
    let linhas = applyProduct([blankLine()], 0, 123, PRODUTOS);
    linhas = updateLine(linhas, 0, { quantidade: 10 });
    linhas = addLine(linhas); // a segunda linha fica vazia
    const out = buildOrderPayload(linhas, base);
    expect(out.valid).toBe(true);
    expect(out.payload.items).toHaveLength(1);
  });
});
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/bling-order-state.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/bling-order-state"`

- [ ] **Step 4: Implementar `bling-order-state.ts`**

```ts
// frontend/src/lib/bling-order-state.ts
/**
 * Lógica do formulário de pedido Bling, separada do componente.
 *
 * A suíte do frontend é de lógica pura (não há runner de DOM no projeto), então
 * tudo que pode dar errado mora aqui e é testado; o componente vira casca de
 * renderização.
 */
import { buildInstallments, orderTotal, type BlingInstallment } from "@/lib/bling";

export interface BlingProduct {
  id: number;
  codigo: string | null;
  nome: string;
  preco: number | null;
  unidade: string | null;
  saldo_virtual: number | null;
}

export interface OrderLine {
  blingProductId: number | null;
  descricao: string;
  codigo: string | null;
  unidade: string | null;
  quantidade: number;
  valorUnitario: number;
  descontoPercentual: number;
}

export interface OrderMeta {
  leadId: string;
  dealId: string | null;
  soldAt: string;
  soldBy: string | null;
  paymentMethodId: number | null;
  terms: number[];
  notes: string;
}

export interface OrderPayloadResult {
  valid: boolean;
  total: number;
  installments: BlingInstallment[];
  payload: {
    lead_id: string;
    deal_id: string | null;
    sold_at: string;
    sold_by: string | null;
    notes: string;
    items: {
      bling_product_id: number;
      codigo: string | null;
      descricao: string;
      unidade: string | null;
      quantidade: number;
      valor_unitario: number;
      desconto_percentual: number;
    }[];
    payment: { method_id: number | null; terms: number[] };
  };
}

export function blankLine(): OrderLine {
  return {
    blingProductId: null,
    descricao: "",
    codigo: null,
    unidade: null,
    quantidade: 1,
    valorUnitario: 0,
    descontoPercentual: 0,
  };
}

export function addLine(linhas: OrderLine[]): OrderLine[] {
  return [...linhas, blankLine()];
}

/** Nunca deixa o formulário sem nenhuma linha. */
export function removeLine(linhas: OrderLine[], index: number): OrderLine[] {
  if (linhas.length <= 1) return linhas;
  return linhas.filter((_, i) => i !== index);
}

export function updateLine(
  linhas: OrderLine[],
  index: number,
  patch: Partial<OrderLine>,
): OrderLine[] {
  return linhas.map((linha, i) => (i === index ? { ...linha, ...patch } : linha));
}

export function applyProduct(
  linhas: OrderLine[],
  index: number,
  productId: number,
  produtos: BlingProduct[],
): OrderLine[] {
  const produto = produtos.find((p) => p.id === productId);
  if (!produto) return linhas;
  return updateLine(linhas, index, {
    blingProductId: produto.id,
    descricao: produto.nome,
    codigo: produto.codigo,
    unidade: produto.unidade,
    valorUnitario: produto.preco ?? 0,
  });
}

function isComplete(linha: OrderLine): boolean {
  return !!linha.blingProductId && linha.quantidade > 0;
}

export function buildOrderPayload(
  linhas: OrderLine[],
  meta: OrderMeta,
): OrderPayloadResult {
  const completas = linhas.filter(isComplete);
  const total = orderTotal(
    completas.map((l) => ({
      quantidade: l.quantidade,
      valorUnitario: l.valorUnitario,
      descontoPercentual: l.descontoPercentual,
    })),
  );
  const terms = meta.terms.length ? meta.terms : [0];

  return {
    valid: completas.length > 0 && !!meta.paymentMethodId,
    total,
    installments: buildInstallments(total, terms, meta.soldAt),
    payload: {
      lead_id: meta.leadId,
      deal_id: meta.dealId,
      sold_at: meta.soldAt,
      sold_by: meta.soldBy,
      notes: meta.notes,
      items: completas.map((l) => ({
        bling_product_id: l.blingProductId as number,
        codigo: l.codigo,
        descricao: l.descricao,
        unidade: l.unidade,
        quantidade: l.quantidade,
        valor_unitario: l.valorUnitario,
        desconto_percentual: l.descontoPercentual,
      })),
      payment: { method_id: meta.paymentMethodId, terms },
    },
  };
}
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `cd frontend && npx vitest run src/lib/bling-order-state.test.ts`
Expected: PASS — 12 passed

- [ ] **Step 6: Implementar `bling-order-form.tsx`**

Casca de renderização sobre `bling-order-state.ts`. Nenhuma regra de negócio aqui.

- Busca `/api/bling/products` e `/api/bling/payment-methods` no mount, guarda em estado.
- Estado local: `linhas: OrderLine[]` (começa em `[blankLine()]`), `paymentMethodId`,
  `termsRaw` (string tipo `"30/60"`, convertida com `parseTerms` de `@/lib/bling`).
- Cada linha renderiza: combobox de produto (busca por nome ou SKU, com `saldo_virtual`
  exibido ao lado apenas como informação — **nunca** bloqueia a venda, controle de
  estoque é do Bling), quantidade, valor unitário, desconto %, e o total da linha.
- Rodapé com o total do pedido e a previsão das parcelas (data em `dd/MM/yyyy`,
  valor em `pt-BR` com 2 casas), vinda de `buildOrderPayload(...).installments`.
- `onChange(result: OrderPayloadResult)` a cada mudança — o modal usa `result.valid`
  para habilitar o botão e `result.payload` para submeter.
- Pré-preenche `termsRaw` com a `condicao_pagamento` do contato quando o modal a receber.

- [ ] **Step 7: Implementar `bling-contact-resolver.tsx`**

Aparece quando `POST /api/bling/orders` devolve **409**:

- `status: "ambiguous" | "suggested"` → lista `candidates` (nome, fantasia, documento,
  telefone) com um botão "É este cliente" por linha, que chama
  `POST /api/bling/contacts/link` e refaz o pedido.
- `status: "missing"` → formulário de cadastro: nome, CPF/CNPJ (**obrigatório**),
  tipo (F/J, inferido pelo tamanho do documento), e-mail, telefone, e endereço
  (CEP, logradouro, número, bairro, município, UF). Submete em `POST /api/bling/contacts`
  e refaz o pedido.
- Valida CPF/CNPJ no cliente antes de enviar. **Extraia a validação para
  `frontend/src/lib/documento.ts` com teste próprio** (`documento.test.ts`), espelhando
  `_cpf_ok`/`_cnpj_ok` de `backend/app/bling/contacts.py`: mesmos casos —
  `29860598000170` válido, `12345678909` válido, `11111111111` inválido, `123` inválido.
- Texto explicando por que o documento é obrigatório: *"O CPF/CNPJ é o que garante que o
  cliente não seja duplicado no Bling."*

- [ ] **Step 8: Ligar no `sale-create-modal.tsx`**

- Nova prop `blingEnabled?: boolean` (vem de `/api/bling/status`).
- Quando ligado: substitui os campos "Produto / Serviço" e "Valor" pelo `BlingOrderForm`;
  mantém lead, data, vendedor, deal e observação.
- No submit, posta em `/api/bling/orders` em vez de `/api/sales`, e trata:
  - `201` → fecha e mostra "Pedido #1234 criado no Bling".
  - `202` → fecha e mostra "Venda registrada; o pedido está sendo enviado ao Bling".
  - `409` → renderiza o `BlingContactResolver` dentro do modal, sem perder o que foi digitado.
  - `422` → mostra a mensagem do Bling no bloco de erro que já existe.
- Quando desligado, **nada muda** — o modal continua exatamente como está hoje.

- [ ] **Step 9: Rodar os testes e o type-check**

Run: `cd frontend && npm test && npm run type-check`
Expected: PASS — suíte inteira verde

- [ ] **Step 10: Commit**

```bash
git add frontend/src/lib/bling-order-state.ts frontend/src/lib/bling-order-state.test.ts frontend/src/lib/documento.ts frontend/src/lib/documento.test.ts frontend/src/components/sales
git commit -m "feat(bling): modal de venda com itens, parcelas e resolucao de contato"
```


---

### Task 17: `/vendas` e `/config`

**Files:**
- Modify: `frontend/src/components/sales/sales-table.tsx`
- Modify: `frontend/src/lib/types.ts` (campos novos em `Sale`)
- Create: `frontend/src/lib/sale-display.ts`
- Create: `frontend/src/components/config/bling-settings.tsx`
- Test: `frontend/src/lib/sale-display.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
// frontend/src/lib/sale-display.test.ts
import { describe, expect, it } from "vitest";
import { blingOrderUrl, orderLabel, saleStatus } from "@/lib/sale-display";
import type { Sale } from "@/lib/types";

const base: Sale = {
  id: "S1", lead_id: "L1", sold_at: "2026-08-18T12:00:00Z", value: 267,
  product: "Cafe 250g", sold_by: "v@e.com", deal_id: null,
  conversation_id: null, notes: null, created_at: "2026-08-18T12:00:00Z",
};

describe("saleStatus", () => {
  it("venda normal e Registrada", () => {
    expect(saleStatus({ ...base, bling_order_number: 1234 })).toMatchObject({
      label: "Registrada", tone: "neutral",
    });
  });

  it("cancelada tem tom de alerta", () => {
    expect(saleStatus({ ...base, status: "cancelada" })).toMatchObject({
      label: "Cancelada", tone: "danger",
    });
  });

  it("pendente_bling avisa que esta enviando", () => {
    expect(saleStatus({ ...base, status: "pendente_bling" })).toMatchObject({
      label: "Enviando…", tone: "warning",
    });
  });

  it("usa a situacao do Bling quando existir", () => {
    expect(saleStatus({
      ...base, bling_order_number: 1234, bling_situacao_nome: "Faturado",
    }).label).toBe("Faturado");
  });

  it("cancelada vence a situacao do Bling", () => {
    expect(saleStatus({
      ...base, status: "cancelada", bling_situacao_nome: "Faturado",
    }).label).toBe("Cancelada");
  });
});

describe("orderLabel", () => {
  it("prefixa o numero com #", () => {
    expect(orderLabel({ ...base, bling_order_number: 1234 })).toBe("#1234");
  });

  it("venda legada sem pedido no Bling nao mostra nada", () => {
    expect(orderLabel({ ...base, origin: "manual" })).toBe("");
  });
});

describe("blingOrderUrl", () => {
  it("monta a URL a partir do id", () => {
    expect(blingOrderUrl(34215992)).toContain("34215992");
  });

  it("sem id nao ha link", () => {
    expect(blingOrderUrl(null)).toBe("");
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/sale-display.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/sale-display"`

- [ ] **Step 3: Implementar `sale-display.ts`**

```ts
// frontend/src/lib/sale-display.ts
/** Derivações de exibição da venda (status e link do pedido no Bling). */
import type { Sale } from "@/lib/types";

/**
 * O deep-link do pedido NÃO está documentado no OpenAPI do Bling. Confirme o
 * formato abrindo um pedido real no Bling e ajuste esta constante — é o único
 * lugar do código que precisa mudar.
 */
export const BLING_ORDER_URL_TEMPLATE =
  "https://www.bling.com.br/pedidos.vendas.php#/{id}";

export type StatusTone = "neutral" | "warning" | "danger";

export interface SaleStatus {
  label: string;
  tone: StatusTone;
}

export function saleStatus(sale: Sale): SaleStatus {
  if (sale.status === "cancelada") return { label: "Cancelada", tone: "danger" };
  if (sale.status === "pendente_bling") return { label: "Enviando…", tone: "warning" };
  return { label: sale.bling_situacao_nome || "Registrada", tone: "neutral" };
}

export function orderLabel(sale: Sale): string {
  return sale.bling_order_number ? `#${sale.bling_order_number}` : "";
}

export function blingOrderUrl(orderId: number | null | undefined): string {
  return orderId ? BLING_ORDER_URL_TEMPLATE.replace("{id}", String(orderId)) : "";
}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd frontend && npx vitest run src/lib/sale-display.test.ts`
Expected: PASS — 9 passed


- [ ] **Step 5: Estender o tipo `Sale`**

Em `frontend/src/lib/types.ts`, na interface `Sale`, acrescente:

```ts
  bling_order_id?: number | null;
  bling_order_number?: number | null;
  bling_situacao_id?: number | null;
  bling_situacao_nome?: string | null;
  origin?: "crm" | "bling" | "manual";
  status?: "registrada" | "cancelada" | "pendente_bling";
  payment_method_id?: number | null;
  payment_terms?: string | null;
```

- [ ] **Step 6: Implementar as colunas em `sales-table.tsx`**

O componente hoje recebe
`{ sales, loading, count, page, onPageChange, onEdit?, onDelete? }` — a assinatura
não muda; só entram duas colunas novas, ambas derivadas por `@/lib/sale-display`
(nenhuma regra nova no componente):

- Coluna **"Pedido"**: `orderLabel(sale)`. Quando houver `bling_order_id`, envolve
  em `<a href={blingOrderUrl(sale.bling_order_id)} target="_blank" rel="noreferrer">`.
  Vendas legadas (`origin: "manual"`) devolvem string vazia e a célula fica em branco.
- Coluna **"Situação"**: `saleStatus(sale)`, mapeando `tone` para as cores já usadas
  na tabela — `neutral` no cinza padrão (`#7b7b78`), `warning` em âmbar, `danger` em
  vermelho.

- [ ] **Step 7: Criar a seção Bling em `/config`**

`bling-settings.tsx`, visível só para admin:

- Estado da conexão a partir de `/api/bling/status`: desconectado, conectado, ou
  **alerta quando `refresh_expires_at` estiver a menos de 5 dias** — o `refresh_token`
  dura 30 dias e perdê-lo obriga a refazer o OAuth na mão.
- Botão "Conectar ao Bling" → `GET /api/bling/oauth/authorize` e redireciona para a `url`.
- Botão "Sincronizar agora" → `POST /api/bling/sync`, mostrando as contagens devolvidas.
- Mapeamento de vendedores: tabela usuário do CRM (de `/api/users`) × vendedor do Bling
  (de `/api/bling/sellers`), com select por linha.
- Botão "Importar histórico (12 meses)" → `POST /api/bling/backfill`, com confirmação
  explícita antes (é um job longo).

- [ ] **Step 8: Rodar os testes do frontend**

Run: `cd frontend && npm test`
Expected: PASS — toda a suíte do frontend

- [ ] **Step 9: Type-check, lint e commit**

Run: `cd frontend && npm run type-check && npm run lint`

```bash
git add frontend/src
git commit -m "feat(bling): colunas de pedido em /vendas e secao Bling em /config"
```

---

## Fechamento

- [ ] **Rodar a suíte inteira**

```bash
cd backend && python -m pytest -q
cd ../frontend && npm test && npm run type-check && npm run lint
```

Expected: tudo verde. Baseline do backend antes desta feature: **3.010 testes**.

- [ ] **Checklist manual antes do go-live**

Nada disto é automatizável e tudo é bloqueante:

1. Criar o aplicativo **privado** no Bling (Central de Extensões → Área do Integrador).
2. Marcar os escopos: contatos, produtos, pedidos de venda, formas de pagamento,
   vendedores. **Os escopos precisam existir ANTES** de configurar o webhook — sem o
   escopo, o recurso `order` nem aparece na aba Webhooks.
3. `BLING_REDIRECT_URI` = `https://api.canastrainteligencia.com/api/bling/oauth/callback`,
   idêntico ao cadastrado no app.
4. Preencher no `.env` de produção: `BLING_ENABLED=true`, `BLING_CLIENT_ID`,
   `BLING_CLIENT_SECRET`, `BLING_REDIRECT_URI`, `BLING_STORE_ID`,
   `BLING_ORDER_SITUACAO_ID`, `BLING_LEAD_DEFAULT_STAGE`.
5. **Antes de aplicar a migration**, checar `id_bling` duplicado. O índice UNIQUE
   `leads_bling_contact_id_key` é criado *antes* do `UPDATE` de seed; se dois leads
   carregarem o mesmo `metadata->>'id_bling'`, o `UPDATE` viola a unicidade e **a
   migration inteira aborta** (o runner executa o arquivo como uma query só).

   ```sql
   SELECT metadata->>'id_bling' AS id_bling, count(*)
     FROM leads
    WHERE metadata->>'id_bling' ~ '^[0-9]+$'
    GROUP BY 1 HAVING count(*) > 1;
   ```

   Vazio → aplica sem medo. Com linhas → decidir qual lead fica com o vínculo antes
   de rodar (os 1.208 leads da reativação de 17/08/2026 são a origem provável).

6. Aplicar `supabase/migrations/20260818_bling_integration.sql` no Supabase.
7. Conectar via `/config` → "Conectar ao Bling" e confirmar `/api/bling/status`.
8. Rodar `POST /api/bling/sync?full=true` e conferir as contagens.
9. Configurar o webhook `order` no app apontando para
   `https://api.canastrainteligencia.com/webhook/bling`, versão `v1`, ações
   created/updated/deleted. Repetir para `product`.
10. Confirmar o formato da URL de deep-link do pedido e ajustar
   `BLING_ORDER_URL_TEMPLATE`.
11. Mapear os vendedores em `/config`.
12. Teste E2E ao vivo: registrar uma venda real de valor baixo, conferir o pedido no
    Bling, alterar a situação lá e confirmar que o CRM reflete.
13. Só então rodar `POST /api/bling/backfill` (12 meses).

- [ ] **Push (com autorização do usuário)**

O repo não usa PR. Depois de validado:

```bash
git pull origin master
git push origin worktree-feat-bling-crm-integracao:master
```

O push dispara deploy de produção via GitHub Actions — **só com autorização explícita**.
