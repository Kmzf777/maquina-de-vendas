# Integração CRM ↔ Bling — Design

Data: 2026-08-18
Branch: `worktree-feat-bling-crm-integracao`

---

## 1. Problema

Para registrar uma venda hoje, o vendedor faz o trabalho duas vezes: preenche o modal
do CRM (`sales`: produto como texto livre + um valor) e depois abre o Bling para lançar
o pedido de verdade — contato, itens, quantidades, preços, condição de pagamento. É
lento, desestimula o registro no CRM, e os dois lados divergem.

Além disso o painel de vendas do CRM não bate com o ERP: vendas que nascem fora do CRM
(balcão, telefone, marketplace) são invisíveis, e alterações posteriores no Bling
(cancelamento, mudança de valor) nunca chegam.

**Objetivo:** o vendedor registra a venda **uma vez, no CRM**, e o pedido nasce no Bling.
O ERP continua sendo a fonte da verdade do faturamento — o CRM reflete.

---

## 2. Decisões tomadas

| # | Decisão | Escolha |
|---|---|---|
| D1 | Escopo do pedido | **Pedido comercial**: itens, quantidades, preços, desconto, vendedor, condição de pagamento. Frete, NF-e, estoque e expedição continuam no Bling. |
| D2 | Catálogo de produtos | **Espelho local** sincronizado (job + webhook `product`). |
| D3 | Sem CPF/CNPJ | **Documento obrigatório** para registrar venda. Sem documento não há chave única. |
| D4 | Sentido da sincronia | **Bidirecional**. ERP é a fonte da verdade; `sales` vira projeção do pedido do Bling. |
| D5 | Pagamento | **Forma + condição em dias** (`à vista`, `30`, `30/60`, `30/60/90`, custom). CRM gera as parcelas. |
| D6 | Pedido órfão (contato sem lead) | **Cria o lead** a partir do contato do Bling. |
| D7 | Venda sem deal | Venda criada no CRM continua exigindo deal; venda que chega do webhook entra **sem deal**. |
| D8 | Histórico | **Backfill de 12 meses** de pedidos. |
| D9 | Arquitetura | **Serviço Bling no backend FastAPI** como dono único da conta; Next consome. Criação síncrona com fallback para fila. |

---

## 3. Restrições da API do Bling v3

Levantadas do OpenAPI oficial (`developer.bling.com.br`, 257 endpoints) e das páginas
de Limites, Erros e Webhooks. Estas restrições são o que molda a arquitetura:

- **Base URL**: `https://api.bling.com.br/Api/v3`.
- **Auth**: OAuth 2.0 *authorization_code* (único grant suportado). `access_token` expira
  em **6h** (`expires_in: 21600`); `refresh_token` em **30 dias**. Tokens opacos estão
  **descontinuados** — obrigatório enviar `enable-jwt: 1` no `POST /oauth/token` **e em
  todas as requisições subsequentes**. JWT tem 1.500–3.000 caracteres.
- **Rate limit por CONTA, não por endpoint**: **3 req/s** e **120.000 req/dia**. Estourar
  devolve `429 TOO_MANY_REQUESTS`. Bloqueio de IP em 300 erros/10s, 600 req/10s, ou
  20 chamadas a `/oauth/token` em 60s (bloqueio de 60 min).
  → **Consequência de design:** só pode existir *um* processo falando com o Bling. Se o
  Next e o worker chamassem direto, um estouraria o orçamento do outro.
- **Filtros de período**: intervalo maior que 1 ano devolve `400`. Backfill precisa de
  janelas.
- **Paginação**: `pagina` + `limite` (default 100).
- **`POST /pedidos/vendas`** — obrigatórios: `contato.id`, `data`, `dataSaida`,
  `dataPrevista`, `itens[]` (`quantidade`, `valor`, `descricao`), `parcelas[]`
  (`dataVencimento`, `valor`, `formaPagamento.id`). O contato **precisa já existir**.
- **Webhooks**: assinatura HMAC-SHA256 em `X-Bling-Signature-256` (`sha256=<hex>`, corpo
  cru + client_secret, UTF-8). Recursos: `order`, `product`, `stock`, `virtual_stock`,
  `product_supplier`, `invoice`, `consumer_invoice`. **Não existe webhook de contato** —
  contatos exigem polling.
  - Entrega **não ordenada** e pode repetir → precisa de idempotência e guarda de ordem.
  - Precisa responder **2xx em até 5 segundos**, senão o Bling retenta por 3 dias e
    depois **desabilita** a configuração do webhook.
    → **Consequência de design:** o receiver valida, persiste e devolve 200. O
    processamento (que precisa buscar o pedido completo) roda fora do request.
- Payload do webhook `order` traz só o resumo (`id`, `data`, `numero`, `total`, `contato.id`,
  `vendedor.id`, `loja.id`, `situacao`) — **sem itens**. Buscar itens exige
  `GET /pedidos/vendas/{id}`.

---

## 4. Arquitetura

```
┌──────────────┐  POST /api/bling/orders   ┌────────────────────────────┐
│  Next.js     │ ────────────────────────► │  FastAPI  backend/app/bling│
│  modal venda │ ◄──────────────────────── │  ─ client (JWT + 3 req/s)  │
└──────────────┘   {order_id, numero}      │  ─ contacts (identidade)   │
                                           │  ─ products (espelho)      │
┌──────────────┐   GET /api/bling/products │  ─ orders (criar pedido)   │
│  Next.js     │ ────────────────────────► │  ─ webhook receiver        │
│  combobox    │       (lê o espelho)      │  ─ sync/backfill jobs      │
└──────────────┘                           └────────────┬───────────────┘
                                                        │ httpx
┌──────────────┐   POST /webhook/bling                  ▼
│    Bling     │ ──────────────────────────►    api.bling.com.br
└──────────────┘   (HMAC, ack <5s)
```

**Por que o backend é o dono único:** o limite de 3 req/s é da conta inteira. Um
token-bucket em Redis dentro do backend é o único ponto onde dá pra garantir que o
modal de venda, o job de sync e o processamento de webhook não briguem pelo mesmo
orçamento. O backend também já tem worker com tasks periódicas
(`backend/app/worker/main.py`, com `ad-spend-sync` como precedente), lock distribuído em
Redis (`backend/app/buffer/lead_lock.py`) e refresh de OAuth
(`backend/app/campaigns/google_ads.py`).

### Módulos novos

```
backend/app/bling/
  __init__.py
  config.py        # settings + flags (habilitado, loja, situação padrão)
  auth.py          # OAuth: authorize URL, troca de code, refresh, storage
  ratelimit.py     # token-bucket Redis (3 req/s + teto diário)
  client.py        # BlingClient: httpx + auth + rate limit + retry + erros
  contacts.py      # resolução de identidade e criação de contato
  products.py      # sync do catálogo
  orders.py        # montar e criar pedido de venda; projetar em sales
  webhook_router.py# POST /webhook/bling (ack rápido)
  jobs.py          # outbox: enfileirar e drenar
  sync.py          # jobs periódicos (produtos, contatos, formas, vendedores)
  backfill.py      # importação dos 12 meses
  router.py        # /api/bling/* (produtos, formas, pedido, oauth, status)
```

---

## 5. Modelo de dados

Migration: `supabase/migrations/20260818_bling_integration.sql`.

### 5.1 Credenciais

```sql
CREATE TABLE bling_credentials (
  id                 text PRIMARY KEY DEFAULT 'default',
  access_token       text,
  refresh_token      text,
  access_expires_at  timestamptz,
  refresh_expires_at timestamptz,
  scope              text,
  updated_at         timestamptz NOT NULL DEFAULT now()
);
```

Tokens ficam no **Postgres** (verdade durável) e são cacheados em Redis. O incidente de
`FLUSHALL` de 07/06/2026 é a razão: perder o `refresh_token` obriga a refazer o fluxo
OAuth manualmente no navegador. Redis é cache, não storage.

### 5.2 Espelhos

```sql
CREATE TABLE bling_products (
  id              bigint PRIMARY KEY,        -- id no Bling
  codigo          text,                      -- SKU
  nome            text NOT NULL,
  preco           numeric(12,2),
  unidade         text,
  tipo            text,                      -- P/S/N
  formato         text,                      -- S/V/E
  situacao        text,                      -- A/I
  id_produto_pai  bigint,
  saldo_virtual   numeric(14,3),
  imagem_url      text,
  synced_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX bling_products_nome_trgm ON bling_products
  USING gin (f_unaccent(lower(nome)) gin_trgm_ops);
CREATE INDEX bling_products_codigo_idx ON bling_products (codigo);
CREATE INDEX bling_products_situacao_idx ON bling_products (situacao);

CREATE TABLE bling_contacts (
  id                 bigint PRIMARY KEY,
  nome               text NOT NULL,
  fantasia           text,
  tipo               text,                   -- F/J/E
  doc_digits         text,                   -- CPF/CNPJ só dígitos
  telefone_e164      text,
  celular_e164       text,
  email              text,
  situacao           text,                   -- A/E/I/S
  endereco           jsonb,
  vendedor_id        bigint,
  condicao_pagamento text,
  synced_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX bling_contacts_doc_idx      ON bling_contacts (doc_digits) WHERE doc_digits IS NOT NULL;
CREATE INDEX bling_contacts_telefone_idx ON bling_contacts (telefone_e164) WHERE telefone_e164 IS NOT NULL;
CREATE INDEX bling_contacts_celular_idx  ON bling_contacts (celular_e164) WHERE celular_e164 IS NOT NULL;
CREATE INDEX bling_contacts_email_idx    ON bling_contacts (lower(email)) WHERE email IS NOT NULL;

CREATE TABLE bling_payment_methods (
  id             bigint PRIMARY KEY,
  descricao      text NOT NULL,
  tipo_pagamento int,
  situacao       int,
  padrao         int,
  finalidade     int,
  synced_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bling_sellers (
  id        bigint PRIMARY KEY,
  nome      text NOT NULL,
  situacao  text,
  synced_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bling_sync_state (
  resource     text PRIMARY KEY,   -- 'products' | 'contacts' | 'payment_methods' | 'sellers'
  last_sync_at timestamptz,
  last_cursor  text,
  updated_at   timestamptz NOT NULL DEFAULT now()
);
```

`telefone_e164` / `celular_e164` são gravados **já normalizados** por
`app.leads.service.normalize_phone` — a mesma função que normaliza `leads.phone`.
É isso que garante que os dois lados casem: a normalização é nossa, dos dois lados,
e não depende do formato de texto livre que o Bling guarda (`(51) 99269-6163`).

### 5.3 Vínculo lead ↔ contato

```sql
ALTER TABLE leads ADD COLUMN IF NOT EXISTS bling_contact_id bigint;
CREATE UNIQUE INDEX leads_bling_contact_id_key ON leads (bling_contact_id)
  WHERE bling_contact_id IS NOT NULL;

-- Seed: os 1.208 leads da reativação já carregam o ID do contato.
UPDATE leads
   SET bling_contact_id = (metadata->>'id_bling')::bigint
 WHERE bling_contact_id IS NULL
   AND metadata->>'id_bling' ~ '^[0-9]+$';
```

O índice UNIQUE parcial é a garantia estrutural de 1:1 — dois leads não podem apontar
para o mesmo contato do Bling.

### 5.4 Vendas

```sql
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_order_id      bigint;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_order_number  integer;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_situacao_id   integer;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_situacao_nome text;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_event_date    timestamptz;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS origin              text NOT NULL DEFAULT 'crm';
ALTER TABLE sales ADD COLUMN IF NOT EXISTS status              text NOT NULL DEFAULT 'registrada';
ALTER TABLE sales ADD COLUMN IF NOT EXISTS payment_method_id   bigint;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS payment_terms       text;

CREATE UNIQUE INDEX sales_bling_order_id_key ON sales (bling_order_id)
  WHERE bling_order_id IS NOT NULL;

CREATE TABLE sale_items (
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
CREATE INDEX sale_items_sale_id_idx ON sale_items (sale_id);
```

- `origin`: `crm` (nasceu no modal) | `bling` (chegou pelo webhook) | `manual` (registro
  legado, anterior à integração). A migration marca as linhas existentes:
  `UPDATE sales SET origin = 'manual' WHERE bling_order_id IS NULL;` — roda uma vez,
  antes de qualquer venda nova, então não pega nada criado pela integração.
- `status`: `registrada` | `cancelada` | `pendente_bling`.

  **`pendente_bling` não é escrito pela implementação atual.** O desenho original
  previa gravar a venda no CRM antes de o pedido subir; o que ficou é melhor: no
  caminho da fila (§9.2) o router enfileira e devolve `202` **sem** criar linha em
  `sales`, e a venda nasce quando o job conclui — com o `bling_order_id` já em mãos.
  Criar uma linha antes colidiria com a inserção que o próprio `create_order` faz sob
  a chave de idempotência, e uma venda "fantasma" no painel é pior que uma venda que
  aparece dois minutos depois. O `202` já avisa o vendedor na hora.

  O valor permanece no schema e a tabela de `/vendas` sabe exibi-lo, mas hoje é
  caminho morto. Quem for reativá-lo precisa resolver a colisão com a idempotência
  primeiro.
- `product` (texto, `NOT NULL`) continua existindo e passa a guardar um **resumo
  derivado** dos itens (`"Café Canastra Clássico Moído 250g +2 itens"`), para não quebrar
  a busca e as telas que já leem esse campo.
- `bling_event_date` é a guarda de ordenação: evento com `date` anterior ao já aplicado
  é descartado.

### 5.5 Idempotência de webhook e outbox

```sql
CREATE TABLE bling_webhook_events (
  event_id    text PRIMARY KEY,
  event       text NOT NULL,
  payload     jsonb NOT NULL,
  event_date  timestamptz,
  status      text NOT NULL DEFAULT 'pending',  -- pending|done|failed|skipped
  attempts    integer NOT NULL DEFAULT 0,
  last_error  text,
  received_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz
);
CREATE INDEX bling_webhook_events_pending_idx ON bling_webhook_events (received_at)
  WHERE status = 'pending';

CREATE TABLE bling_jobs (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind       text NOT NULL,          -- 'create_order'
  payload    jsonb NOT NULL,
  status     text NOT NULL DEFAULT 'pending',
  attempts   integer NOT NULL DEFAULT 0,
  last_error text,
  sale_id    uuid REFERENCES sales(id) ON DELETE SET NULL,
  run_after  timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX bling_jobs_pending_idx ON bling_jobs (run_after) WHERE status = 'pending';
```

Todas as tabelas novas com `ENABLE ROW LEVEL SECURITY` + policy de `SELECT` para
`authenticated, service_role` (padrão de `20260618_products_catalog.sql`). Escrita
apenas por `service_role`. `bling_credentials` **não** recebe policy de leitura para
`authenticated` — contém segredos.

---

## 6. Cliente Bling

### 6.1 Autenticação (`auth.py`)

- `authorize_url(state)` → `https://bling.com.br/Api/v3/oauth/authorize?response_type=code&client_id=…&state=…`
- `exchange_code(code)` → `POST /oauth/token`, `Authorization: Basic base64(client_id:client_secret)`,
  `Content-Type: application/x-www-form-urlencoded`, header **`enable-jwt: 1`**,
  body `grant_type=authorization_code&code=…`. Persiste em `bling_credentials`.
- `refresh()` → mesmo endpoint com `grant_type=refresh_token`. **Serializado por lock
  Redis** (`lock:bling_token_refresh`, TTL 30s) — o limite de 20 chamadas a
  `/oauth/token` por 60s com bloqueio de IP de 60 minutos torna refresh concorrente um
  risco real de derrubar a integração inteira.
- `get_access_token()` → lê cache Redis (`bling:access_token`); se ausente ou expirando
  em menos de 5 min, pega o lock, relê o Postgres (outro processo pode ter renovado) e
  só então renova.
- `state` do OAuth: valor aleatório guardado em Redis com TTL de 10 min, validado no
  callback (proteção CSRF).

### 6.2 Rate limit (`ratelimit.py`)

Token-bucket em Redis com script Lua, chave por segundo:

```
key = bling:rl:{unix_second}   → INCR; se == 1, EXPIRE 1
se count > 3 → aguarda até o próximo segundo e repete
key = bling:rl:day:{YYYY-MM-DD} → INCR; EXPIRE 172800
se count > 110000 → recusa (margem de 8% sobre o teto de 120.000)
```

**Fail-closed:** se o Redis estiver indisponível o cliente **recusa** a chamada em vez
de seguir sem contagem. Ao contrário do `lead_lock` (que é fail-open porque bloquear
atendimento é pior que duplicar um turno), aqui seguir sem contagem arrisca bloqueio de
IP por tempo indeterminado. A chamada recusada vai para a fila.

### 6.3 Client (`client.py`)

- `httpx.AsyncClient`, base `https://api.bling.com.br/Api/v3`.
- Headers fixos: `Authorization: Bearer <jwt>`, `enable-jwt: 1`, `Accept: application/json`.
- Retry:
  - `401` → renova o token **uma vez** e repete; segunda falha levanta `BlingAuthError`.
  - `429` → backoff exponencial (1s, 2s, 4s), 3 tentativas, depois `BlingRateLimitError`.
  - `5xx` / timeout → backoff exponencial, 3 tentativas, depois `BlingServerError`.
  - `4xx` de validação → `BlingValidationError` com `type`/`message`/`description` do
    corpo, **sem retry**.
- Nunca loga `access_token`, `refresh_token` ou `client_secret`.

---

## 7. Resolução de identidade — a garantia anti-duplicação

O risco: o CRM normaliza telefone para E.164; o Bling guarda texto livre formatado. Casar
por telefone criaria contatos duplicados no ERP. **Telefone não é chave.**

### 7.1 Ordem de resolução (`contacts.resolve(lead)`)

| Passo | Chave | Resultado |
|---|---|---|
| 1 | `leads.bling_contact_id` | resolvido, fim |
| 2 | `doc_digits(lead.cnpj)` em `bling_contacts` | 1 match → vincula e grava; 2+ → **ambíguo**, devolve candidatos |
| 3 | telefone normalizado (lead.phone, telefone_comercial) contra `telefone_e164`/`celular_e164` | 1 match → devolve como **sugestão** (exige confirmação humana) |
| 4 | `lower(email)` | idem passo 3 |
| 5 | nada | devolve vazio → fluxo de criação |

Só o passo 2 vincula sozinho. Passos 3 e 4 **sugerem** — nunca gravam sem confirmação,
porque o telefone do lead costuma ser o do comprador enquanto o contato do Bling é a
empresa.

### 7.2 Criação (`contacts.create(lead, dados)`)

Pré-condições, nesta ordem:

1. `doc_digits` presente e válido (11 ou 14 dígitos, com verificação de dígito
   verificador de CPF/CNPJ). **Sem documento, não cria** (D3).
2. Lock Redis `lock:bling_contact:{doc_digits}` (TTL 30s) — impede dois vendedores
   criando o mesmo cliente em paralelo.
3. **Re-checagem ao vivo** `GET /contatos?numeroDocumento={doc}` — o espelho pode estar
   minutos atrasado. Se achar, vincula em vez de criar.
4. `POST /contatos` com `nome`, `tipo` (F/J), `situacao: 'A'`, `numeroDocumento`,
   `telefone`/`celular`, `email`, `endereco.geral` completo.
5. Grava em `bling_contacts` e em `leads.bling_contact_id` na mesma transação lógica.

Se o `POST` falhar com violação de documento duplicado do lado do Bling, refaz a busca
por documento e vincula ao existente.

### 7.3 Caminho inverso (`contacts.ensure_lead(contact)`)

Para D6 — pedido chega do Bling e o contato não tem lead:

1. Busca lead por `bling_contact_id`.
2. Busca lead por `cnpj = doc_digits`.
3. Busca lead por telefone normalizado.
4. Não achou → cria lead com `name`, `company`, `cnpj`, `email`, `endereco`, `stage`
   configurável (`BLING_LEAD_DEFAULT_STAGE`), `metadata.origem = 'bling_webhook'`.

`leads.phone` é `UNIQUE NOT NULL`, então o campo precisa de um valor sempre:

- contato tem celular/telefone → `normalize_phone(...)`;
- contato **sem** telefone → placeholder `bling-{contact_id}`, único por construção.
  A coluna já aceita valores não-E.164 (os BSUIDs do WhatsApp usam o mesmo caminho, ver
  `is_bsuid` em `app/leads/service.py`), então isso não é precedente novo.

Se o telefone normalizado colidir com um lead existente, esse lead **é** o cliente —
vincula em vez de criar (é o passo 3 chegando por outro caminho).

---

## 8. Catálogo de produtos

- **Sync completo** na primeira execução: `GET /produtos?criterio=5&limite=100`, paginado.
- **Sync incremental** diário: `GET /produtos?dataAlteracaoInicial={last_sync}`.
- **Webhook `product`** (created/updated/deleted) para atualização em tempo real.
- Guarda `situacao` — o combobox mostra apenas `A` (ativos), mas produtos inativos
  continuam na tabela para que pedidos antigos e o backfill resolvam a descrição.
- `saldo_virtual` é informativo no combobox (não bloqueia venda; controle de estoque é
  do Bling).

Busca no combobox: `GET /api/bling/products?q=` lê **o espelho**, com trigram sobre
`f_unaccent(lower(nome))` e match exato por `codigo`. Zero chamadas ao Bling no caminho
quente do modal.

---

## 9. Fluxo: criar pedido de venda

### 9.1 Contrato

`POST /api/bling/orders` (backend), proxied por `/api/bling/orders` no Next.

```jsonc
{
  "lead_id": "uuid",
  "deal_id": "uuid",                  // obrigatório (D7, venda nascida no CRM)
  "sold_at": "2026-08-18",
  "sold_by": "vendedor@empresa.com",
  "items": [
    { "bling_product_id": 123, "quantidade": 10, "valor_unitario": 26.70, "desconto_percentual": 0 }
  ],
  "payment": { "method_id": 45, "terms": [30, 60] },
  "discount": { "valor": 0, "unidade": "REAL" },
  "notes": "…"
}
```

Respostas:

- `201` → `{ "sale_id", "bling_order_id", "bling_order_number", "status": "created" }`
- `202` → `{ "sale_id", "status": "queued" }` — Bling indisponível, job enfileirado.
- `409` → `{ "error": "contact_unresolved", "candidates": [...] }` — precisa de decisão
  no modal (escolher candidato ou informar documento e criar).
- `422` → `{ "error": "validation", "detail": ... }` — erro de validação do Bling,
  repassado com a mensagem original.

### 9.2 Passos

1. Resolve o contato (§7). Se não resolver, devolve `409` com candidatos — **não cria
   nada**.
2. Resolve `vendedor.id` a partir de `sold_by` (§11.2). Opcional.
3. Monta o payload:
   - `data` = `dataSaida` = `dataPrevista` = `sold_at`.
   - `itens[]`: `{ produto: {id}, codigo, descricao, unidade, quantidade, valor, desconto }`.
     `descricao` vem do espelho (o Bling exige `descricao` mesmo com `produto.id`).
   - `parcelas[]` geradas de `payment` (§9.3).
   - `loja: {id}` se `BLING_STORE_ID` configurado; `situacao: {id}` se
     `BLING_ORDER_SITUACAO_ID` configurado.
   - `observacoes` = `notes`; `observacoesInternas` = `"CRM lead {lead_id} · deal {deal_id}"`.
4. `POST /pedidos/vendas` → resposta traz `data.id`.
5. `GET /pedidos/vendas/{id}` para obter `numero` e `situacao` já resolvidos.
6. Grava `sales` (`origin='crm'`, `bling_order_id`, `bling_order_number`, `product` =
   resumo derivado, `value` = total) + `sale_items`.
7. Move o deal para `fechado_ganho` (mesma lógica de `frontend/src/app/api/sales/route.ts`).

Se o passo 4 falhar com `BlingRateLimitError` / `BlingServerError` / timeout: grava a
`sales` com `status='pendente_bling'` e enfileira `bling_jobs.kind='create_order'`,
devolvendo `202`. O drain do worker completa e preenche `bling_order_id`.

Se falhar com `BlingValidationError`: **não** enfileira (repetir não vai consertar) —
devolve `422` com a mensagem do Bling.

### 9.3 Geração de parcelas

```
n = len(terms)                     # terms em dias: [0] à vista, [30,60] etc.
base = round(total / n, 2)
parcelas[i].valor = base           para i < n-1
parcelas[n-1].valor = total - base * (n-1)     # a última absorve o arredondamento
parcelas[i].dataVencimento = sold_at + terms[i] dias
parcelas[i].formaPagamento.id = payment.method_id
```

A soma das parcelas sempre fecha exatamente com o total — a última absorve o resto.
Pré-preenchimento: se `bling_contacts.condicao_pagamento` do contato estiver preenchida
e for parseável (`"30/60/90"`), sugere como default no modal.

---

## 10. Webhook `order` → projeção em `sales`

### 10.1 Receiver (`POST /webhook/bling`) — precisa devolver 2xx em <5s

1. Lê o corpo **cru** (bytes) — o HMAC é sobre os bytes exatos.
2. Valida `X-Bling-Signature-256` com `hmac.compare_digest` contra
   `hmac_sha256(body, BLING_CLIENT_SECRET)`. Assinatura inválida → `401`, sem processar.
3. `INSERT ... ON CONFLICT (event_id) DO NOTHING` em `bling_webhook_events`. Evento
   repetido é absorvido aqui (idempotência).
4. Publica no event bus e devolve `200` **imediatamente**. Nada de I/O com o Bling
   dentro do request.

### 10.2 Processamento (worker)

Para cada evento `pending`:

- **Guarda de ordem**: se `event_date` < `sales.bling_event_date` do pedido, marca
  `skipped` e não aplica. A entrega do Bling não é ordenada.
- `order.created` / `order.updated`:
  1. `GET /pedidos/vendas/{id}` (o payload do webhook não traz itens).
  2. Resolve o lead pelo `contato.id` → `bling_contacts` → `leads.bling_contact_id`;
     se não houver, `ensure_lead` (§7.3).
  3. `UPSERT` em `sales` por `bling_order_id`: valor, situação, data, vendedor,
     `origin='bling'` **apenas quando a linha é nova** (uma venda criada pelo CRM
     mantém `origin='crm'`), `bling_event_date` = `date` do evento.
  4. Substitui `sale_items` (delete + insert) — o pedido é a verdade.
- `order.deleted`: `status='cancelada'`, preserva a linha e os itens.

### 10.3 Colisão CRM ↔ webhook

Criar um pedido pelo CRM gera um `order.created` que volta pelo webhook. O `UNIQUE
(bling_order_id)` faz o upsert casar com a linha que o CRM já gravou — não duplica.
Vendas em `status='pendente_bling'` (sem `bling_order_id`) que recebem o id pelo drain
do outbox convergem para a mesma linha.

---

## 11. Configuração

### 11.1 Variáveis de ambiente

| Var | Uso |
|---|---|
| `BLING_ENABLED` | liga/desliga a integração (default `false`) |
| `BLING_CLIENT_ID` | app do Bling |
| `BLING_CLIENT_SECRET` | app do Bling; também é a chave do HMAC dos webhooks |
| `BLING_REDIRECT_URI` | `https://api.canastrainteligencia.com/api/bling/oauth/callback` |
| `BLING_STORE_ID` | `loja.id` padrão do pedido (opcional) |
| `BLING_ORDER_SITUACAO_ID` | situação em que o pedido nasce (opcional) |
| `BLING_LEAD_DEFAULT_STAGE` | stage dos leads criados pelo webhook |

O app do Bling é **privado** (opera na própria conta). Escopos necessários: contatos,
produtos, pedidos de venda, formas de pagamento, vendedores — e os escopos precisam
estar presentes **antes** de configurar o webhook `order`, senão o recurso nem aparece
na tela de webhooks do Bling.

### 11.2 Mapeamento de vendedores

`sales.sold_by` guarda o e-mail do usuário do CRM (Supabase Auth); o Bling identifica
vendedor por `id` numérico. Mapeamento em `bling_sellers` + uma tabela de vínculo:

```sql
CREATE TABLE bling_seller_map (
  user_email       text PRIMARY KEY,
  bling_seller_id  bigint NOT NULL REFERENCES bling_sellers(id),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
```

Preenchida por tela admin em `/config`. Sem vínculo, o pedido vai sem `vendedor` — não
bloqueia a venda.

---

## 12. Fluxo OAuth (setup inicial)

1. Admin abre `/config` → seção Bling → "Conectar".
2. Next chama `GET /api/bling/oauth/authorize` → backend gera `state`, guarda em Redis
   (TTL 10 min) e devolve a URL.
3. Admin autoriza no Bling e é redirecionado para
   `GET /api/bling/oauth/callback?code=…&state=…` no backend.
4. Backend valida `state`, troca o `code` (janela de **1 minuto** — o code expira rápido),
   persiste os tokens e redireciona para `/config?bling=ok`.
5. `GET /api/bling/status` mostra conectado/expirando/desconectado e a data do último sync.

---

## 13. Frontend

- **`sale-create-modal.tsx`** ganha modo Bling (quando `BLING_ENABLED`):
  - combobox de produto lendo o espelho (`/api/bling/products?q=`), com SKU e preço;
  - linhas de item (produto, quantidade, valor unitário, desconto) com total calculado;
  - forma de pagamento (espelho) + condição em dias;
  - bloco de resolução de contato quando a API devolve `409`: lista de candidatos ou
    formulário de documento + endereço;
  - o campo `product` de texto livre some no modo Bling (vira resumo derivado).
- **`/painel-vendas`**: colunas de número do pedido e situação do Bling; link direto
  para o pedido no Bling; badge para `status='cancelada'`.
  (A tabela de vendas é renderizada por `/painel-vendas`; `/vendas` é o Kanban de
  deals — a spec dizia `/vendas` por engano.)
  O formato da URL de deep-link do pedido **não** está no OpenAPI — deve ser confirmado
  abrindo um pedido real no Bling e copiando o padrão, na task que constrói a tela.
  Até lá o link fica atrás de uma constante única (`BLING_ORDER_URL_TEMPLATE`).
- **`/config`**: seção Bling (conectar/desconectar, status, mapeamento de vendedores,
  botão de sync manual).

O trabalho de frontend deve ser feito com a skill `frontend-design` invocada antes
(preferência registrada do usuário).

---

## 14. Backfill de 12 meses

Job sob demanda (`POST /api/bling/backfill`), não automático:

- Janelas de 30 dias (o filtro de período do Bling rejeita intervalos > 1 ano; janelas
  menores mantêm cada página pequena e o job retomável).
- Para cada pedido: `GET /pedidos/vendas/{id}` para obter itens → mesma projeção do §10.2,
  com `origin='bling'`.
- Progresso em `bling_sync_state` (`resource='backfill'`, `last_cursor` = última janela
  concluída) — retomável se cair no meio.
- Respeita o token-bucket: com 3 req/s e ~2 chamadas por pedido, ~1,5 pedido/s.
- Vendas legadas de `sales` sem `bling_order_id` **não são tocadas** e recebem
  `origin='manual'` na migration.

---

## 15. Testes

Backend (`backend/tests/`, pytest com `asyncio_mode=auto`):

- `test_bling_auth.py` — refresh serializado por lock, `enable-jwt` presente, `state`
  validado, tokens nunca logados.
- `test_bling_ratelimit.py` — 4ª chamada no mesmo segundo espera; teto diário recusa;
  Redis fora → fail-closed.
- `test_bling_client.py` — 401 renova e repete uma vez; 429/5xx com backoff; 4xx de
  validação sem retry.
- `test_bling_contacts.py` — **núcleo anti-duplicação**: resolve por documento; ambíguo
  não vincula; telefone só sugere; criação sem documento é recusada; re-checagem ao vivo
  encontra e vincula em vez de criar; lock serializa criação concorrente.
- `test_bling_orders.py` — payload montado corretamente; parcelas somam o total exato
  (incluindo casos de arredondamento, ex.: 100,00 em 3x); falha transitória enfileira,
  falha de validação não.
- `test_bling_webhook.py` — assinatura inválida rejeitada; evento repetido absorvido;
  evento fora de ordem descartado; `deleted` cancela sem apagar; pedido do CRM não
  duplica ao voltar pelo webhook; contato sem lead cria lead.
- `test_bling_products.py` — sync incremental, paginação, situação.
- `test_bling_backfill.py` — janelas, retomada.

Frontend (`vitest`): geração de parcelas no cliente, cálculo de total, e o fluxo de
resolução de contato no modal.

**Baseline atual: 3.010 testes.** A suíte inteira precisa passar antes do push.

---

## 16. Fora de escopo

- Emissão de NF-e/NFC-e a partir do CRM (`gerar-nfe`, `gerar-nfce`).
- Frete, transportadora, volumes e etiquetas.
- Lançamento de contas a receber e estoque pelo CRM (`lancar-contas`, `lancar-estoque`).
- Sincronia de estoque em tempo real (webhooks `stock`/`virtual_stock`).
- Propostas comerciais / orçamentos.
- Pedidos de compra, notas de entrada, financeiro.
- Backfill além de 12 meses.

---

## 17. Riscos e limitações assumidas

| Risco | Mitigação |
|---|---|
| Bloqueio de IP por estourar `/oauth/token` (20/60s → 60 min de bloqueio) | Refresh serializado por lock Redis; token cacheado; renovação só a <5 min da expiração |
| Perda do `refresh_token` (30 dias) | Persistido no Postgres, não só no Redis; alerta em `/api/bling/status` quando faltar <5 dias |
| Webhook desabilitado pelo Bling após 3 dias de falha | Ack em <5s por construção (processamento fora do request); alerta quando eventos `pending` acumulam |
| Contato duplicado no Bling | Documento obrigatório + índice UNIQUE + lock + re-checagem ao vivo (§7) |
| Leads criados pelo webhook poluírem o funil | Stage dedicado configurável; leads entram sem `assigned_to` e sem deal |
| Divergência de preço (espelho desatualizado) | O valor enviado é o que o vendedor viu; o Bling aceita valor por item. Sync diário + webhook `product` mantêm a deriva pequena |
| `sales` legadas sem `bling_order_id` | Marcadas `origin='manual'`; nenhuma rotina as toca |
| Estouro dos 120.000 req/dia durante o backfill | Teto diário no rate limiter com margem de 8%; backfill retomável |
