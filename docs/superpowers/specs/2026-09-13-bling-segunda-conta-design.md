# Segunda conta Bling no CRM — design

Data: 2026-09-13
Branch: `worktree-bling-conta2-investigacao` (a partir de `origin/master` = `6435afc4`)

---

## 1. Objetivo

Permitir que o CRM opere **duas contas Bling simultaneamente e por tempo
indeterminado** — a atual e uma segunda de outro CNPJ — com paridade de
funcionalidade: sincronizar catálogo, criar contato, criar **orçamento**, criar
**pedido de venda** e receber **webhook** de pedido em qualquer uma das duas.

O motivo do segundo CNPJ é fiscal (pagar menos imposto). As duas contas
pertencem à mesma empresa, têm **alguns clientes em comum** e **produtos em
comum** — mas SKU e ID são diferentes em cada conta. É isso que torna o
problema um problema de chave, não de configuração.

Entradas do usuário (respostas de 13/09/2026, todas já decididas):

| # | Decisão |
|---|---|
| 1 | Mesma empresa, **outro CNPJ**, por motivo fiscal. As duas contas convivem **indefinidamente** |
| 2 | Haverá **clientes em comum** e **produtos em comum**; SKU/ID **não** coincidem entre as contas |
| 3 | **O vendedor escolhe a conta na hora** de criar orçamento/pedido. Sem motor de regra fiscal automática |
| 4 | Escopo da conta 2: **paridade total, sem backfill** — sync, emissão e webhook daqui para frente; histórico antigo não é importado |
| 5 | **Todos os vendedores operam as duas contas**. Não há permissão por usuário |
| 6 | **Orçamento e pedido são sempre na MESMA conta** — a conversão herda a conta do orçamento e não permite troca (§7) |

## 2. O problema — onde a premissa de conta única está gravada

Não existe branch nem plano anterior sobre isso. A branch
`worktree-bling-segunda-conta` existe no repositório mas está **vazia** (zero
commits à frente de `master`, working tree limpo). As cinco specs de Bling
anteriores (`2026-08-14`, `08-18`, `08-21`, `08-24`, `08-25`) são todas
mono-conta e nenhuma antecipa uma segunda.

A premissa está gravada em seis camadas:

| # | Camada | Como está hoje | Por que quebra com duas contas |
|---|---|---|---|
| 1 | Credenciais | `bling_credentials` PK `id`, com a string `'default'` chumbada em `_persist` e `_stored_row` | Só cabe um par de tokens |
| 2 | Cache/lock Redis | `bling:access_token`, `lock:bling_token_refresh`, `bling:oauth_state:` — chaves globais | **A conta 2 receberia o `access_token` da conta 1.** Bug de correção, não de config |
| 3 | Espelhos locais | `bling_products.id`, `bling_contacts.id`, `bling_sellers.id`, `bling_payment_methods.id` são `bigint PRIMARY KEY` com o ID cru do Bling | IDs do Bling são sequência **por conta** → o sync da conta 2 **sobrescreve** as linhas da conta 1 |
| 4 | Vínculos | `leads.bling_contact_id` UNIQUE; `sales.bling_order_id` UNIQUE; `quotes.bling_proposal_id` UNIQUE; `bling_seller_map.user_email` PK | Um lead só pode apontar para um contato; pedidos e propostas colidem por ID; um vendedor só tem um ID de ERP |
| 5 | Webhook | `POST /webhook/bling`, assinatura HMAC com `config.client_secret()` da conta única; `bling_webhook_events` sem coluna de conta | Um segundo aplicativo tem outro secret → **401 → o Bling retenta 3 dias e DESABILITA a configuração em silêncio**. E o worker não sabe com qual token buscar o pedido |
| 6 | Rate limit | `bling:rl:{seg}` global, sem conta | O teto do Bling (3 req/s, 120.000/dia) é **por conta** — duas contas dividiriam um orçamento só, perdendo metade da capacidade |

O que joga a favor: `BlingClient()` é instanciado fresco em **12 call sites,
sempre sem argumentos**, e tudo abaixo dele (`orders.py`, `proposals.py`) já
recebe o client **por injeção**. A camada que de fato emite orçamento e pedido
já é agnóstica de conta.

### Volumetria medida em produção (13/09/2026, somente `SELECT`)

| Tabela | Linhas | Impacto |
|---|---|---|
| `quotes` / `quote_items` | **0 / 0** | orçamento migra sem backfill |
| `bling_jobs` | 0 | livre |
| `bling_seller_map` | **1** | livre |
| `bling_credentials` | 1 | — |
| `bling_sellers` | 16 | trivial |
| `bling_payment_methods` | 45 | trivial |
| `bling_webhook_events` | 136 | trivial |
| `bling_products` | 536 | trivial |
| `sales` (com `bling_order_id`) | 1158 (**1024**) | backfill de 1024 |
| `sale_items` | 2645 | sem coluna nova |
| `bling_contacts` | 2859 | backfill |
| `leads` com `bling_contact_id` | **1479** | backfill para tabela nova |

`bling_seller_map` com **1 linha** para 16 vendedores no Bling significa que
hoje quase todo pedido sai sem vendedor. Isso **não** é escopo desta entrega,
mas está registrado em §11.

## 3. Abordagem

**Escolhida: escopo por coluna `account`, com PK composta.**

Toda tabela `bling_*` ganha `account text NOT NULL DEFAULT 'default'` e as PKs
passam a ser `(account, id)`. `sales` e `quotes` ganham `bling_account`.
`leads.bling_contact_id` vira a tabela `lead_bling_contacts`.
`BlingClient(account)` carrega a conta pelos 12 call sites. As chaves Redis
ganham a conta no nome. O webhook ganha rota por conta.

Por quê:

- Os dados existentes migram com um único `DEFAULT` — tudo vira `'default'`,
  sem ambiguidade e sem reescrita de linha.
- Um caminho de código, não dois.
- É a **única** opção que corrige o bug do cache de token cruzado (camada 2).
- Escala para um terceiro CNPJ sem nova migration — não por especulação, mas
  porque travar em exatamente duas contas daria *mais* trabalho (um booleano
  `is_conta_2` é pior em todo lugar onde aparece).

### Alternativas rejeitadas

**Tabelas paralelas (`bling2_products`, …).** Risco zero para o que está em
produção, mas duplica toda query e todo módulo — e `sales`/`quotes`/`leads` são
compartilhadas de qualquer forma, então ainda precisariam da coluna
discriminadora. Seria metade desta abordagem *mais* a manutenção de duas cópias
da outra metade. Um terceiro CNPJ vira uma terceira cópia.

**Chave sintética com prefixo (`"default:123"`).** Mantém PK de coluna única
tornando tudo `text`. Evita PK composta, mas converte todo ID `bigint` do Bling
no schema, reescreve toda linha existente e quebra o tratamento numérico no
frontend. Mais reescrita, menos clareza.

## 4. Modelo de dados

Migration: `supabase/migrations/20260913_bling_multi_conta.sql`.

### 4.1 O slug da conta existente é `'default'`

De propósito, e não por preguiça. `bling_credentials` já usa `id = 'default'`.
Renomear essa linha para `'principal'` abriria uma janela em que o código antigo
não encontra credencial nenhuma; se um refresh de token cair nessa janela, o
Bling rotaciona o `refresh_token` do lado dele e a linha nova fica com um token
já invalidado — exatamente o cenário "reautorização manual necessária" que
`auth.py` marca como catastrófico no seu próprio log `critical`.

Duplicar a linha (`'default'` + `'principal'`) é **pior**, não melhor: se o
código antigo refrescar durante a janela, ele rotaciona o token e a cópia
`'principal'` passa a guardar um `refresh_token` que o Bling já invalidou.

O nome legível ("Café Canastra — CNPJ 1") vive como **label na config**, nunca
como chave.

### 4.2 Espelhos → PK composta

```sql
ALTER TABLE bling_products        ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
ALTER TABLE bling_contacts        ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
ALTER TABLE bling_sellers         ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
ALTER TABLE bling_payment_methods ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
```

E, para cada uma, trocar a PK de `(id)` para `(account, id)`.

**Atenção à FK:** `bling_seller_map.bling_seller_id` tem
`REFERENCES bling_sellers(id)`. Ela **precisa ser derrubada antes** de trocar a
PK de `bling_sellers` e recriada como FK composta
`(account, bling_seller_id) REFERENCES bling_sellers(account, id)`.

No mesmo movimento, `bling_seller_map` ganha `account` e sua PK passa de
`(user_email)` para `(user_email, account)` — é o que permite um vendedor do CRM
ter um ID de ERP em **cada** conta (decisão 5: todos operam as duas). Uma linha
para migrar.

Os índices existentes de `bling_contacts` (doc, telefone, celular, e-mail) e de
`bling_products` (trigram no nome, código, situação) continuam válidos como
estão — não precisam da conta, porque a busca sempre filtra por conta na query.
Adicionar `account` à frente deles é otimização, não correção; fica fora.

### 4.3 Controle

```sql
-- PK (account, resource)
ALTER TABLE bling_sync_state ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';

-- PK (account, event_id) — a deteccao de repeticao por violacao de PK continua identica
ALTER TABLE bling_webhook_events ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';

-- 0 linhas hoje
ALTER TABLE bling_jobs ADD COLUMN IF NOT EXISTS account text NOT NULL DEFAULT 'default';
```

`bling_credentials` **não muda de schema** — `id text PRIMARY KEY` já comporta
uma linha por conta. Só passa a receber mais linhas.

### 4.4 Contato do lead

```sql
CREATE TABLE IF NOT EXISTS lead_bling_contacts (
  lead_id          uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  account          text NOT NULL,
  bling_contact_id bigint NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (lead_id, account)
);

-- Preserva a garantia estrutural da migration 20260818: um contato do ERP
-- pertence a no maximo um lead. Agora por conta.
CREATE UNIQUE INDEX IF NOT EXISTS lead_bling_contacts_account_contact_key
  ON lead_bling_contacts (account, bling_contact_id);

-- Backfill: 1479 linhas
INSERT INTO lead_bling_contacts (lead_id, account, bling_contact_id)
SELECT id, 'default', bling_contact_id
  FROM leads
 WHERE bling_contact_id IS NOT NULL
ON CONFLICT DO NOTHING;
```

`leads.bling_contact_id` **não é derrubada agora**. Ela continua existindo
(código antigo ainda a lê durante a janela de deploy) e cai numa migration
posterior, depois que a versão nova estabilizar. Enquanto isso ela fica estagnada
— o código novo lê e escreve apenas na tabela.

### 4.5 Vendas e orçamentos

```sql
ALTER TABLE sales  ADD COLUMN IF NOT EXISTS bling_account text;  -- NULL para venda manual
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS bling_account text;

UPDATE sales SET bling_account = 'default' WHERE bling_order_id IS NOT NULL;  -- 1024 linhas

DROP INDEX IF EXISTS sales_bling_order_id_key;
CREATE UNIQUE INDEX sales_bling_order_key ON sales (bling_account, bling_order_id);

ALTER TABLE quotes DROP CONSTRAINT IF EXISTS quotes_bling_proposal_id_key;
CREATE UNIQUE INDEX quotes_bling_proposal_key ON quotes (bling_account, bling_proposal_id);
```

> **Armadilha já paga uma vez neste repo.** `_upsert_sale` em `orders.py` usa
> `on_conflict="bling_order_id"`. Com o índice composto ele **precisa** virar
> `on_conflict="bling_account,bling_order_id"`. Sem isso volta o `42P10`
> (*"no unique or exclusion constraint matching the ON CONFLICT
> specification"*) que derrubou **todo** upsert de pedido em produção e está
> documentado em `20260818_bling_integration.sql`. Índice **não-parcial**, pelo
> mesmo motivo de lá: o `on_conflict=` do PostgREST emite só a lista de colunas,
> nunca o `WHERE`.

`sale_items.bling_product_id` e `quote_items.bling_product_id` **não** ganham
coluna: o produto é sempre lido na conta do pai (`sales.bling_account` /
`quotes.bling_account`). Isso mantém a migration menor e não cria uma segunda
fonte de verdade para a mesma informação.

Ao final, `NOTIFY pgrst, 'reload schema';` — o PostgREST não enxerga coluna nova
sem recarregar o cache de schema.

## 5. Backend

### 5.1 `config.py` — env por conta com fallback

Mantém o padrão documentado do módulo (env cru via `os.getenv`, nunca campo no
`Settings` do pydantic). **Nenhuma variável de hoje muda de nome ou de valor.**

```
BLING_ACCOUNTS=default,secundaria          # ausente => so 'default' (retrocompativel)
BLING_SECUNDARIA_LABEL="Canastra CNPJ 2"
BLING_SECUNDARIA_CLIENT_ID=...             # ausente => cai para BLING_CLIENT_ID
BLING_SECUNDARIA_CLIENT_SECRET=...         # ausente => cai para BLING_CLIENT_SECRET
BLING_SECUNDARIA_STORE_ID=...
BLING_SECUNDARIA_ORDER_SITUACAO_ID=...
```

O fallback para a variável global resolve as duas topologias possíveis sem
decidir por antecipação:

- **Um único aplicativo Bling autorizado nas duas contas** (caminho natural do
  OAuth): `client_id`/`client_secret` são compartilhados; só entram label e
  `store_id`/`situacao_id`.
- **Dois aplicativos distintos**: preenche-se os dois pares.

A conta `'default'` lê exatamente as variáveis de hoje (`BLING_CLIENT_ID`, …),
sem sufixo.

Interface nova:

```python
@dataclass(frozen=True)
class BlingAccount:
    key: str
    label: str
    client_id: str
    client_secret: str
    store_id: int | None
    situacao_id: int | None

def accounts() -> list[BlingAccount]: ...
def account(key: str) -> BlingAccount: ...   # levanta BlingUnknownAccount
def is_configured(key: str = "default") -> bool: ...
```

`enabled()` continua global (`BLING_ENABLED`) — liga/desliga a integração
inteira, não uma conta.

`BLING_DATE_MARGIN_HOURS` (em `dates.py`) continua global: é margem de
tolerância de data, não tem relação com conta.

### 5.2 `client.py`

`BlingClient(account: str = "default")`. A conta desce para `_headers()` (que
chama `auth.get_access_token(account)`), para o rate limit e para o retry de
401 (`auth.invalidate_cache(account)`).

Os 12 call sites passam a derivar a conta do request, da linha do banco ou do
laço — **nunca** de um default implícito no meio do caminho. O default no
construtor existe só para não quebrar os testes existentes.

### 5.3 `auth.py`

Tudo que hoje é global vira por conta:

| Hoje | Passa a ser |
|---|---|
| `_CACHE_KEY = "bling:access_token"` | `f"bling:{account}:access_token"` |
| `_LOCK_KEY = "lock:bling_token_refresh"` | `f"lock:bling_token_refresh:{account}"` |
| `_persist` grava `"id": "default"` | grava `"id": account` |
| `_stored_row()` filtra `.eq("id","default")` | `_stored_row(account)` |
| `_basic_auth_header()` | credenciais da conta |
| `status()` → dict | `status()` → **lista**, uma entrada por conta |

**O `state` do OAuth passa a carregar a conta.** Hoje `new_state()` grava o
valor `"1"` no Redis e `consume_state` devolve só um bool. Com duas contas,
`/oauth/callback` não teria como saber qual está sendo conectada — e autorizar
a conta 2 sobrescreveria o token da conta 1. Então:

```python
async def new_state(account: str) -> str: ...        # grava o slug como valor
async def consume_state(state: str) -> str | None:   # devolve a conta, ou None
```

### 5.4 `ratelimit.py`

`bling:rl:{account}:{seg}` e a chave diária idem. Cada conta passa a ter o
orçamento que o Bling de fato lhe dá (3 req/s, 120.000/dia **por conta**).

### 5.5 Webhook

Nasce `POST /webhook/bling/{account}`:

1. Resolve a conta pelo slug; **desconhecida → 404**. É erro de configuração no
   painel do Bling e precisa ser barulhento, não absorvido com 200.
2. Valida o HMAC com o `client_secret` **daquela** conta.
3. Grava o evento já com a coluna `account`.

> **A rota legada `POST /webhook/bling` (sem slug) CONTINUA existindo**,
> mapeada para `'default'`. O painel da conta 1 já aponta para ela; se ela
> sumir, os webhooks passam a 404 e o Bling **desabilita a configuração em
> silêncio depois de 3 dias** de retentativa — a integração para sem erro
> visível. Reapontar o painel da conta 1 para a rota nova é passo posterior e
> opcional.

### 5.6 Worker

`sync.py`, `jobs.py` e o tick de webhook iteram `config.accounts()` com
`try/except` **por conta**: falha na conta 2 não pode matar o sync da conta 1.

`webhook_processor` lê a conta da própria linha do evento (`evento["account"]`)
em vez de iterar — é mais direto e evita processar o evento com o cliente
errado. `_contact_row` e `_sale_event_date` passam a receber a conta.

`backfill.py` recebe a conta como parâmetro, mas **não é executado para a conta
2** (decisão 4: sem backfill).

### 5.7 `contacts.py`

`ensure_lead` continua casando lead por telefone/documento/e-mail — essa lógica
não muda. O que muda é onde o vínculo é gravado: `lead_bling_contacts`, com a
conta. Um lead que já tem contato na conta 1 simplesmente ganha uma **segunda
linha** quando aparecer na conta 2, que é o caso "alguns clientes em comum".

`/contacts/link` e `/contacts/unlink` passam a receber a conta.

## 6. Frontend

**A conta é o primeiro campo do formulário**, acima de tudo — tanto no modal de
pedido (`bling-order-form.tsx`) quanto em `/orcamento`. Precisa ser o primeiro
porque tudo abaixo dele (catálogo, contato, forma de pagamento, vendedor) é
escopado por ele.

**Trocar a conta limpa itens, contato e forma de pagamento**, com confirmação
que só aparece se já houver algo preenchido. Não há alternativa honesta:
os SKU/ID não coincidem entre as contas (decisão 2), então remapear os itens
seria adivinhação com risco de emitir pedido com o produto errado.

**Com uma conta só configurada, o seletor não aparece.** A feature inteira fica
invisível até `BLING_ACCOUNTS` listar a segunda — nada muda visualmente para
quem usa o CRM hoje.

**Endpoints de leitura ganham `?account=`:** `/products`, `/catalog`,
`/contacts/search`, `/payment-methods`, `/sellers`. Ausente = `'default'`,
retrocompatível.

**`/config` lista uma linha por conta** (`bling-settings.tsx`): label, conectado
ou não, validade do token e botão "Conectar" chamando
`/oauth/authorize?account=…`. `GET /api/bling/status` passa a devolver lista;
`use-bling-status.ts` e `bling-gate.ts` acompanham. O gate vira **por conta**: o
seletor só oferece contas efetivamente conectadas.

**Deep links para o painel do Bling.** `BLING_ORDER_URL_TEMPLATE`
(`sale-display.ts`) e `BLING_CONTACT_URL_TEMPLATE`
(`bling-contact-display.ts`) são constantes hardcoded no frontend, apesar do
nome sugerir env var. Com duas contas o link fica ambíguo: ele abre no painel da
conta em que o usuário estiver logado. **Não há solução completa** — o Bling não
expõe URL que force a conta. O que se faz é **rotular a conta ao lado do link**
("Pedido #1234 · Canastra CNPJ 2"), para o vendedor saber em qual painel entrar
antes de clicar. A limitação é assumida, não disfarçada.

## 7. Invariante: orçamento e pedido na mesma conta

**Um orçamento criado na conta X só pode virar pedido na conta X.** A proposta
comercial vive naquela conta do ERP, e os IDs de contato e produto do pedido
precisam ser os daquela conta — um pedido emitido na conta errada referenciaria
IDs que não existem lá, ou pior, IDs que existem e apontam para outro produto.

Como é garantido:

1. `quotes.bling_account` é gravado na criação do orçamento e **nunca é
   editável** depois (o `PUT /api/quotes/{id}` ignora qualquer conta no corpo).
2. `POST /api/quotes/{quote_id}/convert` **não aceita conta** — nem hoje recebe
   corpo. Ele lê `quote["bling_account"]` e é essa a conta usada para criar o
   pedido. A invariante sai de graça da assinatura do endpoint.
3. No modal de conversão, o seletor de conta aparece **desabilitado**, exibindo
   a conta do orçamento, com a dica "definido pelo orçamento #N". Mostrar
   desabilitado, em vez de esconder, é o que ensina a regra ao vendedor.
4. Teste de regressão: converter um orçamento da conta `secundaria` cria a venda
   com `sales.bling_account = 'secundaria'`.

A mesma invariante vale para a situação inversa, já coberta por §4.5: a venda
gerada herda `bling_account` do orçamento, então o índice único composto
`(bling_account, bling_order_id)` nunca vê a venda migrar de conta.

## 8. Testes

Os ~16 arquivos de teste de Bling existentes devem passar **sem mudança de
comportamento** — o default `account="default"` mantém as chamadas antigas
válidas. Onde a assinatura mudar (ex.: `consume_state`), o teste é ajustado, não
reescrito.

Testes novos:

| Arquivo | Cobre |
|---|---|
| `test_bling_config.py` | `accounts()` com e sem `BLING_ACCOUNTS`; fallback de credencial para a global; slug desconhecido levanta |
| `test_bling_auth.py` | **chaves Redis distintas por conta** (regressão direta do bug de token cruzado); `state` carregando o slug; `_persist` gravando no `id` certo |
| `test_bling_ratelimit.py` | contadores independentes por conta; o teto de uma não consome o da outra |
| `test_bling_webhook.py` | rota por conta; rota **legada** → `'default'`; slug desconhecido → 404; HMAC validado com o secret da conta correta |
| `test_bling_orders.py` | `on_conflict` composto; upsert não colide entre contas com o mesmo `bling_order_id` |
| `test_bling_contacts.py` | `lead_bling_contacts`; **o mesmo lead vinculado nas duas contas**; unicidade contato↔lead por conta |
| `test_quotes_*.py` | invariante de §7: conversão herda a conta e não aceita troca |
| Frontend | troca de conta limpa itens; seletor oculto com uma conta só; seletor desabilitado na conversão |

> **Teste verde não basta no `on_conflict`.** A migration `20260818` documenta
> que os dubles do Supabase **não pegam** falha de inferência de ON CONFLICT —
> o `42P10` só aparece contra o Postgres real. Esse ponto exige verificação
> manual contra o banco antes do push.

## 9. Ordem de subida e a janela de risco

O repo aplica migration **à mão** no SQL editor do Supabase antes do push (o
GitHub Actions sobe imagem, não roda migration).

1. Aplicar `20260913_bling_multi_conta.sql` no Supabase.
2. **Push imediatamente em seguida.**
3. Só então configurar `BLING_ACCOUNTS` no `.env` da VPS e conectar a conta 2
   via OAuth em `/config`.

> ⚠️ **Existe uma janela real entre os passos 1 e 2.** Com a PK já composta e o
> código antigo ainda no ar, todo upsert com `on_conflict="id"` toma `42P10`:
> o **sync de catálogo e a criação de pedido falham** nesse intervalo. Por isso
> os passos 1 e 2 precisam ser consecutivos e em **horário de baixo movimento**.
> Um vendedor que emitir pedido dentro da janela recebe erro.

Até o passo 3 acontecer, o sistema roda **idêntico** ao de hoje: uma conta,
mesmo comportamento, seletor invisível.

## 10. Riscos e pontos a validar em produção

| Risco | Mitigação |
|---|---|
| `42P10` volta por `on_conflict` desatualizado em algum call site | Varredura explícita por `on_conflict=` em todo `app/bling` e `app/quotes`; verificação manual contra o Postgres real (§8) |
| A rota legada de webhook é removida por engano | Teste dedicado garantindo que `POST /webhook/bling` sem slug responde 200 e grava com `account='default'` |
| Autorizar a conta 2 sobrescreve o token da conta 1 | O `state` carrega o slug (§5.3) + teste de chaves Redis distintas |
| Backfill de `lead_bling_contacts` diverge de `leads.bling_contact_id` | `ON CONFLICT DO NOTHING` + conferência de contagem (esperado: 1479) após aplicar |
| Janela de deploy atinge um vendedor emitindo pedido | Horário de baixo movimento; passos 1 e 2 consecutivos |
| Vendedor emite na conta errada por desatenção | Fora de alcance técnico — decisão 3 é escolha manual. Mitigado só pelo rótulo da conta visível no formulário e no link |

## 11. Fora de escopo

- **Backfill do histórico da conta 2** (decisão 4).
- **Motor de regra fiscal** que escolha a conta sozinho (decisão 3).
- **Permissão de conta por usuário** (decisão 5: todos operam as duas).
- **Derrubar `leads.bling_contact_id`** — migration posterior, depois da
  estabilização.
- **Preencher `bling_seller_map`** para os 16 vendedores. O achado de §2 (1
  linha apenas, quase todo pedido sai sem vendedor) é anterior a esta entrega e
  não é regressão dela. A tela de mapeamento passa a ser por conta; popular os
  dados é decisão separada.
- **Índices com `account` à frente** nos espelhos — otimização, não correção.
- **URL de painel do Bling que force a conta** — não existe na plataforma (§6).
