# Segunda conta Bling no CRM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o CRM operar duas contas Bling (dois CNPJs) em paralelo e por tempo indeterminado, com paridade de sync, emissão de orçamento/pedido e recebimento de webhook em ambas.

**Architecture:** Escopo por coluna `account` em todas as tabelas derivadas do Bling, com PK composta `(account, id)` nos espelhos. A conta viaja no construtor de `BlingClient` e por parâmetro nas funções de `auth`/`ratelimit`, o que namespaceia as chaves Redis e separa os orçamentos de rate limit. O webhook ganha rota por conta, mantendo a legada apontada para `'default'`. A conta existente mantém o slug `'default'` para não abrir janela de reautorização.

**Tech Stack:** Python 3 / FastAPI / pytest (`asyncio_mode = auto`) no backend; Next.js App Router / TypeScript / vitest no frontend; Postgres via Supabase (PostgREST) com migrations aplicadas à mão.

**Spec:** `docs/superpowers/specs/2026-09-13-bling-segunda-conta-design.md`

---

## Como rodar os testes

```bash
# Backend — sempre a partir de backend/
cd backend && python -m pytest tests/ -q

# Um arquivo
cd backend && python -m pytest tests/test_bling_config.py -v

# Frontend — sempre a partir de frontend/
cd frontend && npm test
```

## Antes de mudar QUALQUER resposta de API: ache TODOS os consumidores

Regra nascida de um erro real cometido nesta entrega, duas vezes seguidas.

Ao alterar o corpo de uma resposta, **não basta conferir o consumidor que você
conhece**. Faça `grep` por *cada nome de campo* que a resposta devolve, no
frontend inteiro. Em `/api/bling/status` havia dois consumidores independentes:
`use-bling-status.ts` (o hook, que todo mundo lembra) e
`bling-settings.tsx` (que faz `fetch` direto e lê `configured`,
`access_expires_at`, `refresh_expires_at` e `scope`).

O segundo passou despercebido e o "formato aditivo" derrubou os quatro campos.
Consequência: banner de erro permanente, aviso de expiração do refresh_token
nunca mais dispara, e o botão **"Conectar ao Bling" fica desabilitado para
sempre** — ou seja, ninguém consegue autorizar conta nenhuma pela tela, que é
exatamente o que a segunda conta precisa.

O TypeScript não pega isso: `bling-settings.tsx` faz `body as BlingStatus`, um
cast sem checagem. Teste de backend também não pega — os testes foram escritos
contra o consumidor que eu conhecia.

## Mapa completo dos consumidores de `/api/bling/*`

Levantado por `grep` em 14/09/2026, depois de errar duas vezes por conferir só o
consumidor que eu lembrava. **Esta é a lista autoritativa.**

### ⚠️ A camada de proxy do Next — o ponto mais perigoso da entrega

O frontend **não fala direto com o FastAPI**. Existem 13 rotas
`frontend/src/app/api/bling/**/route.ts` que encaminham. E elas **não repassam a
query string**: cada uma monta uma URL nova a partir de uma lista fixa de
parâmetros (`products/route.ts` monta `?limit=&q=`; `catalog/route.ts` monta
`q`, `situacao`, `page`, `limit`).

Consequência se forem esquecidas: o vendedor escolhe a conta 2, o componente
manda `?account=secundaria`, **o proxy descarta**, o backend cai no default e o
**pedido é emitido no CNPJ errado — sem erro nenhum na tela.** É o pior modo de
falha possível nesta entrega, e nenhum teste de backend o pega, porque o backend
recebe exatamente o que o proxy mandou.

| Proxy | Precisa repassar `account`? |
|---|---|
| `api/bling/products/route.ts` | **Sim** — monta `?limit=&q=` |
| `api/bling/catalog/route.ts` | **Sim** — monta `q/situacao/page/limit` |
| `api/bling/contacts/search/route.ts` | **Sim** |
| `api/bling/contacts/route.ts` (POST) | **Sim** — no corpo |
| `api/bling/contacts/link/route.ts` | **Sim** — query string |
| `api/bling/contacts/unlink/route.ts` | **Sim** — query string |
| `api/bling/payment-methods/route.ts` | **Sim** |
| `api/bling/sellers/route.ts` | **Sim** |
| `api/bling/orders/route.ts` (POST) | **Sim** — no corpo |
| `api/bling/orders/[order_id]/route.ts` (PUT) | **Sim** — no corpo |
| `api/bling/oauth/authorize/route.ts` | **Sim** — query string |
| `api/bling/sync/route.ts` | Opcional (sync roda todas as contas) |
| `api/bling/status/route.ts` | Não repassa `account`, mas **corta a resposta** — ver abaixo |

### ⚠️ O proxy de `status` corta o payload para não-admin

`api/bling/status/route.ts` devolve o objeto **completo** para `role === "admin"`
e apenas `{enabled, connected}` para todos os outros. O comentário explica por
quê, e a razão é boa: expiração de token e escopos do OAuth são informação de
administração e não têm por que circular na tela de venda.

Mas com a segunda conta isso vira uma armadilha: **`accounts` não chega ao
vendedor**. O seletor da Task 15 receberia lista vazia, `precisaSeletor([])`
daria `false`, o seletor não apareceria — e **toda venda iria para a conta
padrão**, em silêncio.

O que torna este caso pior que os outros: **um admin testando a feature veria
tudo funcionar.** A falha só aparece para quem tem `role` de vendedor — exatamente
quem usa o modal.

Correção (Task 14 ou 16): o não-admin passa a receber `accounts` numa forma
**reduzida**, preservando a intenção de segurança original:

```ts
    if (role !== "admin") {
      return Response.json({
        enabled: !!status.enabled,
        connected: !!status.connected,
        // O vendedor precisa saber QUAIS contas existem e quais estao
        // conectadas — sem isso o seletor de conta nao tem o que renderizar e
        // toda venda cai na conta padrao em silencio. O que ele NAO recebe
        // continua sendo o mesmo de antes: expiracao de token e escopos OAuth.
        accounts: (status.accounts || []).map((c: BlingAccountStatus) => ({
          account: c.account,
          label: c.label,
          configured: c.configured,
          connected: c.connected,
        })),
      });
    }
```

Teste obrigatório: com `role` de vendedor, a resposta traz `accounts` com
`account`/`label`/`connected`/`configured` e **não** traz `access_expires_at`,
`refresh_expires_at` nem `scope`.

### Componentes e páginas que consomem

| Arquivo | Endpoints | Task |
|---|---|---|
| `hooks/use-bling-status.ts` | `status` | 14 |
| `components/config/bling-settings.tsx` | `status`, `sellers`, `oauth/authorize`, `sync` | 16 |
| `components/sales/bling-order-form.tsx` | `payment-methods`, `products` | 15 |
| `components/sales/sale-create-modal.tsx` | `orders` (POST e PUT) | 15 |
| `components/sales/bling-contact-resolver.tsx` | `contacts`, `contacts/link` | 15 |
| `components/leads/lead-bling-section.tsx` | `contacts/search`, `contacts/link`, `contacts/unlink` | 15 |
| `app/(authenticated)/produtos/page.tsx` | `catalog` | **não estava no plano** |

> A página `/produtos` lista o catálogo do espelho e não estava em nenhuma task.
> Com duas contas ela passa a misturar os catálogos dos dois CNPJs numa lista
> só, com códigos repetidos e sem dizer de quem é cada produto. Precisa de um
> seletor de conta ou de uma coluna indicando a conta — decidir na Task 16.

## Decisões transversais (valem para TODAS as tasks)

**1. Nunca escreva o literal `"default"`.** Use `config.DEFAULT_ACCOUNT`. Todos os
módulos de `app/bling` já fazem `from app.bling import config`. O slug é a chave
de tudo — cache Redis, lock, linha de credencial, coluna no Postgres — e um
literal espalhado por 15 arquivos diverge da fonte de verdade no primeiro ajuste.

**2. A validação e a normalização do slug moram em `BlingClient.__init__`.**
Decisão explícita, tomada na revisão da Task 2. O construtor faz:

```python
        # Normaliza e VALIDA aqui, no unico ponto por onde toda chamada HTTP ao
        # Bling passa. Sem isso, um slug com caixa ou espaco errado ("Secundaria",
        # " secundaria") nao levanta erro nenhum: ele abre em silencio um
        # namespace novo e sem governanca no Redis — orcamento de rate limit
        # proprio, cache de token proprio, lock proprio. O erro so apareceria
        # como "a conta 2 estourou o limite" sem causa visivel.
        self._account = config.account(account).key
```

`ratelimit.acquire` e as funções de `auth` continuam recebendo a string já
normalizada e **não** revalidam — o client é o gargalo, e revalidar em cada
camada só multiplicaria o custo sem cobrir nenhum caminho novo.

**3. Default de conta só na superfície PÚBLICA. Função privada exige o
parâmetro.** Convenção já estabelecida por `ratelimit.py`: `_second_key` e
`_day_key` (privadas) exigem a conta; só `acquire()` (pública) tem default.

O motivo não é estética: um default numa função privada permite que um chamador
*dentro do próprio módulo* omita a conta em silêncio e opere no CNPJ errado — a
classe exata de bug que esta entrega existe para eliminar. Com o parâmetro
obrigatório, o mesmo erro vira `TypeError` na hora.

Vale para todas as tasks. Onde um snippet deste plano mostrar
`account: str = config.DEFAULT_ACCOUNT` numa função com `_` no início, **o
snippet está errado** — use `account: str` sem default e ajuste os chamadores.

**4. Dublê de teste também exige o parâmetro.** `def fake_x(_account)`, nunca
`def fake_x(_account=None)`. Um dublê com default aceita ser chamado com ou sem
o argumento, então uma regressão em que a produção para de repassar a conta
passaria despercebida — e o `monkeypatch` substitui a função real inteira, então
a assinatura do dublê é a **única** coisa que sustenta o contrato durante aquele
teste. Isto não é redundante com a regra 3: as duas se somam.

Isso importa nas duas entradas onde a string vem de fora e é menos confiável: o
`?account=` da Task 11 (query param HTTP) e a conta lida da linha do banco na
Task 10. Nas duas, o erro vira `BlingUnknownAccount` e sobe como 400/404, em vez
de virar um namespace fantasma.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `backend/app/bling/errors.py` | Hierarquia de erros | Modificar — `BlingUnknownAccount` |
| `backend/app/bling/config.py` | Config por conta, fonte única do roster | Modificar — `BlingAccount`, `accounts()`, `account()` |
| `backend/app/bling/client.py` | HTTP + auth + rate limit | Modificar — `account` no construtor |
| `backend/app/bling/ratelimit.py` | Orçamento de requisições | Modificar — chaves por conta |
| `backend/app/bling/auth.py` | OAuth, tokens, cache | Modificar — storage/cache/state por conta |
| `backend/app/bling/sync.py` | Sync de espelhos | Modificar — laço por conta |
| `backend/app/bling/products.py` | Espelho de produtos | Modificar — `account` no upsert |
| `backend/app/bling/contacts.py` | Espelho de contatos + vínculo do lead | Modificar — `lead_bling_contacts` |
| `backend/app/bling/orders.py` | Pedido de venda | Modificar — `on_conflict` composto |
| `backend/app/bling/jobs.py` | Fila de jobs | Modificar — `account` na linha |
| `backend/app/bling/backfill.py` | Importação histórica | Modificar — conta por parâmetro |
| `backend/app/bling/webhook_router.py` | Receiver | Modificar — rota por conta + legada |
| `backend/app/bling/webhook_processor.py` | Worker de eventos | Modificar — conta vinda da linha |
| `backend/app/bling/router.py` | API `/api/bling` | Modificar — `?account=` e OAuth por conta |
| `backend/app/quotes/router.py` | API `/api/quotes` | Modificar — `bling_account` + invariante |
| `supabase/migrations/20260913_bling_multi_conta.sql` | Schema | **Criar** |
| `frontend/src/hooks/use-bling-status.ts` | Status das contas | Modificar — lista |
| `frontend/src/lib/bling-gate.ts` | Gate do modal | Modificar — por conta |
| `frontend/src/lib/bling-accounts.ts` | Lógica pura de seleção de conta | **Criar** |
| `frontend/src/components/sales/bling-order-form.tsx` | Modal de pedido | Modificar — seletor |
| `frontend/src/components/config/bling-settings.tsx` | `/config` | Modificar — uma linha por conta |
| `frontend/src/lib/sale-display.ts` | Deep link do pedido | Modificar — rótulo da conta |
| `frontend/src/lib/bling-contact-display.ts` | Deep link do contato | Modificar — rótulo da conta |

---

## Task 1: `BlingUnknownAccount` e o roster de contas

**Files:**
- Modify: `backend/app/bling/errors.py`
- Modify: `backend/app/bling/config.py`
- Test: `backend/tests/test_bling_config.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicionar ao fim de `backend/tests/test_bling_config.py`:

```python
import pytest

from app.bling.errors import BlingUnknownAccount


@pytest.fixture
def duas_contas(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")


def test_accounts_sem_env_devolve_so_a_default(monkeypatch):
    monkeypatch.delenv("BLING_ACCOUNTS", raising=False)
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    contas = cfg.accounts()
    assert [c.key for c in contas] == ["default"]
    assert contas[0].client_id == "cid"


def test_accounts_normaliza_espaco_e_caixa(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", " default , SECUNDARIA ")
    assert [c.key for c in cfg.accounts()] == ["default", "secundaria"]


def test_accounts_vazio_cai_para_default(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "   ,  ")
    assert [c.key for c in cfg.accounts()] == ["default"]


def test_conta_default_nunca_usa_sufixo(monkeypatch):
    monkeypatch.delenv("BLING_ACCOUNTS", raising=False)
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    monkeypatch.setenv("BLING_DEFAULT_CLIENT_ID", "NAO_USAR")
    assert cfg.account("default").client_id == "cid"


def test_conta_secundaria_cai_para_credencial_global(duas_contas, monkeypatch):
    monkeypatch.delenv("BLING_SECUNDARIA_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLING_SECUNDARIA_CLIENT_SECRET", raising=False)
    sec = cfg.account("secundaria")
    assert sec.client_id == "cid"
    assert sec.client_secret == "csec"


def test_conta_secundaria_prefere_credencial_propria(duas_contas, monkeypatch):
    monkeypatch.setenv("BLING_SECUNDARIA_CLIENT_ID", "cid2")
    monkeypatch.setenv("BLING_SECUNDARIA_CLIENT_SECRET", "csec2")
    sec = cfg.account("secundaria")
    assert sec.client_id == "cid2"
    assert sec.client_secret == "csec2"


def test_store_id_e_situacao_sao_por_conta(duas_contas, monkeypatch):
    monkeypatch.setenv("BLING_STORE_ID", "111")
    monkeypatch.setenv("BLING_SECUNDARIA_STORE_ID", "222")
    monkeypatch.setenv("BLING_SECUNDARIA_ORDER_SITUACAO_ID", "9")
    assert cfg.account("default").store_id == 111
    assert cfg.account("secundaria").store_id == 222
    assert cfg.account("secundaria").situacao_id == 9


def test_label_cai_para_a_propria_key(duas_contas, monkeypatch):
    monkeypatch.delenv("BLING_SECUNDARIA_LABEL", raising=False)
    assert cfg.account("secundaria").label == "secundaria"


def test_label_le_do_env(duas_contas, monkeypatch):
    monkeypatch.setenv("BLING_SECUNDARIA_LABEL", "Canastra CNPJ 2")
    assert cfg.account("secundaria").label == "Canastra CNPJ 2"


def test_conta_desconhecida_levanta(duas_contas):
    with pytest.raises(BlingUnknownAccount):
        cfg.account("naoexiste")


def test_unknown_account_nao_e_transient():
    from app.bling.errors import TRANSIENT
    assert issubclass(BlingUnknownAccount, BlingError)
    assert BlingUnknownAccount not in TRANSIENT
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_config.py -q`
Expected: FAIL — `ImportError: cannot import name 'BlingUnknownAccount'`

- [ ] **Step 3: Adicionar o erro**

Em `backend/app/bling/errors.py`, logo depois de `BlingNotConfigured`:

```python
class BlingUnknownAccount(BlingError):
    """Slug de conta que nao esta em BLING_ACCOUNTS. Erro de configuracao."""
```

Não incluir em `TRANSIENT`: repetir com o mesmo slug errado nunca conserta.

- [ ] **Step 4: Implementar o roster em `config.py`**

No topo, junto dos imports:

```python
from dataclasses import dataclass

DEFAULT_ACCOUNT = "default"
```

E ao fim do arquivo (as funções antigas `client_id()`, `client_secret()`,
`store_id()`, `order_situacao_id()` e `is_configured()` **continuam como estão**
— outros módulos ainda as usam nas tasks seguintes):

> Nota posterior: `require_credentials()` também sobreviveu à Task 1, mas foi
> **removida na Task 4**, quando `authorize_url` — seu último chamador — passou a
> usar `conta.configured`. Deixar um ajudante mono-conta num módulo que virou
> multi-conta convida alguém a pegar o errado.

```python
@dataclass(frozen=True)
class BlingAccount:
    """Uma conta Bling configurada. `key` e o slug usado como chave em tudo."""
    key: str
    label: str
    client_id: str
    client_secret: str
    store_id: int | None
    situacao_id: int | None


def _suffixed(name: str, account: str) -> str:
    """BLING_<CONTA>_<NAME>. A conta default NUNCA recebe sufixo — e o que
    mantem todas as variaveis de ambiente de hoje valendo sem alteracao."""
    if account == DEFAULT_ACCOUNT:
        return f"BLING_{name}"
    return f"BLING_{account.upper()}_{name}"


def _env_for(name: str, account: str) -> str:
    """Valor da conta, caindo para a variavel global quando a especifica falta.

    O fallback e o que permite um unico aplicativo Bling autorizado nas duas
    contas: client_id/secret sao compartilhados e so o label e o store_id
    entram por conta.
    """
    return _env(_suffixed(name, account)) or _env(f"BLING_{name}")


def _env_int_for(name: str, account: str) -> int | None:
    bruto = _env_for(name, account)
    if not bruto:
        return None
    try:
        return int(bruto)
    except ValueError:
        logger.warning("Valor invalido para %s: %r (esperava inteiro)",
                       _suffixed(name, account), bruto)
        return None


def account_keys() -> list[str]:
    """Slugs configurados. Ausencia de BLING_ACCOUNTS => so a conta default."""
    bruto = _env("BLING_ACCOUNTS")
    if not bruto:
        return [DEFAULT_ACCOUNT]
    chaves = [p.strip().lower() for p in bruto.split(",") if p.strip()]
    return chaves or [DEFAULT_ACCOUNT]


def account(key: str = DEFAULT_ACCOUNT) -> BlingAccount:
    from app.bling.errors import BlingUnknownAccount

    key = (key or DEFAULT_ACCOUNT).strip().lower()
    if key not in account_keys():
        raise BlingUnknownAccount(f"conta Bling desconhecida: {key!r}")
    return BlingAccount(
        key=key,
        # LABEL nao usa _env_for de proposito: nao faz sentido a conta 2 herdar
        # o rotulo da conta 1 — o rotulo existe justamente para distingui-las.
        label=_env(_suffixed("LABEL", key)) or key,
        client_id=_env_for("CLIENT_ID", key),
        client_secret=_env_for("CLIENT_SECRET", key),
        store_id=_env_int_for("STORE_ID", key),
        situacao_id=_env_int_for("ORDER_SITUACAO_ID", key),
    )


def accounts() -> list[BlingAccount]:
    return [account(k) for k in account_keys()]
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_config.py -q`
Expected: PASS, incluindo todos os testes que já existiam no arquivo.

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/errors.py backend/app/bling/config.py backend/tests/test_bling_config.py
git commit -m "feat(bling): roster de contas em config com fallback para credencial global"
```

---

## Task 2: Rate limit e client por conta

**Files:**
- Modify: `backend/app/bling/ratelimit.py`
- Modify: `backend/app/bling/client.py:49-90`
- Test: `backend/tests/test_bling_ratelimit.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicionar a `backend/tests/test_bling_ratelimit.py`:

```python
def test_chave_do_segundo_inclui_a_conta():
    from app.bling import ratelimit
    assert ratelimit._second_key(1757800000.4, "default") == "bling:rl:default:1757800000"
    assert ratelimit._second_key(1757800000.4, "secundaria") == "bling:rl:secundaria:1757800000"


def test_chave_do_dia_inclui_a_conta():
    from app.bling import ratelimit
    a = ratelimit._day_key("default")
    b = ratelimit._day_key("secundaria")
    assert a.startswith("bling:rl:default:day:")
    assert b.startswith("bling:rl:secundaria:day:")
    assert a != b


def test_contas_nao_compartilham_orcamento():
    """O teto do Bling e POR CONTA (3 req/s, 120k/dia). Chave compartilhada
    faria duas contas dividirem um orcamento so."""
    from app.bling import ratelimit
    agora = 1757800000.0
    assert ratelimit._second_key(agora, "default") != ratelimit._second_key(agora, "secundaria")
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_ratelimit.py -q`
Expected: FAIL — `TypeError: _second_key() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Implementar as chaves por conta**

Em `backend/app/bling/ratelimit.py`, substituir as duas funções de chave e a
assinatura de `acquire`:

```python
def _second_key(now: float, account: str) -> str:
    return f"bling:rl:{account}:{int(now)}"


def _day_key(account: str) -> str:
    return (f"bling:rl:{account}:day:"
            + datetime.now(timezone.utc).strftime("%Y-%m-%d"))


async def acquire(account: str = config.DEFAULT_ACCOUNT) -> None:
```

E dentro do corpo de `acquire`, na chamada `eval`:

```python
                _second_key(now, account), _day_key(account),
```

- [ ] **Step 4: Passar a conta pelo `BlingClient`**

Em `backend/app/bling/client.py`, no `__init__` (linha ~49):

```python
    def __init__(self, http: Any | None = None, timeout: float = 30.0,
                 max_attempts: int = _MAX_ATTEMPTS,
                 account: str = config.DEFAULT_ACCOUNT):
        self._http = http
        self._owns_http = http is None
        self._timeout = timeout
        self._max_attempts = max_attempts
        # A conta viaja na instancia, nunca num default implicito no meio do
        # caminho: e o que garante que cada chamada use o token e o orcamento
        # de rate limit da conta certa.
        self._account = account
```

Em `_headers`:

```python
    async def _headers(self) -> dict:
        token = await auth.get_access_token(self._account)
```

Em `request`, a linha do rate limit:

```python
            await ratelimit.acquire(self._account)
```

> `auth.get_access_token` ainda não aceita o parâmetro — isso é a Task 3. Até lá
> o teste de `ratelimit` passa e o de `client`/`auth` pode falhar. Rodar a suíte
> inteira só ao fim da Task 3.

- [ ] **Step 5: Rodar o teste de rate limit**

Run: `cd backend && python -m pytest tests/test_bling_ratelimit.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/ratelimit.py backend/app/bling/client.py backend/tests/test_bling_ratelimit.py
git commit -m "feat(bling): orcamento de rate limit por conta e account no BlingClient"
```

---

## Task 3: Tokens e cache por conta em `auth.py`

**Files:**
- Modify: `backend/app/bling/auth.py`
- Test: `backend/tests/test_bling_auth.py`

Esta é a task que fecha o bug mais grave do levantamento: hoje a conta 2
receberia o `access_token` da conta 1, porque o cache Redis é uma chave global.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar a `backend/tests/test_bling_auth.py`:

```python
def test_chave_de_cache_inclui_a_conta():
    assert auth._cache_key("default") == "bling:default:access_token"
    assert auth._cache_key("secundaria") == "bling:secundaria:access_token"


def test_chave_de_lock_inclui_a_conta():
    assert auth._lock_key("default") == "lock:bling_token_refresh:default"
    assert auth._lock_key("secundaria") == "lock:bling_token_refresh:secundaria"


def test_contas_distintas_nunca_compartilham_cache():
    """Regressao do bug: com chave global, autorizar a conta 2 entregaria o
    access_token da conta 1 para as chamadas da conta 2."""
    assert auth._cache_key("default") != auth._cache_key("secundaria")
    assert auth._lock_key("default") != auth._lock_key("secundaria")


async def test_persist_grava_no_id_da_conta(monkeypatch, creds):
    store = {}
    monkeypatch.setattr(auth, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(auth, "_cache_set", _noop_async)
    await auth._persist({"access_token": "tok", "refresh_token": "ref",
                         "expires_in": 21600}, "secundaria")
    assert store["upserted"]["id"] == "secundaria"


async def test_persist_default_continua_gravando_em_default(monkeypatch, creds):
    store = {}
    monkeypatch.setattr(auth, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(auth, "_cache_set", _noop_async)
    await auth._persist({"access_token": "tok", "refresh_token": "ref",
                         "expires_in": 21600}, "default")
    assert store["upserted"]["id"] == "default"


def test_basic_header_usa_credencial_da_conta(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    monkeypatch.setenv("BLING_SECUNDARIA_CLIENT_ID", "cid2")
    monkeypatch.setenv("BLING_SECUNDARIA_CLIENT_SECRET", "csec2")
    esperado = "Basic " + base64.b64encode(b"cid2:csec2").decode()
    assert auth._basic_auth_header("secundaria") == esperado
```

E, no topo do arquivo de teste, o helper usado acima:

```python
async def _noop_async(*_a, **_k):
    return None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_auth.py -q`
Expected: FAIL — `AttributeError: module 'app.bling.auth' has no attribute '_cache_key'`

- [ ] **Step 3: Implementar**

Em `backend/app/bling/auth.py`, trocar as constantes globais por funções:

```python
# As chaves sao POR CONTA. Uma chave global entregaria o access_token da conta 1
# para as chamadas da conta 2 — silenciosamente, porque o token e valido, so que
# do CNPJ errado.
def _cache_key(account: str) -> str:
    return f"bling:{account}:access_token"


def _lock_key(account: str) -> str:
    return f"lock:bling_token_refresh:{account}"
```

Remover `_CACHE_KEY` e `_LOCK_KEY`. Manter `_STATE_PREFIX` (a Task 4 mexe nele).

Adicionar `account` a estas funções, propagando para as chamadas internas:

```python
def _basic_auth_header(account: str) -> str:
    conta = config.account(account)
    # `conta.configured` e a fonte unica da regra "o que conta como configurado"
    # (Task 1). Repetir `client_id and client_secret` aqui criaria uma segunda
    # versao da mesma regra, que diverge no dia em que a integracao passar a
    # exigir tambem o redirect_uri.
    if not conta.configured:
        from app.bling.errors import BlingNotConfigured
        raise BlingNotConfigured(
            f"conta {account!r}: BLING_CLIENT_ID e BLING_CLIENT_SECRET "
            "precisam estar configurados"
        )
    return "Basic " + base64.b64encode(
        f"{conta.client_id}:{conta.client_secret}".encode()).decode()


async def _token_request(data: dict, account: str) -> dict:
    headers = {
        "Authorization": _basic_auth_header(account),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "1.0",
        "enable-jwt": "1",
    }
    # ... resto igual


async def exchange_code(code: str, account: str = config.DEFAULT_ACCOUNT) -> dict:
    payload = await _token_request(
        {"grant_type": "authorization_code", "code": code}, account)
    await _persist(payload, account)
    return payload


async def _refresh_now(refresh_token: str, account: str) -> str:
    payload = await _token_request(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}, account)
    await _persist(payload, account)
    return payload["access_token"]


async def _persist(payload: dict, account: str) -> None:
    # ... igual, trocando so a linha do id:
    row = {
        "id": account,
        # ... resto igual
    }
    # e, no fim:
    await _cache_set(row["access_token"],
                     max(60, expires_in - _RENEW_MARGIN_SECONDS), account)


def _stored_row(account: str) -> dict | None:
    res = (get_supabase().table("bling_credentials")
           .select("*").eq("id", account).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


async def _cache_get(account: str) -> str | None:
    try:
        return await _get_redis().get(_cache_key(account))
    except Exception:  # noqa: BLE001 — cache indisponivel cai para o Postgres
        return None


async def _cache_set(token: str | None, ttl: int, account: str) -> None:
    if not token:
        return
    try:
        await _get_redis().setex(_cache_key(account), ttl, token)
    except Exception:  # noqa: BLE001
        logger.warning("[BLING AUTH] nao foi possivel cachear o access_token "
                       "da conta %s", account)


async def _refresh_lock(account: str):
    client = _get_redis()
    token = secrets.token_hex(8)
    chave = _lock_key(account)
    # ... resto igual, trocando _LOCK_KEY por `chave` nas tres ocorrencias
    # (o set nx, o eval de liberacao e o KEYS[1])


async def get_access_token(account: str = config.DEFAULT_ACCOUNT) -> str:
    cached = await _cache_get(account)
    if cached:
        return cached

    ctx = await _refresh_lock(account)
    async with ctx as owned:
        cached = await _cache_get(account)
        if cached:
            return cached
        if not owned:
            raise BlingServerError(
                f"conta {account}: nao foi possivel obter o lock de refresh (timeout)")

        row = await asyncio.to_thread(_stored_row, account) or {}
        access_token = row.get("access_token")
        restante = _seconds_until(row.get("access_expires_at"))
        if access_token and restante > _RENEW_MARGIN_SECONDS:
            await _cache_set(access_token,
                             max(60, int(restante) - _RENEW_MARGIN_SECONDS), account)
            return access_token

        refresh_token = row.get("refresh_token")
        if not refresh_token:
            raise BlingNotConfigured(
                f"conta {account}: nenhum refresh_token salvo — "
                "refaca o fluxo OAuth em /config"
            )
        return await _refresh_now(refresh_token, account)


async def invalidate_cache(account: str = config.DEFAULT_ACCOUNT) -> None:
    try:
        await _get_redis().delete(_cache_key(account))
    except Exception:  # noqa: BLE001
        pass
```

- [ ] **Step 4: Atualizar o retry de 401 no client**

Em `backend/app/bling/client.py`, onde há `auth.invalidate_cache()`:

```python
                await auth.invalidate_cache(self._account)
```

- [ ] **Step 5: Restaurar o verde em `test_bling_client.py`**

A Task 2 deixou **12 testes vermelhos de propósito**, todos em
`backend/tests/test_bling_client.py`. Esta task é a responsável por devolvê-los
ao verde. São dois dublês com assinatura de zero argumentos que a produção passou
a chamar com um:

- a fixture `token`, cujo `fake_token()` substitui `auth.get_access_token` — 11
  testes;
- `fake_acquire()` dentro de `test_rate_limiter_e_chamado_antes_de_cada_request`,
  que substitui `ratelimit.acquire` — 1 teste.

Os dois passam a aceitar o argumento da conta. **Ajustar o dublê, nunca afrouxar
a asserção** — o que cada teste verifica continua igual.

Aproveite para acrescentar uma asserção que hoje não existe: que o `BlingClient`
repassa a conta que recebeu no construtor para `get_access_token` e para
`ratelimit.acquire`. É o contrato que a Task 2 introduziu e nada o cobre ainda.

- [ ] **Step 6: Rodar a suíte de Bling inteira**

Run: `cd backend && python -m pytest tests/ -k bling -q`
Expected: **PASS, zero falhas** — o baseline antes da Task 2 era 261 passed,
1 skipped. Se sobrar qualquer vermelho, a task não está pronta.

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/auth.py backend/app/bling/client.py backend/tests/test_bling_auth.py
git commit -m "fix(bling): tokens e cache Redis por conta — fecha o token cruzado entre contas"
```

---

## Task 4: O `state` do OAuth carrega a conta, e `status()` vira lista

**Files:**
- Modify: `backend/app/bling/auth.py`
- Test: `backend/tests/test_bling_auth.py`

Sem isso, `/oauth/callback` não tem como saber qual conta está sendo conectada —
e autorizar a conta 2 sobrescreveria o token da conta 1.

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_state_guarda_a_conta_e_consume_devolve(monkeypatch):
    guardado = {}

    class FakeRedis:
        async def setex(self, chave, ttl, valor):
            guardado[chave] = valor
        async def get(self, chave):
            return guardado.get(chave)
        async def delete(self, chave):
            return 1 if guardado.pop(chave, None) is not None else 0

    monkeypatch.setattr(auth, "_get_redis", lambda: FakeRedis())
    state = await auth.new_state("secundaria")
    assert await auth.consume_state(state) == "secundaria"


async def test_state_queimado_devolve_none(monkeypatch):
    guardado = {}

    class FakeRedis:
        async def setex(self, chave, ttl, valor):
            guardado[chave] = valor
        async def get(self, chave):
            return guardado.get(chave)
        async def delete(self, chave):
            return 1 if guardado.pop(chave, None) is not None else 0

    monkeypatch.setattr(auth, "_get_redis", lambda: FakeRedis())
    state = await auth.new_state("default")
    assert await auth.consume_state(state) == "default"
    assert await auth.consume_state(state) is None


async def test_state_vazio_devolve_none(monkeypatch):
    assert await auth.consume_state("") is None


def test_authorize_url_usa_client_id_da_conta(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    monkeypatch.setenv("BLING_SECUNDARIA_CLIENT_ID", "cid2")
    monkeypatch.setenv("BLING_SECUNDARIA_CLIENT_SECRET", "csec2")
    url = auth.authorize_url("abc123", "secundaria")
    assert "client_id=cid2" in url
    assert "state=abc123" in url
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_auth.py -q`
Expected: FAIL — `TypeError: new_state() takes 0 positional arguments but 1 was given`

- [ ] **Step 3: Implementar**

```python
async def new_state(account: str = config.DEFAULT_ACCOUNT) -> str:
    """Gera o state (anti-CSRF) guardando a CONTA como valor.

    O valor precisa ser a conta, nao um "1": o /oauth/callback so recebe `code`
    e `state`, entao o state e o unico canal que diz qual conta esta sendo
    conectada. Sem isso, autorizar a conta 2 sobrescreveria o token da conta 1.
    """
    state = secrets.token_urlsafe(24)
    await _get_redis().setex(_STATE_PREFIX + state, _STATE_TTL, account)
    return state


async def consume_state(state: str) -> str | None:
    """Valida e queima o state. Devolve a conta, ou None se invalido/ja usado."""
    if not state:
        return None
    chave = _STATE_PREFIX + state
    redis = _get_redis()
    conta = await redis.get(chave)
    if conta is None:
        return None
    if not await redis.delete(chave):
        # Outro request queimou entre o get e o delete — trata como invalido.
        return None
    return conta


def authorize_url(state: str, account: str = config.DEFAULT_ACCOUNT) -> str:
    conta = config.account(account)
    if not conta.configured:
        from app.bling.errors import BlingNotConfigured
        raise BlingNotConfigured(
            f"conta {account!r}: credenciais nao configuradas")
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": conta.client_id,
        "state": state,
    })
    return f"{config.AUTHORIZE_URL}?{params}"
```

E `status()` passa a devolver uma lista, uma entrada por conta.

> ⚠️ **O endpoint `/api/bling/status` NÃO pode trocar de formato.** `auth.status()`
> é interno e vira lista; o endpoint continua devolvendo `enabled` e `connected`
> no topo, com a lista **ao lado**, em `accounts`.
>
> O motivo é um modo de falha silencioso: `use-bling-status.ts` lê
> `body.enabled` e `body.connected` e colapsa os dois num booleano. Com a
> resposta virando lista pura, `body.enabled` seria `undefined`, o hook devolveria
> `enabled: false`, e `blingGate` cairia em `mode: "legacy", canSubmit: true` —
> ou seja, **as vendas parariam de ir para o Bling sem nenhum erro na tela**. É
> precisamente o defeito que o comentário do `bling-gate.ts` diz que aquele
> arquivo existe para impedir.
>
> Com o formato aditivo, o frontend das Tasks 14-16 migra para `accounts` quando
> estiver pronto, sem janela de comportamento errado no meio.

**O ajuste do endpoint é da Task 4, não da Task 11.** `router.py:481` faz hoje
`return {**estado, "enabled": config.enabled()}` — desempacotamento de
dicionário. No instante em que `auth.status()` devolve lista, isso vira
`TypeError: 'list' object is not a mapping` e o endpoint ao vivo morre. Nenhum
teste pega (só a existência da rota é verificada). Quem quebra conserta na mesma
task; adiar por sete tasks é como uma branch apodrece.

Forma do endpoint:

```python
    contas = await auth.status()
    padrao = next((c for c in contas if c["account"] == config.DEFAULT_ACCOUNT), {})
    return {
        # Compatibilidade: o frontend atual le estes dois no topo. Sair daqui
        # sem aviso faria o modal de venda cair em modo legado em silencio.
        "enabled": config.enabled(),
        "connected": bool(padrao.get("connected")),
        "accounts": contas,
    }
```

> **`status()` precisa de teste direto NESTA task.** Ela acabou de ter um bug
> real (chamava `_stored_row()` sem argumento, achado na T3 só porque a
> assinatura ficou estrita) e é endpoint ao vivo em `/config`. A T11 só a testa
> indiretamente pelo router, duas tasks adiante — tempo demais para uma função
> recém-mexida ficar descoberta. Use o `FakeSupabase` que já existe no arquivo:

```python
async def test_status_devolve_uma_entrada_por_conta_configurada(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    monkeypatch.setattr(auth, "_stored_row",
                        lambda conta: {"refresh_token": "r"} if conta == "default" else {})

    saida = await auth.status()
    assert [c["account"] for c in saida] == ["default", "secundaria"]
    assert saida[0]["connected"] is True
    assert saida[1]["connected"] is False   # sem refresh_token
```

A função interna:

```python
async def status() -> list[dict]:
    """Resumo para /api/bling/status: uma entrada por conta configurada."""
    saida = []
    for conta in config.accounts():
        row = await asyncio.to_thread(_stored_row, conta.key) or {}
        saida.append({
            "account": conta.key,
            "label": conta.label,
            "configured": conta.configured,
            "connected": bool(row.get("refresh_token")),
            "access_expires_at": row.get("access_expires_at"),
            "refresh_expires_at": row.get("refresh_expires_at"),
            "scope": row.get("scope"),
        })
    return saida
```

- [ ] **Step 4: Rodar**

Run: `cd backend && python -m pytest tests/test_bling_auth.py -q`
Expected: PASS. O teste antigo `test_authorize_url_tem_response_type_client_id_e_state`
continua válido — `authorize_url("abc123")` usa o default.

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/auth.py backend/tests/test_bling_auth.py
git commit -m "feat(bling): state do OAuth carrega a conta e status devolve uma entrada por conta"
```

---

## Task 5: A migration

**Files:**
- Create: `supabase/migrations/20260913_bling_multi_conta.sql`

Sem teste automatizado — o repo aplica migrations à mão. A verificação está no
Step 3.

> **Schema conferido contra PRODUÇÃO em 14/09/2026** (somente `SELECT` no
> catálogo do Postgres), não contra os arquivos de migration — eles são
> aplicados à mão neste repo e podem divergir. O que a consulta confirmou:
>
> | Verificação | Resultado |
> |---|---|
> | FKs apontando para tabelas `bling_*` | **exatamente uma**: `bling_seller_map_bling_seller_id_fkey` → `bling_sellers(id)` |
> | Nomes das PKs | batem com o padrão `<tabela>_pkey` usado abaixo |
> | `sales_bling_order_id_key` | é **ÍNDICE** (só em `pg_indexes`) → `DROP INDEX` |
> | `quotes_bling_proposal_id_key` | é **CONSTRAINT** (em `pg_constraint`) → `ALTER TABLE ... DROP CONSTRAINT` |
> | Coluna `account` / `bling_account` | **não existe** em nenhuma tabela ainda |
> | `leads_bling_contact_id_key` | índice **parcial** (`WHERE bling_contact_id IS NOT NULL`) — intocado, a coluna fica |
>
> ⚠️ A assimetria índice-vs-constraint é uma armadilha: os dois têm sufixo
> `_key` e parecem a mesma coisa. `DROP INDEX` numa constraint falha, e
> `DROP CONSTRAINT` num índice também. Não "harmonize" os dois comandos.

- [ ] **Step 1: Escrever a migration**

Criar `supabase/migrations/20260913_bling_multi_conta.sql`:

```sql
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
-- Derrubar antes, recriar composta depois.
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
-- EXISTS, entao sem ele a segunda execucao do arquivo morre em 42710. Todo o
-- resto desta migration ja segue o padrao drop-then-add (inclusive os PKs, que
-- o Postgres nomeia <tabela>_pkey sozinho e por isso o DROP acima alcanca).
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
DROP INDEX IF EXISTS sales_bling_order_id_key;
DROP INDEX IF EXISTS sales_bling_order_key;
CREATE UNIQUE INDEX sales_bling_order_key ON sales (bling_account, bling_order_id);

ALTER TABLE quotes DROP CONSTRAINT IF EXISTS quotes_bling_proposal_id_key;
DROP INDEX IF EXISTS quotes_bling_proposal_key;
CREATE UNIQUE INDEX quotes_bling_proposal_key ON quotes (bling_account, bling_proposal_id);

-- PostgREST nao enxerga coluna nova sem recarregar o cache de schema.
NOTIFY pgrst, 'reload schema';
```

- [ ] **Step 2: Commit**

```bash
git add supabase/migrations/20260913_bling_multi_conta.sql
git commit -m "feat(bling): migration multi-conta — PK composta nos espelhos e lead_bling_contacts"
```

- [ ] **Step 3: Verificação manual (NÃO automatizável)**

Depois de aplicar no SQL editor do Supabase, conferir:

```sql
select count(*) from lead_bling_contacts;                        -- esperado 1479
select count(*) from sales where bling_account = 'default';      -- esperado 1024
select indexdef from pg_indexes where indexname = 'sales_bling_order_key';
-- deve conter (bling_account, bling_order_id) e NAO conter WHERE
```

---

## Task 6: Sync e espelhos por conta

**Files:**
- Modify: `backend/app/bling/sync.py`
- Modify: `backend/app/bling/products.py`
- Test: `backend/tests/test_bling_sync.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_sync_roda_para_cada_conta_configurada(monkeypatch):
    from app.bling import sync

    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")

    chamadas = []

    async def fake_sync_account(account, *, full=False):
        chamadas.append(account)
        return {"produtos": 0}

    monkeypatch.setattr(sync, "sync_account", fake_sync_account)
    resultado = await sync.sync_all()
    assert chamadas == ["default", "secundaria"]
    assert set(resultado) == {"default", "secundaria"}


async def test_falha_numa_conta_nao_impede_a_outra(monkeypatch):
    from app.bling import sync

    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")

    chamadas = []

    async def fake_sync_account(account, *, full=False):
        chamadas.append(account)
        if account == "default":
            raise RuntimeError("conta 1 fora do ar")
        return {"produtos": 3}

    monkeypatch.setattr(sync, "sync_account", fake_sync_account)
    resultado = await sync.sync_all()   # nao pode propagar a excecao
    assert chamadas == ["default", "secundaria"]
    assert "erro" in resultado["default"]
    assert resultado["secundaria"] == {"produtos": 3}


def test_sync_state_e_lido_por_conta():
    from app.bling import sync
    assert sync._state_filter("produtos", "secundaria") == {
        "resource": "produtos", "account": "secundaria"}
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_sync.py -q`
Expected: FAIL — `AttributeError: module 'app.bling.sync' has no attribute 'sync_all'`

- [ ] **Step 3: Implementar**

**Estado atual conferido no código** (não presumir): `sync.py:232` já tem
`async def sync_all(*, full: bool = False) -> dict`, que devolve um dicionário de
contagens e é chamada por `bling_sync_tick()` (`sync.py:247`), que **loga esse
retorno**. Devolver `None` na versão nova faria o log de produção virar "None".

Passo 1 — **renomear** a `sync_all` existente para `sync_account`, acrescentando a
conta como primeiro parâmetro e preservando o retorno em dicionário:

```python
async def sync_account(account: str, *, full: bool = False) -> dict:
    """Roda os cinco syncs de UMA conta, em sequencia (nunca em paralelo:
    o teto de 3 req/s e da conta)."""
    from app.bling.client import BlingClient

    async with BlingClient(account=account) as client:
        produtos = await sync_products(client, account, full=full)
        contatos = await sync_contacts(client, account)
        formas = await sync_payment_methods(client, account)
        vendedores = await sync_sellers(client, account)
        situacoes = await sync_situacoes(client, account)
    return {"produtos": produtos, "contatos": contatos,
            "formas_pagamento": formas, "vendedores": vendedores,
            "situacoes": situacoes}
```

Passo 2 — as cinco funções `sync_*(client, account, ...)` passam a receber a conta
e a gravá-la. Concretamente:

- `_upsert(table, rows)` (`sync.py:124`) usa hoje `on_conflict="id"`; passa a ser
  `_upsert(table, rows, account)`, injetando `"account": account` em cada linha e
  usando `on_conflict="account,id"`.
- `_load_sync_state(resource)` (`sync.py:111`) e `_save_sync_state(resource, ...)`
  (`sync.py:117`, hoje `on_conflict="resource"`) passam a receber `account`,
  filtrar por ele e usar `on_conflict="account,resource"`.

Passo 3 — a `sync_all` **nova** vira o laço com isolamento de falha:

```python
def _state_filter(resource: str, account: str) -> dict:
    return {"resource": resource, "account": account}


async def sync_all(*, full: bool = False) -> dict:
    """Sincroniza TODAS as contas configuradas.

    Falha numa conta nao pode derrubar a outra: o worker roda as duas no mesmo
    tick e um 401 na conta 2 nao tem por que parar o catalogo da conta 1. Por
    isso o resultado e por conta e o erro entra como valor, nao como excecao —
    `bling_sync_tick` loga esse dicionario e precisa ver as duas.
    """
    resultado = {}
    for conta in config.accounts():
        try:
            resultado[conta.key] = await sync_account(conta.key, full=full)
        except Exception as exc:  # noqa: BLE001 — isolamento por conta
            logger.warning("[BLING SYNC] conta %s falhou: %s", conta.key, exc)
            resultado[conta.key] = {"erro": str(exc)}
    return resultado
```

`bling_sync_tick()` **não muda**: continua chamando `sync_all()` e logando o
retorno, que agora vem agrupado por conta.

Passo 4 — **`products.py` tem cópias PRÓPRIAS das mesmas funções** e é fácil
passar batido: ele não reusa as de `sync.py`. Todas as quatro precisam da conta:

| Linha | Hoje | Passa a ser |
|---|---|---|
| `products.py:44` | `_load_sync_state(resource)` | recebe `account`, filtra por ele |
| `products.py:50` | `_save_sync_state(...)` com `on_conflict="resource"` | `on_conflict="account,resource"` |
| `products.py:58` | `_upsert(rows)` com `on_conflict="id"` | `_upsert(rows, account)`, injeta `account` na linha, `on_conflict="account,id"` |
| `products.py:67` | `sync_products(client, *, full, batch_size)` | `sync_products(client, account, *, full, batch_size)` |
| `products.py:103` | `apply_product_event(event, payload)` | `apply_product_event(event, payload, account)` |

- [ ] **Step 4: Rodar**

Run: `cd backend && python -m pytest tests/test_bling_sync.py tests/test_bling_products.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/sync.py backend/app/bling/products.py backend/tests/test_bling_sync.py
git commit -m "feat(bling): sync por conta com isolamento de falha entre contas"
```

---

## Task 7: `lead_bling_contacts` em `contacts.py`

**Files:**
- Modify: `backend/app/bling/contacts.py`
- Test: `backend/tests/test_bling_contacts.py`

- [ ] **Step 1: Escrever os testes que falham**

> **Esta é a task mais delicada do plano.** `contacts.py` tem 498 linhas de lógica
> de dedupe (validação de DV de CPF/CNPJ, variantes de telefone, tratamento de
> violação de unicidade) e `leads.bling_contact_id` aparece em **13 pontos** dela.
> A lógica de casamento **não muda** — o que muda é onde o vínculo mora e o fato
> de ele passar a ser por conta. Preserve cada regra existente.

**Os nomes das funções são os que já existem** (`link`, `unlink`, `_link`,
`_unlink`, `resolve`, `ensure_lead`, `_find_lead`, `_pode_vincular_por_telefone`,
`_upsert_mirror`) — acrescente o parâmetro `account`, não crie nomes novos.

**⚠️ A armadilha central desta task.** Duas funções decidem coisas a partir de
"o lead já tem contato?", e as duas precisam virar **"o lead já tem contato
NESTA conta?"**:

- `resolve()` (`contacts.py:226-229`) devolve `linked` de saída quando o lead já
  tem vínculo.
- `_pode_vincular_por_telefone()` (`contacts.py:407`, regra 1) **recusa** gravar
  vínculo por telefone quando o lead já tem um.

Se qualquer uma continuar olhando "tem vínculo em qualquer conta", o cliente que
existe nos DOIS CNPJs — o caso de negócio que motivou esta entrega — nunca
conseguiria ser vinculado na segunda conta. Seria uma falha silenciosa: sem erro,
só um lead que nunca resolve o contato da conta 2.

```python
async def test_vincula_lead_por_conta(monkeypatch):
    from app.bling import contacts
    gravado = {}

    def fake_link(lead_id, contact_id, account):
        gravado.update({"lead_id": lead_id, "account": account,
                        "contact_id": contact_id})

    monkeypatch.setattr(contacts, "_link", fake_link)
    await contacts.link("lead-1", 999, "secundaria")
    assert gravado == {"lead_id": "lead-1", "account": "secundaria",
                       "contact_id": 999}


async def test_mesmo_lead_pode_ter_contato_nas_duas_contas(monkeypatch):
    """O caso 'alguns clientes em comum': o mesmo cliente existe nos dois CNPJs
    com IDs diferentes, e o lead precisa apontar para os dois ao mesmo tempo."""
    from app.bling import contacts
    gravadas = []

    def fake_link(lead_id, contact_id, account):
        gravadas.append((lead_id, account, contact_id))

    monkeypatch.setattr(contacts, "_link", fake_link)
    await contacts.link("lead-1", 111, "default")
    await contacts.link("lead-1", 222, "secundaria")
    assert gravadas == [("lead-1", "default", 111),
                        ("lead-1", "secundaria", 222)]


async def test_resolve_ignora_vinculo_de_outra_conta(monkeypatch):
    """REGRESSAO DA ARMADILHA: um lead vinculado na conta 1 deve continuar
    resolvivel na conta 2, senao o cliente em comum nunca e vinculado la."""
    from app.bling import contacts

    # O lead tem contato na conta 1, nenhum na conta 2.
    monkeypatch.setattr(contacts, "_contato_do_lead",
                        lambda lead_id, account: 111 if account == "default" else None)
    monkeypatch.setattr(contacts, "_query_by_doc",
                        lambda doc, account: [{"id": 222}])
    gravado = {}
    monkeypatch.setattr(contacts, "_link",
                        lambda lead_id, contact_id, account: gravado.update(
                            {"contact_id": contact_id, "account": account}))

    lead = {"id": "lead-1", "cnpj": "11222333000181"}
    r = await contacts.resolve(lead, "secundaria")
    assert r.status == "linked"
    assert gravado == {"contact_id": 222, "account": "secundaria"}


def test_pode_vincular_por_telefone_olha_so_a_conta_corrente():
    """Mesma armadilha do outro lado: ter contato na conta 1 nao pode BLOQUEAR
    o vinculo por telefone na conta 2."""
    from app.bling import contacts
    # Sem contato na conta corrente e sem documento divergente => pode.
    assert contacts._pode_vincular_por_telefone(
        {"cnpj": None}, None, contato_da_conta=None) is True
    # Ja tem contato NA CONTA CORRENTE => nao pode (regra original preservada).
    assert contacts._pode_vincular_por_telefone(
        {"cnpj": None}, None, contato_da_conta=111) is False


def test_espelho_de_contato_usa_chave_composta(monkeypatch):
    from app.bling import contacts
    capturado = {}

    class FakeTable:
        def upsert(self, row, on_conflict=None):
            capturado["row"] = row
            capturado["on_conflict"] = on_conflict
            return self
        def execute(self):
            class R: data = [{}]
            return R()

    class FakeSupa:
        def table(self, _n): return FakeTable()

    monkeypatch.setattr(contacts, "get_supabase", lambda: FakeSupa())
    contacts._upsert_mirror({"id": 5, "nome": "X"}, "secundaria")
    assert capturado["on_conflict"] == "account,id"
    assert capturado["row"]["account"] == "secundaria"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_contacts.py -q`
Expected: FAIL — `AttributeError: module 'app.bling.contacts' has no attribute 'link_lead'`

- [ ] **Step 3: Implementar**

Núcleo do armazenamento — `leads.bling_contact_id` sai, `lead_bling_contacts` entra:

```python
def _contato_do_lead(lead_id: str, account: str) -> int | None:
    """Contato do lead NESTA conta, ou None.

    Substitui a leitura direta de `leads.bling_contact_id`. O recorte por conta e
    o ponto inteiro: um lead pode ter contato na conta 1 e nenhum na conta 2, e os
    dois estados sao independentes.
    """
    res = (get_supabase().table("lead_bling_contacts").select("bling_contact_id")
           .eq("lead_id", lead_id).eq("account", account)
           .limit(1).maybe_single().execute())
    linha = getattr(res, "data", None) or {}
    return linha.get("bling_contact_id")


def _link(lead_id: str, contact_id: int, account: str) -> None:
    (get_supabase().table("lead_bling_contacts").upsert({
        "lead_id": lead_id,
        "account": account,
        "bling_contact_id": contact_id,
    }, on_conflict="lead_id,account").execute())


def _unlink(lead_id: str, account: str) -> None:
    (get_supabase().table("lead_bling_contacts").delete()
     .eq("lead_id", lead_id).eq("account", account).execute())


def _lead_por_contato(contact_id: int, account: str) -> dict | None:
    """Lead dono deste contato, nesta conta. Substitui
    `_find_lead("bling_contact_id", contact_id)`, que nao existe mais como coluna."""
    res = (get_supabase().table("lead_bling_contacts").select("lead_id")
           .eq("bling_contact_id", contact_id).eq("account", account)
           .limit(1).maybe_single().execute())
    linha = getattr(res, "data", None) or {}
    if not linha.get("lead_id"):
        return None
    return _find_lead("id", linha["lead_id"])
```

Inventário dos pontos a mudar em `contacts.py` (todos verificados por `grep`):

| Linha | O que é hoje | Passa a ser |
|---|---|---|
| 10 | docstring cita `leads.bling_contact_id` sob UNIQUE | citar `lead_bling_contacts (account, bling_contact_id)` |
| 177,184,198 | `_query_by_doc` / `_query_by_phones` / `_query_by_email` no espelho | recebem `account` e filtram `.eq("account", account)` |
| 205 | `_link` faz `UPDATE leads` | escreve em `lead_bling_contacts` (acima) |
| 211 | docstring do 23505 cita o índice de `leads` | citar o índice novo; **a detecção de 23505 continua igual** |
| 226-229 | `resolve(lead)` lê `lead["bling_contact_id"]` | `resolve(lead, account)` usa `_contato_do_lead(lead["id"], account)` |
| 276 | `link(lead_id, contact_id)` | `link(lead_id, contact_id, account)` |
| 281-286 | `_unlink` / `unlink` | recebem `account` |
| 297 | `_upsert_mirror` com `on_conflict="id"` | `_upsert_mirror(row, account)` com `on_conflict="account,id"` |
| 302 | `create_contact(client, lead, dados)` | recebe `account`, repassa ao espelho e ao vínculo |
| 401 | `_find_lead` seleciona `bling_contact_id` | remove da projeção; quem precisava agora chama `_contato_do_lead` |
| 407-431 | `_pode_vincular_por_telefone(lead_row, doc_contato)` | ganha `contato_da_conta: int \| None` e testa **ele**, não `lead_row` |
| 439-443 | `ensure_lead(contato)` + `_find_lead("bling_contact_id", …)` | `ensure_lead(contato, account)` + `_lead_por_contato(contact_id, account)` |
| 493 | payload de lead novo grava `bling_contact_id` | grava o lead sem a coluna e chama `_link(...)` depois |

**Regras que NÃO podem mudar** (são de nota fiscal, documentadas no próprio
arquivo — releia os comentários antes de mexer):

- Documento só vira chave depois de validar o DV. Documento inválido não para o
  fluxo: cai para telefone/e-mail, que apenas **sugerem**.
- Telefone e e-mail nunca gravam sozinhos (`suggested`, jamais `linked`).
- Dois contatos com o mesmo documento → `ambiguous`, nunca escolha automática.
- Violação de unicidade vira `ambiguous` com log, nunca 500.
- Documentos que divergem dos dois lados continuam recusando o vínculo por
  telefone, mesmo com o telefone batendo.

- [ ] **Step 4: Rodar**

Run: `cd backend && python -m pytest tests/test_bling_contacts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/contacts.py backend/tests/test_bling_contacts.py
git commit -m "feat(bling): vinculo lead-contato por conta em lead_bling_contacts"
```

---

## Task 8: Pedidos — `on_conflict` composto

**Files:**
- Modify: `backend/app/bling/orders.py`
- Test: `backend/tests/test_bling_orders.py`

Esta é a task com a armadilha mais cara do plano. Ler o aviso do Step 5.

- [ ] **Step 1: Escrever os testes que falham**

> **Assinatura real conferida no código:** `_upsert_sale(row: dict) -> str | None`
> em `orders.py:520` é **síncrona** (chamada via `asyncio.to_thread` na linha 578)
> e usa hoje `on_conflict="bling_order_id"`. Os testes abaixo NÃO usam `await`.

```python
def test_upsert_de_venda_usa_on_conflict_composto(monkeypatch):
    from app.bling import orders
    capturado = {}

    class FakeTable:
        def upsert(self, row, on_conflict=None):
            capturado["row"] = row
            capturado["on_conflict"] = on_conflict
            return self
        def execute(self):
            class R: data = [{"id": "venda-1"}]
            return R()

    class FakeSupa:
        def table(self, _n):
            return FakeTable()

    monkeypatch.setattr(orders, "get_supabase", lambda: FakeSupa())
    orders._upsert_sale({"bling_order_id": 10, "bling_account": "secundaria"})

    assert capturado["on_conflict"] == "bling_account,bling_order_id"
    assert capturado["row"]["bling_account"] == "secundaria"


def test_mesmo_order_id_em_contas_diferentes_nao_colide(monkeypatch):
    """IDs do Bling sao sequencia POR CONTA: o pedido 10 existe nas duas."""
    from app.bling import orders
    linhas = []

    class FakeTable:
        def upsert(self, row, on_conflict=None):
            linhas.append((row["bling_account"], row["bling_order_id"]))
            return self
        def execute(self):
            class R: data = [{"id": "x"}]
            return R()

    class FakeSupa:
        def table(self, _n):
            return FakeTable()

    monkeypatch.setattr(orders, "get_supabase", lambda: FakeSupa())
    orders._upsert_sale({"bling_order_id": 10, "bling_account": "default"})
    orders._upsert_sale({"bling_order_id": 10, "bling_account": "secundaria"})
    assert linhas == [("default", 10), ("secundaria", 10)]
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_orders.py -q`
Expected: FAIL — `TypeError: _upsert_sale() got an unexpected keyword argument 'account'`

- [ ] **Step 3: Implementar**

Em `backend/app/bling/orders.py`:

- `_upsert_sale(row)` (`orders.py:520`) usa
  `on_conflict="bling_account,bling_order_id"`. A linha já chega com
  `bling_account` preenchido pelo chamador — a função continua recebendo só
  `row`, sem parâmetro novo.
- `create_order`, `update_order`, `upsert_from_bling` e `cancel_from_bling`
  recebem `account` e o gravam em `bling_account` nas linhas que montam.
- `cancel_from_bling` e **qualquer** `.eq("bling_order_id", ...)` ganham também
  `.eq("bling_account", account)` — sem isso, cancelar o pedido 10 da conta 2
  cancelaria o pedido 10 da conta 1, porque o número se repete entre as contas.
- `build_order_payload` (`orders.py:141`) lê hoje `config.store_id()` e
  `config.order_situacao_id()` direto do env global (linhas 201 e 204). Passa a
  **receber `store_id` e `situacao_id` como parâmetros**, resolvidos pelo
  chamador via `config.account(account)`. Manter a função pura (sem ler env) é o
  que a torna testável sem monkeypatch de ambiente, como já é hoje o resto do
  módulo.

> **O mapeamento de vendedor NÃO fica aqui.** `bling_seller_map` é lido em
> `backend/app/bling/router.py:247`, não em `orders.py` — a mudança dele está na
> Task 11, junto dos demais endpoints. Não criar um `_seller_id` em `orders.py`.

- [ ] **Step 4: Varredura por `on_conflict` esquecido**

Run: `grep -rn 'on_conflict' backend/app/bling backend/app/quotes`
Expected: nenhuma ocorrência de `on_conflict="id"` ou `on_conflict="bling_order_id"`
sobrando. Toda chave que envolve entidade do Bling precisa da conta.

- [ ] **Step 5: Rodar**

Run: `cd backend && python -m pytest tests/test_bling_orders.py -q`
Expected: PASS

> ⚠️ **Teste verde NÃO é suficiente aqui.** A migration `20260818` documenta que
> os dubles do Supabase não pegam falha de inferência de ON CONFLICT — o `42P10`
> só aparece contra o Postgres real. Antes do push, criar um pedido de teste
> contra o banco real e confirmar que a venda aparece em `sales`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/orders.py backend/tests/test_bling_orders.py
git commit -m "fix(bling): upsert de venda com chave composta (bling_account, bling_order_id)"
```

---

## Task 9: Webhook — rota por conta, mantendo a legada

**Files:**
- Modify: `backend/app/bling/webhook_router.py`
- Test: `backend/tests/test_bling_webhook.py`

- [ ] **Step 1: Escrever os testes que falham**

> **Nomes reais do arquivo de teste** (conferidos, não presumir): a fixture do
> TestClient chama-se **`client`** (`test_bling_webhook.py:19`), a de captura
> chama-se **`gravados`** (linha 28), e o helper existente é `_assinar(corpo)`
> — **com um argumento só**, usando um secret fixo. Estenda-o para
> `_assinar(corpo, secret="csec")` mantendo o default, para os 6 testes que já
> existem continuarem passando sem alteração.
>
> `test_webhook_router_expoe_a_rota` (linha 133) afirma
> `"/webhook/bling" in {r.path for r in router.routes}` e
> `test_router_registrado_no_app` (linha 123) verifica o texto-fonte de
> `main.py`. **Nenhuma das duas precisa mudar** — a rota legada continua
> existindo e `main.py` não é tocado. Melhor ainda: a primeira vira, de graça, a
> guarda automática contra alguém remover a rota legada por engano. Se alguma
> das duas ficar vermelha, é sinal de que algo saiu errado — conserte o código,
> não o teste.

A fixture `client` (linha 19) hoje define só `BLING_CLIENT_SECRET` (da constante
`SECRET` do módulo) e `BLING_ENABLED=true`. Precisa passar a definir também
`BLING_ACCOUNTS=default,secundaria` e `BLING_SECUNDARIA_CLIENT_SECRET=csec2`,
mantendo `BLING_CLIENT_SECRET=SECRET` para os 6 testes existentes continuarem
válidos sem alteração.

```python
def test_rota_por_conta_grava_o_slug(client, gravados):
    corpo = b'{"eventId":"e1","event":"order.created","data":{"id":7}}'
    resp = client.post("/webhook/bling/secundaria", content=corpo,
                       headers={"x-bling-signature-256": _assinar(corpo, "csec2")})
    assert resp.status_code == 200
    assert gravados[0]["account"] == "secundaria"


def test_rota_legada_continua_valendo_como_default(client, gravados):
    """O painel da conta 1 ja aponta para /webhook/bling. Se ela sumir, o Bling
    retenta por 3 dias e DESABILITA a configuracao em silencio."""
    corpo = b'{"eventId":"e2","event":"order.created","data":{"id":8}}'
    resp = client.post("/webhook/bling", content=corpo,
                       headers={"x-bling-signature-256": _assinar(corpo, "csec")})
    assert resp.status_code == 200
    assert gravados[0]["account"] == "default"


def test_slug_desconhecido_responde_404(client, gravados):
    corpo = b'{"eventId":"e3","event":"order.created","data":{"id":9}}'
    resp = client.post("/webhook/bling/naoexiste", content=corpo,
                       headers={"x-bling-signature-256": _assinar(corpo, "csec")})
    assert resp.status_code == 404
    assert gravados == []


def test_assinatura_validada_com_o_secret_da_conta(client, gravados):
    """Assinar com o secret da conta 1 e entregar na rota da conta 2 = 401."""
    corpo = b'{"eventId":"e4","event":"order.created","data":{"id":10}}'
    resp = client.post("/webhook/bling/secundaria", content=corpo,
                       headers={"x-bling-signature-256": _assinar(corpo, "csec")})
    assert resp.status_code == 401
    assert gravados == []
```

> `gravados` **é uma lista** (conferido, `test_bling_webhook.py:28-38`) e já
> implementa o dedupe por `event_id` devolvendo `False` na repetição — por isso
> `gravados[0]["account"]` e `gravados == []` acima estão corretos. Não
> reescreva a fixture; ela já modela o `ON CONFLICT DO NOTHING` do receiver.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_webhook.py -q`
Expected: FAIL — 404 na rota `/webhook/bling/secundaria`

- [ ] **Step 3: Implementar**

Em `backend/app/bling/webhook_router.py`, extrair o corpo para uma função e
expor as duas rotas:

```python
from app.bling.errors import BlingUnknownAccount


async def _receber(request: Request, account: str) -> Response:
    try:
        conta = config.account(account)
    except BlingUnknownAccount:
        # 404 de proposito, NAO 200: slug errado e erro de configuracao no painel
        # do Bling e precisa ser barulhento. Absorver com 200 esconderia para
        # sempre um webhook que nunca vai ser processado.
        logger.error("[BLING WEBHOOK] conta desconhecida na rota: %s", account)
        return Response(status_code=404)

    corpo = await request.body()

    if not verify_signature(corpo, request.headers.get(_SIG_HEADER),
                            conta.client_secret):
        logger.warning("[BLING WEBHOOK] assinatura invalida (conta %s) — descartado",
                       account)
        return Response(status_code=401)

    try:
        evento = json.loads(corpo)
    except Exception:  # noqa: BLE001
        logger.error("[BLING WEBHOOK] corpo nao e JSON valido (conta %s)", account)
        return Response(status_code=200)

    event_id = evento.get("eventId")
    if not event_id:
        logger.error("[BLING WEBHOOK] evento sem eventId: %s", evento.get("event"))
        return Response(status_code=200)

    novo = await asyncio.to_thread(_insert_event, {
        "event_id": event_id,
        "account": account,
        "event": evento.get("event") or "",
        "payload": evento,
        "event_date": evento.get("date"),
        "status": "pending",
    })

    if novo:
        await _notify_worker()
    else:
        logger.info("[BLING WEBHOOK] evento %s (conta %s) repetido — absorvido",
                    event_id, account)

    return Response(status_code=200)


@router.post("/webhook/bling")
async def bling_webhook_legado(request: Request) -> Response:
    """Rota SEM slug. NAO REMOVER.

    O painel da conta 1 ja aponta para ca. Se ela sumir, os webhooks passam a
    404, o Bling retenta por ate 3 dias e depois DESABILITA a configuracao — a
    integracao para em silencio ate alguem reabilitar na mao.
    """
    return await _receber(request, config.DEFAULT_ACCOUNT)


@router.post("/webhook/bling/{account}")
async def bling_webhook(request: Request, account: str) -> Response:
    return await _receber(request, account)
```

- [ ] **Step 4: Rodar**

Run: `cd backend && python -m pytest tests/test_bling_webhook.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/webhook_router.py backend/tests/test_bling_webhook.py
git commit -m "feat(bling): webhook com rota por conta, preservando a rota legada"
```

---

## Task 10: Worker de webhook e jobs por conta

**Files:**
- Modify: `backend/app/bling/webhook_processor.py`
- Modify: `backend/app/bling/jobs.py`
- Modify: `backend/app/bling/backfill.py`
- Test: `backend/tests/test_bling_webhook_processor.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_processador_usa_a_conta_da_linha_do_evento(monkeypatch):
    from app.bling import webhook_processor as wp
    usadas = []

    class FakeClient:
        def __init__(self, account):   # duble exige a conta (decisao transversal 4)
            usadas.append(account)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_a):
            return False
        async def get(self, _path):
            return {"data": {"id": 7, "contato": {"id": 1}}}

    monkeypatch.setattr(wp, "_new_client", lambda account: FakeClient(account))
    monkeypatch.setattr(wp, "_last_event_date", _none_async)
    monkeypatch.setattr(wp, "_contact_row", lambda a, c: None)
    monkeypatch.setattr(wp, "upsert_from_bling", _ok_async)

    evento = {"event_id": "e1", "event": "order.created", "account": "secundaria"}
    await wp._handle_order(evento, {"data": {"id": 7}, "date": "2026-09-13T10:00:00Z"})
    assert usadas == ["secundaria"]


def test_contact_row_filtra_por_conta():
    from app.bling import webhook_processor as wp
    assert wp._contact_filter("secundaria", 42) == {
        "account": "secundaria", "id": 42}
```

Helpers:

```python
async def _none_async(*_a, **_k):
    return None


async def _ok_async(*_a, **_k):
    return None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_webhook_processor.py -q`
Expected: FAIL — `TypeError: _new_client() takes 0 positional arguments but 1 was given`

- [ ] **Step 3: Implementar**

Em `backend/app/bling/webhook_processor.py`:

```python
def _new_client(account: str):
    from app.bling.client import BlingClient
    return BlingClient(account=account)


def _contact_filter(account: str, contact_id: int) -> dict:
    return {"account": account, "id": contact_id}


def _contact_row(account: str, contact_id: int) -> dict | None:
    res = (get_supabase().table("bling_contacts").select("*")
           .eq("account", account).eq("id", contact_id)
           .limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _sale_event_date(account: str, order_id: int) -> str | None:
    res = (get_supabase().table("sales").select("bling_event_date")
           .eq("bling_account", account).eq("bling_order_id", order_id)
           .limit(1).execute())
    linhas = getattr(res, "data", None) or []
    return (linhas[0] or {}).get("bling_event_date") if linhas else None
```

`_handle_order` e `_handle_product` passam a ler
`account = evento.get("account") or "default"` e a repassar para
`_new_client`, `_contact_row`, `_sale_event_date`, `_resolve_lead`,
`upsert_from_bling`, `cancel_from_bling` e `apply_product_event`.

Em `backend/app/bling/jobs.py`: `BlingClient()` vira
`BlingClient(account=job.get("account") or "default")`, e toda criação de job
grava `"account"`.

Em `backend/app/bling/backfill.py`: `_new_client()` recebe a conta;
`backfill(months, account=config.DEFAULT_ACCOUNT)`. **Não** é executado para a conta 2
(decisão 4 da spec).

- [ ] **Step 4: Rodar**

Run: `cd backend && python -m pytest tests/test_bling_webhook_processor.py tests/test_bling_jobs.py tests/test_bling_backfill.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/webhook_processor.py backend/app/bling/jobs.py backend/app/bling/backfill.py backend/tests/test_bling_webhook_processor.py
git commit -m "feat(bling): worker de webhook, jobs e backfill cientes da conta"
```

---

## Task 11: API `/api/bling` — leitura com `?account=` e OAuth por conta

**Files:**
- Modify: `backend/app/bling/router.py`
- Test: `backend/tests/test_bling_router.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_produtos_filtram_pela_conta(monkeypatch, cliente_teste):
    filtros = {}
    _fingir_select(monkeypatch, filtros)
    cliente_teste.get("/api/bling/products?account=secundaria")
    assert filtros["account"] == "secundaria"


async def test_produtos_sem_account_caem_para_default(monkeypatch, cliente_teste):
    filtros = {}
    _fingir_select(monkeypatch, filtros)
    cliente_teste.get("/api/bling/products")
    assert filtros["account"] == "default"


async def test_authorize_aceita_a_conta(monkeypatch, cliente_teste):
    resp = cliente_teste.get("/api/bling/oauth/authorize?account=secundaria")
    assert resp.status_code == 200
    assert "client_id=cid2" in resp.json()["url"]


async def test_authorize_com_conta_desconhecida_da_400(cliente_teste):
    resp = cliente_teste.get("/api/bling/oauth/authorize?account=naoexiste")
    assert resp.status_code == 400


async def test_status_lista_as_contas_em_accounts(cliente_teste):
    resp = cliente_teste.get("/api/bling/status")
    corpo = resp.json()
    assert {c["account"] for c in corpo["accounts"]} == {"default", "secundaria"}


async def test_status_preserva_enabled_e_connected_no_topo(cliente_teste):
    """REGRESSAO: o frontend atual le body.enabled/body.connected no topo. Se a
    resposta virar lista pura, os dois viram undefined, o hook devolve
    enabled:false e o modal de venda cai em modo LEGADO em silencio — as vendas
    param de ir para o Bling sem erro nenhum na tela."""
    corpo = cliente_teste.get("/api/bling/status").json()
    assert "enabled" in corpo
    assert "connected" in corpo
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_router.py -q`
Expected: FAIL

- [ ] **Step 3: Implementar**

Em `backend/app/bling/router.py`, adicionar
`account: str = Query("default")` a `/products`, `/catalog`,
`/contacts/search`, `/payment-methods`, `/sellers`, `/orders` (POST e PUT),
`/contacts`, `/contacts/link`, `/contacts/unlink`, `/sync`, e filtrar as
consultas por `.eq("account", account)`.

A leitura de `bling_seller_map` (`router.py:247`), que resolve o `sold_by` do CRM
para o ID de vendedor do ERP, passa a filtrar **também por conta** — o mesmo
vendedor tem um ID diferente em cada CNPJ:

```python
    res = (get_supabase().table("bling_seller_map").select("bling_seller_id")
           .eq("user_email", user_email).eq("account", account)
           .limit(1).maybe_single().execute())
```

Três pontos de `router.py` ainda leem a coluna que a Task 7 aposentou:
`router.py:204` (docstring), `router.py:239` (o `select` do resolvedor de contato
inclui `bling_contact_id` na projeção de `leads`) e `router.py:435` (o retorno
`{"bling_contact_id": contact_id}`). O select deve parar de projetar a coluna e
passar a resolver o vínculo por `contacts._contato_do_lead(lead_id, account)`; o
retorno do endpoint mantém a chave `bling_contact_id` no JSON (é contrato com o
frontend), mas agora acompanhada de `account`.

Regra preservada: vendedor sem mapa na conta sai **sem vendedor** no pedido, sem
bloquear a venda — é o comportamento de hoje e não muda. Teste:

```python
async def test_vendedor_resolvido_por_conta(monkeypatch, cliente_teste):
    filtros = {}
    _fingir_seller_map(monkeypatch, filtros, retorno={"bling_seller_id": 77})
    cliente_teste.post("/api/bling/orders",
                       json={**_pedido_minimo(), "account": "secundaria"})
    assert filtros["account"] == "secundaria"
```

> ⚠️ **`create_contact_endpoint` (`router.py:429-434`) captura apenas
> `BlingValidationError`** — não tem `except BlingError` nem catch-all. Hoje isso
> é inerte, porque o endpoint não recebe conta e o default sempre resolve. No
> momento em que ele ganhar o parâmetro `account`, um `BlingUnknownAccount`
> passaria direto e viraria **500 em vez de 400**. Acrescente o `except
> BlingError` nesse endpoint junto com o parâmetro, não depois.

Um handler único para slug inválido:

```python
from app.bling.errors import BlingUnknownAccount


def _conta_valida(account: str):
    """Resolve a conta ou devolve 400. Slug errado e erro do chamador."""
    try:
        return config.account(account)
    except BlingUnknownAccount as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

> **Nunca chame `auth.new_state` e `auth.authorize_url` separadamente.** Use
> `auth.begin_authorization(account)`, criado na Task 4. As duas exigem a MESMA
> conta e nada estrutural garante isso — e como as duas contas podem compartilhar
> o mesmo aplicativo Bling, um par trocado **não daria erro**: gravaria o token
> no CNPJ errado, em silêncio.

OAuth:

```python
@router.get("/oauth/authorize")
async def oauth_authorize(account: str = Query("default")):
    conta = _conta_valida(account)
    state = await auth.new_state(conta.key)
    return {"url": auth.authorize_url(state, conta.key)}


@router.get("/oauth/callback")
async def oauth_callback(code: str = "", state: str = ""):
    conta = await auth.consume_state(state)
    if conta is None:
        return JSONResponse({"error": "state_invalido"}, status_code=400)
    await auth.exchange_code(code, conta)
    # ... resto do fluxo de sucesso existente
```

`/status` devolve o formato **aditivo** descrito na Task 4: `enabled` e
`connected` no topo (compatibilidade com o frontend atual) mais `accounts` com a
lista. Nunca trocar a lista pelo objeto — ver o aviso da Task 4.

- [ ] **Step 4: Rodar**

Run: `cd backend && python -m pytest tests/test_bling_router.py -q`
Expected: PASS

- [ ] **Step 5: A camada de proxy do Next — NÃO PULE**

O backend aceitar `?account=` não serve de nada se o proxy o descartar. As 11
rotas marcadas "Sim" no mapa de consumidores (topo deste documento) precisam
repassar a conta. Padrão para as que usam query string:

```ts
  const account = sp.get("account");
  if (account) params.set("account", account);
```

E para `orders` e `contacts`, que postam JSON, a conta viaja no corpo — o
componente já a inclui, o proxy só não pode filtrá-la ao remontar o payload.

**Teste obrigatório**, um por proxy que repassa (vitest, mockando `fetch`):

```ts
it("repassa o account para o backend", async () => {
  const chamadas: string[] = [];
  vi.stubGlobal("fetch", (url: string) => {
    chamadas.push(String(url));
    return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
  });
  await GET(new Request("http://x/api/bling/products?account=secundaria"));
  expect(chamadas[0]).toContain("account=secundaria");
});
```

> Sem isso o modo de falha é: vendedor escolhe a conta 2 → componente manda
> `?account=secundaria` → **o proxy descarta** → backend usa o default → o
> **pedido sai no CNPJ errado, sem erro na tela**. Nenhum teste de backend pega,
> porque o backend recebe exatamente o que o proxy mandou.

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/router.py backend/tests/test_bling_router.py \
        frontend/src/app/api/bling/
git commit -m "feat(bling): endpoints e proxies do Next com ?account= e OAuth por conta"
```

---

## Task 12: Orçamento — `bling_account` e a invariante da conversão

**Files:**
- Modify: `backend/app/quotes/router.py`
- Test: `backend/tests/test_quotes_payload.py`

Regra do usuário: **um orçamento criado na conta X só vira pedido na conta X.**

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_orcamento_nasce_com_a_conta_escolhida(monkeypatch, cliente_teste):
    gravado = _capturar_insert_quote(monkeypatch)
    cliente_teste.post("/api/quotes", json={**_corpo_minimo(),
                                            "account": "secundaria"})
    assert gravado["bling_account"] == "secundaria"


async def test_put_nao_troca_a_conta_do_orcamento(monkeypatch, cliente_teste):
    """A proposta ja existe naquele Bling — trocar a conta orfanaria o registro."""
    atualizado = _capturar_update_quote(monkeypatch, atual={
        "id": "q1", "status": "rascunho", "bling_account": "default"})
    cliente_teste.put("/api/quotes/q1", json={**_corpo_minimo(),
                                              "account": "secundaria"})
    assert "bling_account" not in atualizado


async def test_conversao_herda_a_conta_do_orcamento(monkeypatch, cliente_teste):
    """Invariante: o pedido sai na MESMA conta do orcamento."""
    usadas = []
    _fingir_quote(monkeypatch, {"id": "q1", "status": "enviado",
                                "bling_account": "secundaria"})
    monkeypatch.setattr("app.quotes.router.create_order",
                        lambda *a, account=None, **k: usadas.append(account))
    cliente_teste.post("/api/quotes/q1/convert")
    assert usadas == ["secundaria"]


async def test_venda_gerada_carrega_a_conta_do_orcamento(monkeypatch, cliente_teste):
    venda = _capturar_insert_sale(monkeypatch)
    _fingir_quote(monkeypatch, {"id": "q1", "status": "enviado",
                                "bling_account": "secundaria"})
    cliente_teste.post("/api/quotes/q1/convert")
    assert venda["bling_account"] == "secundaria"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_quotes_payload.py -q`
Expected: FAIL

- [ ] **Step 3: Implementar**

Em `backend/app/quotes/router.py`:

- `QuoteIn` ganha `account: str = config.DEFAULT_ACCOUNT`; `create_quote_endpoint` valida com
  `_conta_valida` e grava `bling_account`.
- `update_quote_endpoint` **ignora** qualquer `account` do corpo — a conta do
  orçamento é imutável depois de criado. Não levanta erro: simplesmente não
  entra no dicionário de atualização.
- `convert_quote_endpoint` (`quotes/router.py:653`) lê `quote["bling_account"]` e
  o repassa para `create_order(...)` e para a linha de `sales`. O endpoint **não
  recebe corpo**, então a invariante sai de graça da assinatura.
- Dentro dele há um caminho de fallback (`quotes/router.py:682-687`): quando o
  orçamento perdeu o `bling_contact_id`, ele chama `contacts.resolve(lead)` para
  reresolver o contato. Essa chamada **precisa receber a conta do orçamento** —
  `contacts.resolve(lead, account)`. Sem isso o fallback resolveria o contato na
  conta errada e o pedido sairia referenciando um ID que não existe naquele CNPJ.
- A ordem das quatro etapas do `convert` (409 → `create_order` → `set_situacao` →
  `UPDATE quotes`) **não muda**. O docstring explica por quê: inverter 2 e 3
  deixaria uma proposta marcada como aprovada sem venda nenhuma.
- `store_id` do payload da proposta passa a vir de
  `config.account(quote["bling_account"]).store_id`.

Comentário a incluir no `convert_quote_endpoint`:

```python
    # A conta NAO e parametro: a proposta comercial vive naquela conta do ERP e
    # os IDs de contato e produto do pedido sao os de la. Emitir na outra conta
    # referenciaria IDs inexistentes — ou, pior, IDs que existem e apontam para
    # outro produto.
    account = quote.get("bling_account") or config.DEFAULT_ACCOUNT
```

- [ ] **Step 4: Rodar**

Run: `cd backend && python -m pytest tests/ -k quote -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/quotes/router.py backend/tests/test_quotes_payload.py
git commit -m "feat(quotes): orcamento carrega a conta e a conversao a herda sem permitir troca"
```

---

## Task 13: Suíte completa do backend

**Files:** nenhum (verificação)

- [ ] **Step 1: Rodar tudo**

Run: `cd backend && python -m pytest tests/ -q`
Expected: PASS, zero falhas. Qualquer teste antigo que quebrou indica um call
site com assinatura desatualizada.

- [ ] **Step 2: Varredura de call sites esquecidos**

```bash
grep -rn 'BlingClient()' backend/app/
grep -rn 'get_access_token()' backend/app/
grep -rn 'ratelimit.acquire()' backend/app/
grep -rn 'bling_contact_id' backend/app/
```

Expected: `BlingClient()` sem `account=` só é aceitável onde a conta é
comprovadamente `default`. Nenhum uso de `leads.bling_contact_id` deve restar
em `app/bling` ou `app/quotes`.

- [ ] **Step 3: Commit (se houve correção)**

```bash
git add -A backend/
git commit -m "fix(bling): call sites remanescentes sem conta explicita"
```

---

## Task 14: Frontend — status, gate e lógica de seleção

**Files:**
- Create: `frontend/src/lib/bling-accounts.ts`
- Create: `frontend/src/lib/bling-accounts.test.ts`
- Modify: `frontend/src/hooks/use-bling-status.ts`
- Modify: `frontend/src/lib/bling-gate.ts`

- [ ] **Step 1: Escrever os testes que falham**

Criar `frontend/src/lib/bling-accounts.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  contasDisponiveis,
  precisaSeletor,
  contaPadrao,
  trocaLimpaFormulario,
} from "./bling-accounts";

const CONTAS = [
  { account: "default", label: "Canastra CNPJ 1", configured: true, connected: true },
  { account: "secundaria", label: "Canastra CNPJ 2", configured: true, connected: true },
];

describe("contasDisponiveis", () => {
  it("devolve so as conectadas", () => {
    const contas = [...CONTAS, {
      account: "terceira", label: "T", configured: true, connected: false,
    }];
    expect(contasDisponiveis(contas).map((c) => c.account))
      .toEqual(["default", "secundaria"]);
  });

  it("devolve vazio quando nenhuma esta conectada", () => {
    expect(contasDisponiveis([{ ...CONTAS[0], connected: false }])).toEqual([]);
  });
});

describe("precisaSeletor", () => {
  it("esconde o seletor com uma conta so", () => {
    expect(precisaSeletor([CONTAS[0]])).toBe(false);
  });

  it("mostra o seletor com duas contas", () => {
    expect(precisaSeletor(CONTAS)).toBe(true);
  });
});

describe("contaPadrao", () => {
  it("prefere a default quando conectada", () => {
    expect(contaPadrao(CONTAS)).toBe("default");
  });

  it("cai para a primeira conectada quando a default nao esta", () => {
    const contas = [{ ...CONTAS[0], connected: false }, CONTAS[1]];
    expect(contaPadrao(contas)).toBe("secundaria");
  });

  it("devolve null sem nenhuma conta conectada", () => {
    expect(contaPadrao([{ ...CONTAS[0], connected: false }])).toBeNull();
  });
});

describe("trocaLimpaFormulario", () => {
  it("nao pede confirmacao com o formulario vazio", () => {
    expect(trocaLimpaFormulario({ itens: 0, contatoId: null })).toBe(false);
  });

  it("pede confirmacao quando ha itens", () => {
    expect(trocaLimpaFormulario({ itens: 2, contatoId: null })).toBe(true);
  });

  it("pede confirmacao quando ha contato escolhido", () => {
    expect(trocaLimpaFormulario({ itens: 0, contatoId: 55 })).toBe(true);
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd frontend && npm test -- bling-accounts`
Expected: FAIL — `Cannot find module './bling-accounts'`

- [ ] **Step 3: Implementar**

Criar `frontend/src/lib/bling-accounts.ts`:

```ts
/**
 * Logica pura de selecao de conta Bling. Fica fora do componente para poder ser
 * testada sem montar o modal inteiro — mesmo padrao de `quote-state.ts`.
 */
export type ContaBling = {
  account: string;
  label: string;
  configured: boolean;
  connected: boolean;
};

/** So conta conectada pode emitir: sem refresh_token nao ha como falar com o ERP. */
export function contasDisponiveis(contas: ContaBling[]): ContaBling[] {
  return contas.filter((c) => c.configured && c.connected);
}

/**
 * Com uma conta so o seletor nao aparece — a feature inteira fica invisivel ate
 * a segunda conta ser configurada, e nada muda para quem usa o CRM hoje.
 */
export function precisaSeletor(contas: ContaBling[]): boolean {
  return contasDisponiveis(contas).length > 1;
}

export function contaPadrao(contas: ContaBling[]): string | null {
  const disponiveis = contasDisponiveis(contas);
  if (disponiveis.length === 0) return null;
  const padrao = disponiveis.find((c) => c.account === "default");
  return (padrao ?? disponiveis[0]).account;
}

/**
 * Trocar a conta invalida itens e contato: os SKU/ID nao coincidem entre as
 * contas, entao remapear seria adivinhacao com risco de emitir o produto errado.
 * Confirmar so quando ha algo a perder.
 */
export function trocaLimpaFormulario(
  estado: { itens: number; contatoId: number | null },
): boolean {
  return estado.itens > 0 || estado.contatoId !== null;
}
```

**`use-bling-status.ts` — o que o código realmente faz hoje** (conferido, não
presumir): ele mantém um **memo de módulo** (`let cache`, `let inflight`)
compartilhado entre todos os chamadores, porque os quatro pontos que abrem o
modal de venda montam em telas diferentes e sem isso cada abertura repetiria a
chamada. E ele **colapsa a resposta num único booleano**:

```ts
const ok = !!body.enabled && !!body.connected;
```

Esse colapso deixa de bastar. O endpoint (Task 11) devolve `enabled` e
`connected` no topo **e** `accounts` com a lista — formato aditivo, de propósito.
O hook passa a guardar no memo a **lista inteira** (`ContaBling[]`) além do
booleano que já expõe, e passa a expor as duas coisas.

Preserve o memo e o `inflight`: eles existem por um motivo real e removê-los
multiplicaria as chamadas por quatro. E mantenha o booleano funcionando a partir
dos campos do topo — é o que garante que, se `accounts` vier ausente por qualquer
razão, o modal de venda não caia em modo legado em silêncio.

**`bling-gate.ts` — a assinatura real é maior do que a deste plano.**
`blingGate({ loading, error, enabled, isEditing, skipBling })`, e há duas regras
já documentadas no arquivo que **não podem ser quebradas**:

- Falha ao consultar o status **bloqueia** o modal; não cai para o modo legado.
  O comentário explica: rede é falha transitória, venda gravada fora do ERP é
  permanente.
- `skipBling` ("Registrar sem enviar ao Bling") curto-circuita tudo, inclusive
  `error`.

O `enabled` booleano vira "a conta escolhida está conectada". E **quando
`skipBling` está marcado o seletor de conta some da tela**: a venda não vai para
ERP nenhum, então escolher CNPJ não significa nada — deixar o seletor ali
sugeriria que a escolha tem efeito. Isso vale para a Task 15 também.

- [ ] **Step 4: Rodar**

Run: `cd frontend && npm test -- bling-accounts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/bling-accounts.ts frontend/src/lib/bling-accounts.test.ts frontend/src/hooks/use-bling-status.ts frontend/src/lib/bling-gate.ts
git commit -m "feat(bling): logica pura de selecao de conta no frontend"
```

---

## Task 15: Frontend — seletor no pedido e no orçamento

**Files:**
- Modify: `frontend/src/components/sales/bling-order-form.tsx`
- Modify: `frontend/src/components/sales/bling-contact-resolver.tsx`
- Modify: `frontend/src/app/(authenticated)/orcamento/page.tsx`

> **Antes de tocar em qualquer componente, invoque a skill `frontend-design`.**
> É regra registrada do projeto para toda alteração de frontend.

- [ ] **Step 1: Adicionar o seletor como PRIMEIRO campo**

No `bling-order-form.tsx`, acima de tudo. Ele é o primeiro porque catálogo,
contato, forma de pagamento e vendedor são todos escopados por ele.

- Renderizar só quando `precisaSeletor(contas)` for `true`.
- Valor inicial: `contaPadrao(contas)`.
- Rotular com `label`, nunca com o slug.

- [ ] **Step 2: Limpar o formulário ao trocar de conta**

```tsx
const aoTrocarConta = (nova: string) => {
  if (trocaLimpaFormulario({ itens: itens.length, contatoId })) {
    const ok = window.confirm(
      "Trocar de conta vai limpar os itens, o contato e a forma de pagamento. " +
      "Os produtos têm códigos diferentes em cada conta. Continuar?",
    );
    if (!ok) return;
  }
  setItens([]);
  setContatoId(null);
  setFormaPagamento(null);
  setConta(nova);
};
```

- [ ] **Step 3: Propagar a conta nas buscas**

Toda chamada a `/api/bling/products`, `/catalog`, `/contacts/search`,
`/payment-methods` e `/sellers` passa `?account=${conta}`.

- [ ] **Step 4: Seletor desabilitado na conversão de orçamento**

Na tela de conversão, o seletor aparece **desabilitado**, exibindo a conta do
orçamento, com a dica "definido pelo orçamento #N". Mostrar desabilitado em vez
de esconder é o que ensina a regra ao vendedor.

- [ ] **Step 5: Rodar a suíte do frontend**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/sales/ frontend/src/app/\(authenticated\)/orcamento/
git commit -m "feat(bling): seletor de conta no pedido e no orcamento"
```

---

## Task 16: Frontend — `/config` e rótulo nos deep links

**Files:**
- Modify: `frontend/src/components/config/bling-settings.tsx`
- Modify: `frontend/src/lib/sale-display.ts`
- Modify: `frontend/src/lib/bling-contact-display.ts`
- Test: `frontend/src/lib/sale-display.test.ts`

- [ ] **Step 1: Escrever o teste do rótulo**

> **Funções reais do arquivo** (conferidas): `sale-display.ts` já tem
> `orderLabel(sale): string` (devolve `"#1234"`) e
> `blingOrderUrl(orderId): string`. **Não** invente um `rotuloDoPedido` paralelo
> nem altere o significado de `orderLabel`, que é usado em vários lugares.
> Acrescente uma função nova e separada, que devolve **só** o rótulo da conta e
> deixa o componente decidir onde encaixá-lo.

```ts
import { describe, expect, it } from "vitest";
import { accountLabel } from "./sale-display";

const CONTAS = [
  { account: "default", label: "Canastra CNPJ 1", configured: true, connected: true },
  { account: "secundaria", label: "Canastra CNPJ 2", configured: true, connected: true },
];

describe("accountLabel", () => {
  it("devolve null quando so existe uma conta", () => {
    expect(accountLabel({ bling_account: "default" }, [CONTAS[0]])).toBeNull();
  });

  it("devolve o rotulo da conta quando existem duas", () => {
    expect(accountLabel({ bling_account: "secundaria" }, CONTAS))
      .toBe("Canastra CNPJ 2");
  });

  it("devolve null para venda fora do Bling", () => {
    expect(accountLabel({ bling_account: null }, CONTAS)).toBeNull();
  });

  it("cai para o slug quando a conta nao esta mais configurada", () => {
    // Venda historica de uma conta que foi removida do BLING_ACCOUNTS: mostrar
    // o slug cru e melhor que esconder a informacao ou quebrar a tela.
    expect(accountLabel({ bling_account: "antiga" }, CONTAS)).toBe("antiga");
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd frontend && npm test -- sale-display`
Expected: FAIL — `rotuloDoPedido is not exported`

- [ ] **Step 3: Implementar**

```ts
/**
 * Rotulo da conta Bling de uma venda, ou null quando nao ha o que dizer.
 *
 * Existe porque o Bling NAO tem URL que force a conta: `blingOrderUrl` abre no
 * painel de onde o usuario ja estiver logado, e um pedido da conta 2 aberto por
 * quem esta logado na conta 1 mostra "nao encontrado". Nao da para resolver isso
 * no link — da para dizer ao vendedor em qual painel entrar antes de clicar.
 *
 * Devolve null com uma conta so: nao ha ambiguidade a desfazer, e um rotulo
 * constante em toda linha da tabela seria ruido.
 */
export function accountLabel(
  sale: Pick<Sale, "bling_account">, contas: ContaBling[],
): string | null {
  if (!sale.bling_account) return null;      // venda fora do Bling
  if (contas.length <= 1) return null;       // sem ambiguidade
  const conta = contas.find((c) => c.account === sale.bling_account);
  // Conta removida do BLING_ACCOUNTS depois da venda: o slug cru diz mais que
  // esconder a informacao, e nao quebra a tela.
  return conta?.label ?? sale.bling_account;
}
```

Equivalente em `bling-contact-display.ts` para o contato, com a mesma regra de
devolver `null` quando há uma conta só.

- [ ] **Step 4: `/config` com uma linha por conta**

`bling-settings.tsx` passa a iterar a lista de `GET /api/bling/status`,
mostrando por conta: label, conectado/desconectado, validade do token e botão
"Conectar" que chama `/api/bling/oauth/authorize?account=<slug>`.

- [ ] **Step 5: Rodar**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/config/bling-settings.tsx frontend/src/lib/sale-display.ts frontend/src/lib/bling-contact-display.ts frontend/src/lib/sale-display.test.ts
git commit -m "feat(bling): /config por conta e rotulo da conta nos links do painel"
```

---

## Task 17: Verificação final e documentação de operação

**Files:**
- Modify: `docs/setup/bling-observacoes-producao.md`

- [ ] **Step 1: Suíte completa nas duas pontas**

```bash
cd backend && python -m pytest tests/ -q
cd ../frontend && npm test
```

Expected: PASS nas duas.

- [ ] **Step 2: Documentar a operação**

Acrescentar a `docs/setup/bling-observacoes-producao.md` uma seção com:

- As variáveis novas (`BLING_ACCOUNTS`, `BLING_<CONTA>_*`) e o fallback.
- O passo a passo de conectar a conta 2: aplicar migration → push → preencher
  `.env` da VPS → `/config` → Conectar.
- A URL do webhook da conta 2 a cadastrar no painel do Bling:
  `https://api.canastrainteligencia.com/webhook/bling/secundaria`.
- O aviso de que a rota legada `/webhook/bling` **não pode ser removida**
  enquanto o painel da conta 1 apontar para ela.
- A janela de risco entre migration e push (§9 da spec).

- [ ] **Step 3: Commit**

```bash
git add docs/setup/bling-observacoes-producao.md
git commit -m "docs(bling): operacao da segunda conta e a janela de deploy"
```

---

## Checklist antes do push

- [ ] `cd backend && python -m pytest tests/ -q` — verde
- [ ] `cd frontend && npm test` — verde
- [ ] `git log --oneline origin/master..HEAD` — só commits desta entrega
  (armadilha de branch-tirada-de-branch já ocorreu neste repo)
- [ ] Migration aplicada no Supabase e as três conferências do Task 5 Step 3 batendo
- [ ] Pedido de teste criado contra o Postgres real, confirmando ausência de `42P10`
- [ ] Horário de baixo movimento combinado com o usuário
- [ ] Autorização explícita do usuário para `git push origin <branch>:master`
