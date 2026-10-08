# ValerIA de Botões v2 (vitrine) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the v2 button flow from `docs/superpowers/specs/2026-10-08-valeria-botoes-v2-vitrine-design.md`:
- a product showcase (carousel + price table) right after the lead picks a branch;
- free text read by an LLM classifier that only picks fixed replies;
- a 2-question qualification after the showcase;
- automatic handoff of leads who stalled after showing intent.

**Architecture:** v2 is a NEW flow (`valeria_botoes_v2`) living beside v1. It gets its own registry (`valeria_registry_v2.py`), a pure engine (`valeria_engine_v2.py`) and a runner (`valeria_runner_v2.py`). The runner reuses v1's I/O helpers by import. v1 files change only by additive, backward-compatible edits:
- a new `Card` type and a `cards` field on `No`;
- a `flow_id` parameter on the content API.

The processor dispatches by `flow_state.flow` first, so conversations in progress finish on the flow they started in.

**Tech Stack:** Python 3.11, FastAPI, Supabase (PostgREST), WhatsApp Cloud API (`interactive.type=carousel`), Gemini via `app.agent.gemini_client`, pytest. Frontend: Next.js App Router + vitest.

---

## Ground rules for every task (read first)

- **Repo / worktree:** `/root/crm-wt/valeria-v2`, branch `feat/valeria-botoes-v2-vitrine`.
  - NEVER work in `/srv/Maquinadevendascanastra`: it is a deploy target and gets `git reset --hard`.
  - NEVER push.
  - Several agents share this worktree at the same time. Only `git add` the exact files your task lists. If `git commit` fails with `index.lock`, wait 3 s and retry (up to 10 times).
  - Never run `git stash`, `git reset`, `git checkout -- .` or anything that touches files you don't own.
- **Running backend tests:** there is no local pytest. Use the API image, mounting the WHOLE repo, with no `backend/.env`:
  ```bash
  docker run --rm --user root -v /root/crm-wt/valeria-v2:/repo -w /repo/backend \
    -e SUPABASE_URL=https://example.supabase.co -e SUPABASE_SERVICE_KEY=ci-dummy \
    canastra-api:latest sh -c "pip install -q -r requirements-dev.txt >/dev/null 2>&1; \
    python -m pytest -q -p no:cacheprovider tests/<your_test_file>.py"
  ```
  During your task, run only your own test files plus the existing tests named in your task. Other agents are editing other files, so the full suite runs only in the final task.
- **Style:** match the surrounding code.
  - Comments and docstrings in Portuguese.
  - Fail-soft in the inbound path: log and continue, never raise to the processor.
  - Pure modules have no I/O.
  - Test files are named `tests/test_valeria_v2_<topic>.py`.
- **Business facts** come from spec §4 and must not be invented. The pending ones (Kit Amostra price and composition, Microlote PL price) must not appear as numbers anywhere.

## File map

| File | Task | Responsibility |
|---|---|---|
| `backend/app/whatsapp/base.py`, `meta.py`, `mock_provider.py` | T1 | `send_interactive_carousel` |
| `backend/app/button_flow/valeria_tabela.py` (new) | T2 | Pure: catalog rows → price table text, card text resolution, PL total |
| `backend/app/button_flow/_llm_comum.py` (new), `valeria_classifier.py` (new), `classifier.py` | T3 | Shared LLM helpers + v2 classifier |
| `backend/app/button_flow/valeria_registry.py` (additive), `valeria_registry_v2.py` (new) | T4 | `Card` type; v2 flow data |
| `backend/app/button_flow/valeria_engine_v2.py` (new) | T5 | Pure v2 decision function |
| `backend/app/button_flow/config.py`, `runner.py`, `buffer/processor.py`, `valeria_content.py`, `valeria_flow_router.py` | T6 | Kill switch, dispatch by flow, content/API per `flow_id` |
| `frontend/src/components/campaigns/valeria-flow-*` | T7 | Version selector v1/v2 in the editor and activation |
| `backend/app/button_flow/valeria_runner_v2.py` (new) | T8 | v2 turn: classify, decide, send, persist, handoff note |
| `backend/app/button_flow/valeria_repasse.py` (new), `backend/app/worker/main.py` | T9 | Stalled-lead sweep |
| — | T10 | Full suite, review, report |

## Execution waves (parallelism)

| Wave | Tasks | Depends on |
|---|---|---|
| 1 | **T1, T2, T3, T4** in parallel | — |
| 2 | **T5, T6, T7** in parallel | T4 (T5, T6); T6's API contract (T7, fixed below) |
| 3 | **T8** | T1, T2, T3, T4, T5, T6 |
| 4 | **T9** | T8 |
| 5 | **T10** | all |

---

## Shared contracts (fixed here so parallel tasks agree)

### C1. Registry types (T4 owns; T2, T5, T8 consume)

Added to `valeria_registry.py`, which v1 keeps importing unchanged:

```python
@dataclass(frozen=True)
class Card:
    """Um card do carrossel. O botão do card devolve o id `card:<id>` no webhook."""
    id: str                       # "classico"
    foto: str                     # caminho sob backend/app/photos/
    corpo: str                    # texto com marcadores {preco:<products.name exato>}
    skus: tuple[str, ...]         # products.name que o card cita; todos ativos e com preço, senão o card não sai
    exige_min_lot: str | None = None   # ex.: "100 un" — o card só sai se TODOS os skus tiverem esse min_lot
    destino: str = ""             # nó para onde o toque no card leva (QA1 / QP1)
    rotulo_botao: str = "Quero esse"

# `No` ganha um campo novo, com default (v1 não muda):
#   cards: tuple[Card, ...] = ()
# e `tela` passa a aceitar também "carrossel".
```

### C2. v2 registry module API (T4 owns)

`app.button_flow.valeria_registry_v2` exports:

```python
FLOW_ID = "valeria_botoes_v2"
NO_ENTRADA = "N0"
NOS: dict[str, No]             # N0, VA, VP, QA1, QA2, QP1, QP2, PL_ABAIXO, VK, VD_A, VD_P, VO, C1, E1, E2, E3, E4
TERMINAIS: dict[str, Terminal] # T_HANDOFF, T_HANDOFF_PL, T_HANDOFF_ARTHUR, T_KIT, T_ADIAR, T_ADIADO, T_HUMANO, T_FIM, T_OPTOUT
MENSAGENS_PRONTAS: dict[str, str]   # normalizar(texto) -> "VA" | "VP"
RAMO_DO_NO: dict[str, str]          # no_id -> "atacado" | "private_label" | "consumo" | "exportacao" | "entrada"
HANDOFF_DO_RAMO = {"atacado": "T_HANDOFF", "private_label": "T_HANDOFF_PL", "exportacao": "T_HANDOFF_ARTHUR"}
VITRINE_DO_RAMO = {"atacado": "VA", "private_label": "VP"}
DUVIDAS_DO_RAMO = {"atacado": "VD_A", "private_label": "VD_P"}
CORPO_ACOES = "como você quer seguir?"     # corpo da 3ª mensagem da vitrine (botões de ação)
FAQ: dict[str, dict[str, str]]       # ramo -> faq_id -> texto default (spec §6.4); faq_ids: grao, minimo, frete, pagamento, revenda, capsula (atacado), prazo_pl, fotolito (PL)
FAQ_DESCRICAO: dict[str, str]        # faq_id -> 1 linha p/ o prompt do classificador (inclui "preco": "pede preço/valor/tabela")
REGRA_QP2: dict[tuple[str, str], str]  # (resposta_QP1, resposta_QP2) -> destino; ausente -> "T_HANDOFF_PL"
NOS_COM_INTENCAO = frozenset({"QA1", "QA2", "QP1", "QP2", "VK"})   # usado pelo repasse automático (T9)
CHAVE_NUDGE = "__nudge__"; CORPO_NUDGE = "pra seguir, é só tocar numa das opções abaixo 👇"
CHAVE_REGRAS_ATACADO = "__regras_atacado__"; CHAVE_COMO_FUNCIONA_PL = "__como_funciona_pl__"
REGRAS_ATACADO_DEFAULT: str    # spec §6.1 — as 4 linhas ✅🚚💳💰
COMO_FUNCIONA_PL_DEFAULT: str  # spec §6.2 msg 2, com marcador {total_pl}
CHAVES_TEXTO: frozenset[str]   # chaves editáveis que não são nó: nudge, rótulo da lista, regras, como-funciona, e "faq:<ramo>:<faq_id>" para cada FAQ
TETO_RUIDO = 2                 # 2º RUIDO seguido → repasse
```

Button-id conventions inside v2 nodes:
- **Action buttons** of VA: `pedido`→QA1, `provar`→VK, `duvida`→VD_A. Of VP: `orcamento`→QP1, `provar`→VK, `duvida`→VD_P.
- **FAQ list rows** (VD_A / VD_P) have `destino = "faq:<faq_id>"`, plus:
  - `faq_outra` → `VO`;
  - `faq_vendedor` → `T_HANDOFF` (VD_A) or `T_HANDOFF_PL` (VD_P).
- **VK buttons:**
  - `quero_kit` → `T_KIT`;
  - `ver_precos` → `"tabela"` (special: resend table + action buttons of the ramo's vitrine);
  - `vendedor` → `"handoff"` (special: handoff of the ramo).
- **PL_ABAIXO buttons:** `quero_kit` → `T_KIT`, `depois` → `T_ADIAR`.
- **QP1:** `tenho_marca`, `criar_zero` → `QP2`; `tenho_graos` → `T_HANDOFF_PL`. **QP2:** `menos100`, `de100a500`, `mais500` → destino via `REGRA_QP2` (the declared `destino` is `"regra:QP2"`).
- **QA1/QA2:** ids and `grava` exactly as v1's N1/N2: `cafeteria`/`loja`/`outro` with segment, and `ate30`/`ate100`/`mais100` with `monthly_volume_kg` 30/65/150. QA2 → `T_HANDOFF`.
- **Copied from v1 unchanged** (same ids, texts and destinations): C1, E1–E4, terminals.
  - C1's `quantidade` button goes to `VA` instead of `N1`.
  - Every v1 destination that pointed to N1/P1 points to VA/VP.

### C3. Engine v2 API (T5 owns; T8 consumes)

```python
# app.button_flow.valeria_engine_v2
@dataclass(frozen=True)
class TextoClassificado:
    conteudo: str
    classe: str                 # "BOTAO"|"FAQ"|"PERGUNTA"|"VENDEDOR"|"SAIR"|"RUIDO"
    botao_id: str | None = None
    faq_id: str | None = None   # inclui "preco"

@dataclass(frozen=True)
class DecisaoV2(valeria_engine.Decisao):
    memoria: dict = field(default_factory=dict)  # chaves a MESCLAR no flow_state: ramo, interesse, respostas{no:botao_id}, retorno, ruidos
    faq: str | None = None          # faq_id cuja resposta fixa sai ANTES da tela
    vitrine: str = "nenhuma"        # "completa" (carrossel+texto+ações) | "tabela" (texto+ações) | "acoes" (só ações) | "nenhuma"
    repasse_motivo: str | None = None

def decidir(no_atual: str | None, evento, estado: dict | None, nos, terminais,
            *, corpo_nudge: str | None = None) -> DecisaoV2: ...
def primeira_tela(texto: str) -> str   # "VA" | "VP" | "N0" (mensagens prontas, spec §5.1)
```

### C4. Classifier API (T3 owns; T8 consumes)

```python
# app.button_flow.valeria_classifier
@dataclass(frozen=True)
class Classificacao:
    classe: str                 # uma de CLASSES
    botao_id: str | None = None
    faq_id: str | None = None
CLASSES = ("BOTAO", "FAQ", "PERGUNTA", "VENDEDOR", "SAIR", "RUIDO")
async def classificar(texto: str, *, no_id: str, ramo: str | None,
                      botoes: list[tuple[str, str]], faqs: dict[str, str],
                      ultima_mensagem: str, lead_id: str | None = None) -> Classificacao
# NUNCA levanta. Saída validada: botao_id ∈ ids de `botoes`, faq_id ∈ `faqs`; senão RUIDO.
```

### C5. Table API (T2 owns; T8 consumes)

```python
# app.button_flow.valeria_tabela  (puro; recebe a lista de produtos já lida)
def precos_por_nome(produtos: list[dict], setor: str) -> dict[str, str]
    # {products.name: price_formatted} só de is_active e price_formatted não vazio, filtrando setor ("Atacado"/"Private Label")
def resolver_card(card: Card, precos: dict[str, str], min_lots: dict[str, str]) -> str | None
    # texto final do card ou None se algum sku faltar / exige_min_lot não bater / texto > 160 / > 2 quebras
def min_lots_por_nome(produtos: list[dict], setor: str) -> dict[str, str]
def tabela_atacado(precos: dict[str, str], regras: str) -> str | None   # None se precos vazio
def como_funciona_pl(precos: dict[str, str], modelo: str) -> str | None  # resolve {total_pl}; None se o SKU base faltar
def total_pl(precos: dict[str, str]) -> str | None   # "R$2.670,00" = 100 × preço("Café Canastra 250g — c/ embalagem Canastra")
```

### C6. Provider API (T1 owns; T8 consumes)

```python
async def send_interactive_carousel(self, to: str, body: str, cards: list[dict]) -> dict
# cards: [{"image_url": str, "body": str, "buttons": [(id, titulo), ...]}]
# Valida: 2 ≤ len(cards) ≤ 10; todo card com image_url; body do card ≤ 160; mesmo nº de botões em todos (1..2); título ≤ 20.
```

### C7. HTTP API for the editor (T6 owns; T7 consumes)

All existing `/api/valeria-flow` routes accept an optional query param `flow_id` (`valeria_botoes_v1` default | `valeria_botoes_v2`):
- `GET /api/valeria-flow?flow_id=...` → same shape as today, built from that flow's registry. For v2, nodes include `cards: [{id, corpo, corpo_default}]` and the reserved text keys from `CHAVES_TEXTO` under `textos: [{chave, corpo, corpo_default}]`.
- `PUT /api/valeria-flow/{node_id}?flow_id=...` → same body. For v2, `node_id` may be a node, a terminal, a key in `CHAVES_TEXTO`, or `card:<card_id>` (only `corpo` editable; validated after resolving prices: ≤160 chars, ≤2 newlines).
- `DELETE /api/valeria-flow/{node_id}?flow_id=...`.
- `POST /api/valeria-flow/activate` body gains `flow_id` (default `valeria_botoes_v1`).
- `GET /api/valeria-flow/channels` → each channel's current profile includes its `flow_id`.

---

### Task 1: Carousel in the WhatsApp provider

**Files:**
- Modify: `backend/app/whatsapp/base.py` (after `send_interactive_list`), `backend/app/whatsapp/meta.py` (after `send_interactive_list`), `backend/app/whatsapp/mock_provider.py`
- Test: `backend/tests/test_valeria_v2_carousel_provider.py`
- Read for patterns: `backend/tests/test_valeria_meta_interactive_2026_09_29.py` (how `_post` is mocked)

- [ ] **Step 1: Write the failing tests.** Mock `MetaCloudClient._post` the same way `test_valeria_meta_interactive_2026_09_29.py` does. The tests:

```python
import pytest
from app.whatsapp.meta import MetaCloudClient  # use the same constructor/fixture as the existing interactive test

def _cards(n, botoes=1):
    return [{"image_url": f"https://x/{i}.jpg", "body": f"card {i}",
             "buttons": [(f"card:c{i}:{j}", "Quero esse") for j in range(botoes)]} for i in range(n)]

@pytest.mark.asyncio
async def test_payload_carrossel_segue_doc_da_meta(meta_client_com_post_mockado):
    client, post = meta_client_com_post_mockado
    post.return_value = {"messages": [{"id": "wamid.X"}]}
    await client.send_interactive_carousel("5534999990000", "corpo", _cards(3))
    payload = post.call_args.args[0]
    assert payload["type"] == "interactive"
    inter = payload["interactive"]
    assert inter["type"] == "carousel"
    assert inter["body"] == {"text": "corpo"}
    cards = inter["action"]["cards"]
    assert [c["card_index"] for c in cards] == [0, 1, 2]
    assert cards[0]["header"] == {"type": "image", "image": {"link": "https://x/0.jpg"}}
    assert cards[0]["body"] == {"text": "card 0"}
    assert cards[0]["action"]["buttons"] == [
        {"type": "quick_reply", "quick_reply": {"id": "card:c0:0", "title": "Quero esse"}}]

@pytest.mark.parametrize("n", [1, 11])
@pytest.mark.asyncio
async def test_recusa_fora_de_2_a_10_cards(meta_client_com_post_mockado, n):
    client, _ = meta_client_com_post_mockado
    with pytest.raises(ValueError):
        await client.send_interactive_carousel("5534999990000", "corpo", _cards(n))

@pytest.mark.asyncio
async def test_recusa_cards_com_numero_de_botoes_diferente(meta_client_com_post_mockado):
    client, _ = meta_client_com_post_mockado
    cards = _cards(2); cards[1]["buttons"] = cards[1]["buttons"] * 2
    with pytest.raises(ValueError):
        await client.send_interactive_carousel("5534999990000", "corpo", cards)

@pytest.mark.asyncio
async def test_recusa_corpo_do_card_acima_de_160(meta_client_com_post_mockado):
    client, _ = meta_client_com_post_mockado
    cards = _cards(2); cards[0]["body"] = "x" * 161
    with pytest.raises(ValueError):
        await client.send_interactive_carousel("5534999990000", "corpo", cards)

@pytest.mark.asyncio
async def test_resposta_sem_messages_vira_runtimeerror(meta_client_com_post_mockado):
    client, post = meta_client_com_post_mockado
    post.return_value = {"error": {"code": 131009}}
    with pytest.raises(RuntimeError):
        await client.send_interactive_carousel("5534999990000", "corpo", _cards(2))

@pytest.mark.asyncio
async def test_mock_registra_carrossel():
    from app.whatsapp.mock_provider import MockProvider  # use the real class name in mock_provider.py
    r = await MockProvider().send_interactive_carousel("5534999990000", "corpo", _cards(2))
    assert r["method"] == "send_interactive_carousel"
```

Build the `meta_client_com_post_mockado` fixture by copying how the existing interactive test builds its client.

- [ ] **Step 2: Run the tests and confirm they fail** with `AttributeError: ... send_interactive_carousel`.
- [ ] **Step 3: Implement.**
  - **`base.py`:** a concrete method that raises `NotImplementedError`, with a docstring, like `send_interactive_list`.
  - **`meta.py`:**

```python
    async def send_interactive_carousel(self, to: str, body: str, cards: list[dict]) -> dict:
        """Carrossel interativo: 2 a 10 cards com imagem, texto e botões de resposta.

        Mensagem de SESSÃO (sem template e sem catálogo) — doc da Meta
        "interactive-media-carousel-messages", conferida em 07/10/2026. A Meta exige
        o mesmo número de botões em todos os cards; validamos aqui porque um 400
        da Meta no meio do inbound custa a vitrine inteira.
        """
        if not 2 <= len(cards) <= 10:
            raise ValueError(f"send_interactive_carousel aceita de 2 a 10 cards, recebeu {len(cards)}")
        qtd = {len(c.get("buttons") or []) for c in cards}
        if len(qtd) != 1 or not 1 <= next(iter(qtd)) <= 2:
            raise ValueError("todos os cards precisam do mesmo número de botões (1 ou 2)")
        montados = []
        for i, c in enumerate(cards):
            texto = c.get("body") or ""
            if not c.get("image_url") or len(texto) > 160 or texto.count("\n") > 2:
                raise ValueError(f"card {i} inválido (imagem obrigatória, texto ≤160 e ≤2 quebras)")
            botoes = []
            for bid, titulo in c["buttons"]:
                if len(titulo) > 20:
                    raise ValueError(f"botão {bid!r} com título > 20 caracteres")
                botoes.append({"type": "quick_reply", "quick_reply": {"id": bid, "title": titulo}})
            montados.append({
                "card_index": i,
                "header": {"type": "image", "image": {"link": c["image_url"]}},
                "body": {"text": texto},
                "action": {"buttons": botoes},
            })
        result = await self._post({
            "messaging_product": "whatsapp",
            **_recipient_field(to),
            "type": "interactive",
            "interactive": {"type": "carousel", "body": {"text": body},
                            "action": {"cards": montados}},
        }, request_type="send_interactive_carousel")
        if not isinstance(result, dict) or "messages" not in result:
            raise RuntimeError(f"Meta send_interactive_carousel rejected (missing messages): {result!r}")
        return result
```

  - **`mock_provider.py`:** log via `_log_entry`, with the buttons converted to lists, and return `{"status": "mock_ok", "method": "send_interactive_carousel"}`.
- [ ] **Step 4: Run the tests and confirm they pass.** Also run `tests/test_valeria_meta_interactive_2026_09_29.py` and `tests/test_button_flow_provider_2026_08_20.py`; they should still pass.
- [ ] **Step 5: Commit** `git add backend/app/whatsapp/base.py backend/app/whatsapp/meta.py backend/app/whatsapp/mock_provider.py backend/tests/test_valeria_v2_carousel_provider.py && git commit -m "feat(whatsapp): send_interactive_carousel (carrossel de sessão da Meta)"`

---

### Task 2: Price table and card text (pure)

**Files:**
- Create: `backend/app/button_flow/valeria_tabela.py`
- Test: `backend/tests/test_valeria_v2_tabela.py`

`Card` comes from contract C1. If T4 hasn't landed yet, define the tests with a local `Card`-compatible stub via `types.SimpleNamespace(id=..., corpo=..., skus=..., exige_min_lot=...)`. The functions only read attributes.

The catalog fixture copies the 32 active rows from production (spec §4 / `products`):

```python
ATACADO = [
 ("Canastra Canela — Moído 250g","R$ 28,70"),("Canastra Clássico — Em Grãos 1kg","R$ 97,70"),
 ("Canastra Clássico — Em Grãos 250g","R$ 31,70"),("Canastra Clássico — Em Grãos 500g","R$ 54,70"),
 ("Canastra Clássico — Moído 250g","R$ 28,70"),("Canastra Clássico — Moído 500g","R$ 52,70"),
 ("Canastra Suave — Em Grãos 1kg","R$ 97,70"),("Canastra Suave — Em Grãos 250g","R$ 31,70"),
 ("Canastra Suave — Em Grãos 500g","R$ 54,70"),("Canastra Suave — Moído 250g","R$ 28,70"),
 ("Canastra Suave — Moído 500g","R$ 52,70"),("Cápsula Canastra Canela — Display 10 cápsulas","R$ 22,90"),
 ("Cápsula Canastra Clássico — Display 10 cápsulas","R$ 22,90"),("Drip Coffee Canastra Suave — Display 10 sachês","R$ 24,90"),
 ("Granel Canastra Clássico — 2kg em grãos","R$ 169,70"),("Granel Canastra Suave — 2kg em grãos","R$ 169,70"),
 ("Granel Néctar de Minas Espresso — 2kg em grãos","R$ 166,70"),("Granel Néctar de Minas Intenso — 2kg em grãos","R$ 166,70"),
 ("Microlote — Em Grãos 250g","R$ 32,70"),("Microlote — Moído 250g","R$ 32,70"),
 ("Moedor + 10 pacotes granel","R$ 599,00"),("Moedor Elétrico Profissional — Unitário","R$ 949,00"),
 ("Néctar de Minas Blend Arábica+Robusta — Em Grãos 1kg","R$ 79,70"),("Néctar de Minas Gourmet — Em Grãos 1kg","R$ 88,70"),
 ("Néctar de Minas Gourmet — Kit 10un 500g","R$ 357,00"),("Néctar de Minas Gourmet — Moído 500g","R$ 39,70"),
]
PL = [("Café Canastra 250g — c/ embalagem Canastra","R$ 26,70","100 un"),("Café Canastra 250g — embalagem do cliente","R$ 25,70","100 un"),
      ("Café Canastra 500g — c/ embalagem Canastra","R$ 48,70","100 un"),("Café Canastra 500g — embalagem do cliente","R$ 47,70","100 un"),
      ("Microlote 250g — c/ embalagem Canastra","R$ 29,70","100 un"),("Microlote 250g — embalagem do cliente","R$ 27,70","50 un")]
def produtos():
    return ([{"sector":"Atacado","name":n,"price_formatted":p,"min_lot":None,"is_active":True} for n,p in ATACADO]
          + [{"sector":"Private Label","name":n,"price_formatted":p,"min_lot":m,"is_active":True} for n,p,m in PL])
```

- [ ] **Step 1: Write the failing tests.**

```python
from types import SimpleNamespace as NS
from app.button_flow import valeria_tabela as t

def test_precos_filtra_setor_inativo_e_vazio():
    ps = produtos() + [{"sector":"Atacado","name":"X","price_formatted":"R$ 1,00","is_active":False,"min_lot":None},
                       {"sector":"Atacado","name":"Y","price_formatted":"","is_active":True,"min_lot":None}]
    p = t.precos_por_nome(ps, "Atacado")
    assert p["Canastra Clássico — Moído 250g"] == "R$ 28,70"
    assert "X" not in p and "Y" not in p and "Café Canastra 250g — embalagem do cliente" not in p

def test_card_resolve_precos_e_sai_dentro_do_limite():
    card = NS(id="classico", corpo="Clássico\n250g moído {preco:Canastra Clássico — Moído 250g}",
              skus=("Canastra Clássico — Moído 250g",), exige_min_lot=None)
    assert t.resolver_card(card, t.precos_por_nome(produtos(),"Atacado"), {}) == "Clássico\n250g moído R$ 28,70"

def test_card_some_se_sku_faltar():
    card = NS(id="x", corpo="{preco:Nao Existe}", skus=("Nao Existe",), exige_min_lot=None)
    assert t.resolver_card(card, t.precos_por_nome(produtos(),"Atacado"), {}) is None

def test_card_microlote_pl_some_enquanto_min_lot_for_50():
    card = NS(id="microlote", corpo="Microlote 250g {preco:Microlote 250g — c/ embalagem Canastra}",
              skus=("Microlote 250g — c/ embalagem Canastra","Microlote 250g — embalagem do cliente"), exige_min_lot="100 un")
    precos = t.precos_por_nome(produtos(), "Private Label"); lots = t.min_lots_por_nome(produtos(), "Private Label")
    assert t.resolver_card(card, precos, lots) is None   # "embalagem do cliente" ainda diz 50 un

def test_card_acima_de_160_ou_3_quebras_some():
    precos = t.precos_por_nome(produtos(),"Atacado")
    assert t.resolver_card(NS(id="a", corpo="x"*161, skus=(), exige_min_lot=None), precos, {}) is None
    assert t.resolver_card(NS(id="a", corpo="a\nb\nc\nd", skus=(), exige_min_lot=None), precos, {}) is None

def test_tabela_atacado_tem_linhas_e_regras():
    txt = t.tabela_atacado(t.precos_por_nome(produtos(),"Atacado"), regras="✅ pedido mínimo R$500")
    assert "Clássico" in txt and "R$ 28,70" in txt and "R$ 97,70" in txt
    assert "Granel" in txt and "R$ 84,85/kg" in txt     # 169,70 / 2, derivado, nunca escrito à mão
    assert txt.rstrip().endswith("✅ pedido mínimo R$500")

def test_tabela_omite_linha_de_sku_inativo():
    ps = [p for p in produtos() if not p["name"].startswith("Moedor")]
    assert "Moedor" not in t.tabela_atacado(t.precos_por_nome(ps,"Atacado"), regras="")

def test_tabela_vazia_devolve_none():
    assert t.tabela_atacado({}, regras="x") is None

def test_total_pl_e_como_funciona():
    precos = t.precos_por_nome(produtos(), "Private Label")
    assert t.total_pl(precos) == "R$ 2.670,00"
    assert "R$ 2.670,00" in t.como_funciona_pl(precos, "exemplo: 100 pacotes = {total_pl} + fotolito")
    assert t.como_funciona_pl({}, "x {total_pl}") is None
```

- [ ] **Step 2: Run the tests and confirm they fail** (module not found).
- [ ] **Step 3: Implement `valeria_tabela.py`.** Pure functions, no imports from `app` except typing.
  - **Price parsing:** `"R$ 169,70"` → `Decimal("169.70")`. Formatting is Brazilian: `R$ 2.670,00`, with a dot for thousands and a comma for decimals.
  - **`tabela_atacado` line groups**, declared in a module-level tuple, each line a `(label, [(format_label, sku_name), ...])`. Lines whose SKUs are all missing are omitted; missing SKUs inside a line are skipped.
    - `☕ Clássico · Suave` with sub-lines `250g moído X · grão Y`, `500g moído X · grão Y`, `1kg grão X`. Use the Clássico prices; if Clássico and Suave differ for a format, print both: `Clássico X · Suave Y`.
    - `☕ Canela  250g moído X`
    - `☕ Microlote  250g X` (use `Microlote — Moído 250g`; if grão differs, print both)
    - `☕ Néctar de Minas  Gourmet 1kg X · moído 500g Y · Blend 1kg Z`
    - `📦 Granel 2kg em grão  Clássico/Suave X (R$ W/kg) · Néctar Y`. W is computed as X/2 and formatted.
    - `☕ Cápsulas (10 un) X · Drip (10 sachês) Y`
    - `⚙️ Moedor profissional X · Moedor + 10 granel Y`
  - **Output order:** header `tabela atacado — preço por pacote 📋`, a blank line, the lines, a blank line, then `regras` as-is.
  - **`resolver_card`:** replace every `{preco:<name>}` using `precos`. If any marker or any `skus` entry is missing → None. If `exige_min_lot` is set and any sku's min_lot is not equal (after `.strip()`) → None. If the result is > 160 chars or has > 2 `\n` → None.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** `git add backend/app/button_flow/valeria_tabela.py backend/tests/test_valeria_v2_tabela.py && git commit -m "feat(valeria-v2): tabela de preços e texto de card gerados do catálogo"`

---

### Task 3: v2 classifier (+ shared LLM helpers)

**Files:**
- Create: `backend/app/button_flow/_llm_comum.py`, `backend/app/button_flow/valeria_classifier.py`
- Modify: `backend/app/button_flow/classifier.py`. Move `_budget_estourado`, `_contabilizar` and the timeout-wrapped model call into `_llm_comum.py`, re-export the old names from `classifier.py` so existing imports and patches keep working, and change no behavior.
- Test: `backend/tests/test_valeria_v2_classifier.py`
- Must stay green: `backend/tests/test_button_flow_classifier_2026_09_09.py`

- [ ] **Step 1: Read** `classifier.py` fully: how it calls `gemini_client.generate`, `_extrair_classe`, budget, `token_usage`, and env handling. Also read its test, to see how the model call is patched.
- [ ] **Step 2: Write the failing tests.** Patch the model call the same way the existing classifier test does, with the patch target being the function in `valeria_classifier` that calls the model.

```python
import pytest
from app.button_flow import valeria_classifier as vc

BOTOES = [("cafeteria","Cafeteria"),("loja","Loja ou empório"),("outro","Outro tipo")]
FAQS = {"preco":"pede preço/valor/tabela","frete":"pergunta sobre frete","minimo":"pedido mínimo"}

async def _cls(resposta_json, texto="x", **kw):
    # patch the model call to return `resposta_json` (str) — follow the existing classifier test's patch style
    ...

@pytest.mark.asyncio
@pytest.mark.parametrize("bruto,esperado", [
    ('{"classe":"BOTAO","botao_id":"cafeteria"}', vc.Classificacao("BOTAO","cafeteria",None)),
    ('{"classe":"FAQ","faq_id":"frete"}', vc.Classificacao("FAQ",None,"frete")),
    ('{"classe":"PERGUNTA"}', vc.Classificacao("PERGUNTA")),
    ('{"classe":"VENDEDOR"}', vc.Classificacao("VENDEDOR")),
    ('{"classe":"SAIR"}', vc.Classificacao("SAIR")),
    ('{"classe":"RUIDO"}', vc.Classificacao("RUIDO")),
])
async def test_classes_validas(bruto, esperado): ...

@pytest.mark.asyncio
@pytest.mark.parametrize("bruto", [
    '{"classe":"BOTAO","botao_id":"inventado"}',   # id fora da tela
    '{"classe":"FAQ","faq_id":"pagamento"}',        # faq fora do ramo
    '{"classe":"XPTO"}', 'não é json', '', None,
])
async def test_saida_invalida_vira_ruido(bruto): ...   # == vc.Classificacao("RUIDO")

async def test_timeout_vira_ruido(): ...        # model call raises asyncio.TimeoutError
async def test_excecao_vira_ruido(): ...        # model call raises RuntimeError
async def test_budget_estourado_vira_ruido_sem_chamar_modelo(): ...
async def test_contabiliza_token_usage_com_call_type_proprio(): ...  # call_type == "valeria_botoes_classify"
def test_prompt_cita_botoes_faqs_e_ultima_mensagem():
    p = vc.montar_prompt("tem frete grátis?", no_id="QA1", ramo="atacado", botoes=BOTOES, faqs=FAQS,
                         ultima_mensagem="que tipo de negócio você tem?")
    for trecho in ("cafeteria: Cafeteria", "frete: pergunta sobre frete", "que tipo de negócio", "tem frete grátis?"):
        assert trecho in p
def test_modelo_e_timeout_vem_do_env(monkeypatch):
    monkeypatch.setenv("VALERIA_CLASSIFIER_MODEL", "m-x"); monkeypatch.setenv("VALERIA_CLASSIFIER_TIMEOUT_S", "3")
    assert vc.modelo() == "m-x" and vc.timeout_segundos() == 3.0
```

- [ ] **Step 3: Run the tests and confirm they fail.**
- [ ] **Step 4: Implement.**
  - **`_llm_comum.py`:** the moved helpers, unchanged in behavior. `classifier.py` imports them back under the original names.
  - **`valeria_classifier.py`:**
    - `Classificacao`, `CLASSES`;
    - `modelo()`, from env `VALERIA_CLASSIFIER_MODEL`, default `"gemini-2.5-flash-lite"`;
    - `timeout_segundos()`, from env `VALERIA_CLASSIFIER_TIMEOUT_S`, default 12.0, invalid → default;
    - `montar_prompt(...)`;
    - `async classificar(...)`.
  - **Prompt** (Portuguese, compact): role "classifique a mensagem do lead numa etiqueta; NÃO responda ao lead"; the 6 classes with one-line definitions (spec §7.2); current screen buttons as `id: rótulo` lines; valid FAQ ids as `id: descrição` lines; `última mensagem enviada ao lead: ...`; `mensagem do lead: ...`. Output JSON only: `{"classe": ..., "botao_id": ..., "faq_id": ...}`. Few-shot examples from spec §7.3:
    - "tenho uma cafeteria" → BOTAO cafeteria
    - "uns 200 kgs" → BOTAO mais100 (when that id exists)
    - "qual o valor do quilo?" → FAQ preco
    - "tem frete grátis?" → FAQ frete
    - "vocês fazem café com açaí?" → PERGUNTA
    - "bom dia" → RUIDO
    - "quero falar com alguém" → VENDEDOR
    - "não quero mais" → SAIR
  - **Call:** `json_mode=True`, guarded by the budget and timeout helpers; contabilizes with `call_type="valeria_botoes_classify"`.
  - **Validation:** class not in CLASSES → RUIDO; BOTAO without a valid `botao_id` → RUIDO; FAQ without a valid `faq_id` → RUIDO.
  - Never raises: wrap everything in `try/except Exception` → RUIDO, logged at `warning`.
- [ ] **Step 5: Run the new tests and `tests/test_button_flow_classifier_2026_09_09.py`; both should pass.**
- [ ] **Step 6: Commit** `git add backend/app/button_flow/_llm_comum.py backend/app/button_flow/valeria_classifier.py backend/app/button_flow/classifier.py backend/tests/test_valeria_v2_classifier.py && git commit -m "feat(valeria-v2): classificador de texto livre (só etiqueta, nunca escreve)"`

---

### Task 4: v2 registry (data)

**Files:**
- Modify: `backend/app/button_flow/valeria_registry.py`. Add `Card` from C1 and `cards: tuple[Card, ...] = ()` as the LAST field of `No`, with a docstring note that `tela="carrossel"` is a v2 node. No other change.
- Create: `backend/app/button_flow/valeria_registry_v2.py`
- Test: `backend/tests/test_valeria_v2_registry.py`
- Must stay green: `backend/tests/test_valeria_registry_2026_09_29.py`, `backend/tests/test_valeria_content_2026_09_29.py`

- [ ] **Step 1: Write the failing tests** (`test_valeria_v2_registry.py`):

```python
from app.button_flow import valeria_registry as v1, valeria_registry_v2 as r
from app.button_flow.engine import normalizar

def _todos_botoes():
    for no in r.NOS.values():
        yield no, no.botoes

def test_rotulos_cabem_no_whatsapp():
    for no, bs in _todos_botoes():
        lim = v1.LIMITE_TITULO_LISTA if no.tela == "lista" else v1.LIMITE_ROTULO_BOTAO
        for b in bs: assert len(b.rotulo) <= lim, (no.id, b.id)
        if no.tela == "lista": assert len(bs) <= v1.MAX_LINHAS_LISTA
        else: assert len(bs) <= v1.MAX_BOTOES
        for c in no.cards: assert len(c.rotulo_botao) <= v1.LIMITE_ROTULO_BOTAO

def test_todo_destino_existe():
    especiais = {"tabela", "handoff", "regra:QP2"}
    for no, bs in _todos_botoes():
        for b in bs:
            d = b.destino
            assert d in r.NOS or d in r.TERMINAIS or d in especiais or d.startswith("faq:"), (no.id, b.id, d)
            if d.startswith("faq:"):
                ramo = r.RAMO_DO_NO[no.id]; assert d[4:] in r.FAQ[ramo]
        for c in no.cards: assert c.destino in r.NOS

def test_regra_qp2_cobre_criar_zero_menos_100():
    assert r.REGRA_QP2[("criar_zero", "menos100")] == "PL_ABAIXO"
    assert all(d in r.NOS or d in r.TERMINAIS for d in r.REGRA_QP2.values())

def test_mensagens_prontas_do_anuncio():
    assert r.MENSAGENS_PRONTAS[normalizar("Olá! Tenho um comércio e quero revender café especial.")] == "VA"
    assert r.MENSAGENS_PRONTAS[normalizar("Olá! Quero saber mais sobre compra por atacado.")] == "VA"
    assert r.MENSAGENS_PRONTAS[normalizar("Olá! Quero café com a minha marca — já tenho CNPJ")] == "VP"
    assert r.MENSAGENS_PRONTAS[normalizar("Olá! Quero saber mais sobre ter a Marca Própria de Café.")] == "VP"

def test_todo_no_alcancavel_a_partir_de_n0_ou_mensagem_pronta():
    vistos, fila = set(), ["N0", "VA", "VP"]
    while fila:
        n = fila.pop()
        if n in vistos or n not in r.NOS: continue
        vistos.add(n)
        for b in r.NOS[n].botoes:
            if b.destino in r.NOS: fila.append(b.destino)
        for c in r.NOS[n].cards: fila.append(c.destino)
        if any(b.destino == "regra:QP2" for b in r.NOS[n].botoes): fila.extend(r.REGRA_QP2.values())
    assert set(r.NOS) - vistos == set()

def test_vitrines_tem_cards_com_fotos_existentes_e_mesmo_numero_de_botoes():
    from pathlib import Path
    fotos = Path(v1.__file__).parent.parent / "photos"
    for vid in ("VA", "VP"):
        no = r.NOS[vid]; assert no.tela == "carrossel" and len(no.cards) >= 2
        for c in no.cards: assert (fotos / c.foto).exists(), c.foto

def test_microlote_pl_exige_min_lot_100():
    c = {c.id: c for c in r.NOS["VP"].cards}["microlote"]
    assert c.exige_min_lot == "100 un"

def test_nenhum_numero_pendente_no_texto():
    # Kit e Microlote PL estão pendentes (spec §4): nenhum "R$" no VK nem no card do microlote PL sem marcador
    assert "R$" not in r.NOS["VK"].corpo
    for c in r.NOS["VP"].cards:
        assert "R$" not in c.corpo   # preço só por {preco:...}

def test_fatos_confirmados_estao_nos_textos():
    assert "R$500" in r.REGRAS_ATACADO_DEFAULT and "R$2.000" in r.REGRAS_ATACADO_DEFAULT
    assert "15 dias úteis" in r.COMO_FUNCIONA_PL_DEFAULT and "R$100" in r.COMO_FUNCIONA_PL_DEFAULT
    assert "{total_pl}" in r.COMO_FUNCIONA_PL_DEFAULT
    assert r.FAQ["atacado"]["minimo"].count("R$500") == 1
```

- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement `valeria_registry_v2.py`** as pure data, following the v1 registry's style and module docstring conventions and citing the spec section for every text.
  - **Reuse** `Botao`, `No`, `Terminal`, `Card`, the TAG_* constants, `VENDEDOR_*`, `BOTOES_PRAZO` and `DIAS_POR_PRAZO` from v1 by import. Do not duplicate them.
  - **Nodes, texts and ids** come from spec §5.2 and contract C2.
  - **Card texts** (spec §6.1 and §6.2): `{preco:<exact products.name>}` markers only. Use `\n` for the two line breaks.
    - Atacado cards and skus:
      - `classico`: 5 Clássico SKUs;
      - `suave`: 5 Suave SKUs;
      - `microlote`: `Microlote — Moído 250g` and `Microlote — Em Grãos 250g`.
    - PL cards:
      - `embalagem_canastra`: the 250g and 500g "c/ embalagem Canastra" SKUs, foto `private_label/foto_3.jpg`;
      - `embalagem_cliente`: the "embalagem do cliente" 250g/500g SKUs, foto `private_label/foto_1.jpg`;
      - `microlote`: both Microlote PL SKUs, `exige_min_lot="100 un"`, foto `private_label/foto_4.jpg`.
    - Atacado photos: `atacado/foto_1_classico.jpg`, `atacado/foto_2_suave.jpg`, `atacado/foto_4_microlote.png`.
  - **Card text budget:** keep each card ≤ 160 chars after resolution. Prices are ~8 chars. Verify with T2's fixture if needed.
  - **VA / VP:**
    - `corpo` = the carousel body;
    - `botoes` = the 3 action buttons;
    - `cards` as above;
    - `ramo` = atacado / private_label.
  - **VK corpo:** `"temos um kit pra você provar nossos cafés antes do pedido 😊 o João te passa o valor e o frete pro seu CEP"`.
  - **VO:** `tela="botoes"`, `botoes=()`, corpo `"pode escrever sua pergunta 🙂"`. T5's engine treats VO specially.
  - **T_KIT:** `Terminal(id="T_KIT", vendedor=VENDEDOR_ATACADO, corpo="perfeito, já chamei o João Brás aqui pra combinar o kit com você 😊", tags=(TAG_QUALIFICADO, TAG_KIT), silenciar_ia=True, handoff=True)`, with `TAG_KIT = "Botões: Kit amostra"` defined in v2.
  - **Other terminals:** copy v1's T_* with the same fields (import and reuse the v1 objects).
- [ ] **Step 4: Run** the new tests, `tests/test_valeria_registry_2026_09_29.py` and `tests/test_valeria_content_2026_09_29.py`; all should pass.
- [ ] **Step 5: Commit** `git add backend/app/button_flow/valeria_registry.py backend/app/button_flow/valeria_registry_v2.py backend/tests/test_valeria_v2_registry.py && git commit -m "feat(valeria-v2): registry do fluxo v2 (vitrine, qualificação curta, dúvidas)"`

---

### Task 5: v2 engine (pure)

**Files:**
- Create: `backend/app/button_flow/valeria_engine_v2.py`
- Test: `backend/tests/test_valeria_v2_engine.py`
- Read: `valeria_engine.py` (v1). Reuse `_casar`, `_encerrado`, `FRASES_OPTOUT`, `Decisao`, `Efeitos`, `Mensagem`, `Clique` and `Texto` by import. Do NOT modify v1.

**Decision rules**, in this order. These are the spec, so implement exactly:

1. **`primeira_tela(texto)`:** `MENSAGENS_PRONTAS.get(normalizar(texto), "N0")`.
2. **`no_atual is None`** (first contact):
   - an opt-out phrase → `T_OPTOUT`;
   - otherwise go to `primeira_tela(texto)`;
   - if that is VA/VP: `vitrine="completa"`, `memoria={"ramo": RAMO_DO_NO[dest]}`;
   - if N0: normal node screen.
3. **Unknown node** (not in NOS and not in TERMINAIS) → `T_HUMANO`.
4. **Text events** (`Texto` or `TextoClassificado`) whose normalized `conteudo` is in `FRASES_OPTOUT` → `T_OPTOUT`, unless already there.
5. **Ended** (`_encerrado`) → `DecisaoV2(proximo_no=no_atual, ignorar=True)`.
6. **`Clique`:**
   - **Card click:** payload `card:<id>`, matched against the current node's `cards`:
     - go to `card.destino`;
     - `memoria={"interesse": id, "ruidos": 0}`;
     - in atacado, `criterios={"purchase_intent": "clear"}`;
     - `repasse_motivo` stays None.
   - **Otherwise match a button** with v1's `_casar`. Then route by `destino`:
     - **`faq:<x>`:** `faq=x`, `proximo_no=estado.get("retorno") or VITRINE_DO_RAMO[ramo]`. The return screen is resent without photo or carousel: if the return node is VA/VP, `vitrine="acoes"`; else it is the normal node screen with `marcar_nudge=False`.
     - **`tabela`:** `proximo_no=VITRINE_DO_RAMO[ramo]`, `vitrine="tabela"`.
     - **`handoff`:** `_ir_para(HANDOFF_DO_RAMO[ramo])`, with `repasse_motivo=f'clicou "{rotulo}"'`.
     - **`regra:QP2`:** `respostas = {**estado.get("respostas",{}), "QP2": botao.id}`; destination `REGRA_QP2.get((respostas.get("QP1"), botao.id), "T_HANDOFF_PL")`.
     - **Into `VD_A`/`VD_P`:** `memoria["retorno"] = no_atual`.
     - **Into VA/VP** (from N0 or C1): `vitrine="completa"`, `memoria["ramo"]`.
     - **Into any handoff terminal:** `repasse_motivo=f'clicou "{rotulo}"'`.
     - **Every click:** `memoria["respostas"] = {**old, no_atual: botao.id}` and `memoria["ruidos"]=0`. `criterios` = `botao.grava`. Atacado `pedido` adds `purchase_intent=clear`.
   - **Unmatched click** → treat as `RUIDO` (rule 7).
7. **`TextoClassificado`**, where `ramo = estado.get("ramo")`:
   - **`BOTAO` with an id of the current node:** exactly like the click on that button (rule 6). The id is already validated by the classifier, but re-check it.
   - **`FAQ`:**
     - `faq_id == "preco"`: if ramo in VITRINE_DO_RAMO → `proximo_no=VITRINE_DO_RAMO[ramo]`, `vitrine="tabela"`; if no ramo → `N0` normal screen.
     - other FAQ: `faq=faq_id`, `proximo_no=no_atual`; resend the current screen as in the `faq:` route (VA/VP → `vitrine="acoes"`).
     - `memoria["ruidos"]=0`.
   - **`PERGUNTA` / `VENDEDOR`:** if ramo has a handoff terminal → `_ir_para(HANDOFF_DO_RAMO[ramo])`, else `T_HUMANO`. `repasse_motivo = f"{classe}: {conteudo[:200]}"`.
   - **`SAIR`** → `T_OPTOUT`.
   - **`RUIDO`:** `r = estado.get("ruidos",0) + 1`.
     - `r < TETO_RUIDO` → nudge: `proximo_no=no_atual`, `mensagem=Mensagem(corpo=corpo_nudge or CORPO_NUDGE, botoes=no.botoes)`, `marcar_nudge=True`, `memoria={"ruidos": r}`. For VA/VP also set `vitrine="acoes"`.
     - Otherwise, handoff as in PERGUNTA, with `repasse_motivo="sem resposta a botões (2 mensagens não entendidas)"`.
   - **At node `VO`:** `BOTAO` is impossible (no buttons). `FAQ` → answer and return to `estado.get("retorno")`. Anything else except `SAIR` → handoff of the ramo with `repasse_motivo=f"PERGUNTA: {conteudo[:200]}"`.
8. **Plain `Texto`** (classifier not run) → same as `RUIDO`.

**Message bodies:** for node destinations, `mensagem=Mensagem(corpo=no.corpo, botoes=no.botoes)`; terminals are handled as in v1's `_ir_para`. Implement a local `_ir_para` that returns `DecisaoV2`, mirroring v1's.

- [ ] **Step 1: Write the failing tests.** One test per numbered rule and sub-rule above, against the real `valeria_registry_v2` (T4). At minimum:
  - `test_primeiro_contato_mensagem_pronta_atacado_vai_para_vitrine_completa`
  - `test_primeiro_contato_texto_qualquer_vai_para_n0`
  - `test_primeiro_contato_pare_vai_para_optout`
  - `test_clique_no_card_grava_interesse_e_vai_para_qa1_com_intencao`
  - `test_clique_pedido_vai_para_qa1_com_purchase_intent`
  - `test_qa2_vai_para_t_handoff_com_motivo`
  - `test_qp2_criar_zero_menos100_vai_para_pl_abaixo`
  - `test_qp2_tenho_marca_menos100_vai_para_handoff_pl`
  - `test_duvida_grava_retorno_e_faq_volta_com_acoes`
  - `test_faq_em_qa1_responde_e_reapresenta_qa1`
  - `test_classificado_preco_reenvia_tabela`
  - `test_classificado_botao_equivale_a_clique`
  - `test_pergunta_com_ramo_vai_para_handoff_do_ramo_com_texto`
  - `test_pergunta_sem_ramo_vai_para_humano`
  - `test_ruido_primeiro_nudge_segundo_handoff`
  - `test_ruido_zera_apos_clique`
  - `test_vo_pergunta_vai_para_handoff`
  - `test_vk_ver_precos_reenvia_tabela`
  - `test_vk_vendedor_handoff_do_ramo`
  - `test_terminal_encerrado_ignora`
  - `test_no_desconhecido_vai_para_humano`
  - `test_optout_vence_tudo`

  Build states as dicts, e.g. `{"flow": "valeria_botoes_v2", "node": "QA1", "ramo": "atacado", "nudges": 0}`, and events as `Clique(payload="pedido", titulo="Fazer pedido")` (check `engine.Clique`'s fields) or `TextoClassificado(...)`.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement** `valeria_engine_v2.py` per the rules. It is pure: no I/O and no clock.
- [ ] **Step 4: Run the tests and confirm they pass.** Also run `tests/test_valeria_engine_2026_09_29.py`, which must be unaffected.
- [ ] **Step 5: Commit** `git add backend/app/button_flow/valeria_engine_v2.py backend/tests/test_valeria_v2_engine.py && git commit -m "feat(valeria-v2): motor puro do fluxo v2"`

---

### Task 6: Kill switch, dispatch by flow, content API per flow

**Files:**
- Modify:
  - `backend/app/button_flow/config.py` (`_CHAVE_POR_FLUXO`)
  - `backend/app/button_flow/runner.py` (new `fluxo_efetivo`)
  - `backend/app/buffer/processor.py` (`_runner_do_fluxo` + the call at ~line 1704)
  - `backend/app/button_flow/valeria_content.py` (registry parameter where it reads `reg.*`)
  - `backend/app/button_flow/valeria_flow_router.py` (`flow_id` query/body, contract C7)
- Test: `backend/tests/test_valeria_v2_dispatch.py`, `backend/tests/test_valeria_v2_flow_router.py`
- Must stay green: `test_valeria_gate_2026_09_29.py`, `test_valeria_processor_2026_09_30.py`, `test_valeria_flow_router_2026_09_30.py`, `test_valeria_content_2026_09_29.py`, `test_valeria_content_terminais_2026_09_29.py`, `test_optout_colisao_button_flow.py`

Changes:

1. **`config._CHAVE_POR_FLUXO`:** add `"valeria_botoes_v2": "VALERIA_BOTOES_ENABLED"`.

2. **`runner.py`:**

```python
FLUXOS_VALERIA = frozenset({"valeria_botoes_v1", "valeria_botoes_v2"})

def fluxo_efetivo(conversation: dict, channel: dict) -> str | None:
    """O fluxo que atende ESTE inbound: o da conversa em andamento vence o do perfil.

    Trocar o perfil do canal de v1 para v2 (ou de volta) não pode reiniciar quem
    está no meio do atendimento: o `flow_state.flow` gravado é a memória de qual
    registry entende o `node` salvo. Só vale entre os fluxos da ValerIA, e só
    quando o perfil ainda aponta para UM deles (perfil desligado → None continua None).
    """
    fluxo = fluxo_da_conversa(conversation, channel)
    if fluxo not in FLUXOS_VALERIA:
        return fluxo
    estado = (conversation or {}).get("flow_state")
    gravado = estado.get("flow") if isinstance(estado, dict) else None
    if gravado in FLUXOS_VALERIA and gravado != fluxo and config.enabled(gravado):
        return gravado
    return fluxo
```

3. **`processor.py`:**
   - import `FLOW_ID as FLUXO_VALERIA_BOTOES_V2` from `valeria_registry_v2`;
   - import `processar_inbound as run_valeria_botoes_v2` from `app.button_flow.valeria_runner_v2`. T8 creates that module. Until it lands, create a stub file `valeria_runner_v2.py` containing only `async def processar_inbound(**kwargs): return None` plus a docstring "stub — substituído na Task 8", and commit it in this task;
   - in `_runner_do_fluxo`, add the `fluxo == FLUXO_VALERIA_BOTOES_V2` branch before the error log;
   - at the call site, use `_runner_do_fluxo(fluxo_efetivo(conversation, channel))`;
   - check every other use of `fluxo_da_conversa` in processor.py (lines ~1369–1388, `_optout_deterministico_cabe`) and keep its semantics, since "is any flow" stays true for v2.

4. **`valeria_content.py`:** functions that read `reg.NOS`, `reg.TERMINAIS` or `reg.CHAVE_*` get an optional `registry` keyword argument. The default is the v1 module, so existing calls are unchanged. `validar(node_id, payload, registry=...)` accepts v2's `CHAVES_TEXTO` keys and `card:<id>` (corpo only).

5. **`valeria_flow_router.py`** (contract C7):
   - `_registry(flow_id)` returns `valeria_registry` or `valeria_registry_v2`; any other value → HTTP 400;
   - `GET`/`PUT`/`DELETE` take `flow_id: str = Query("valeria_botoes_v1")`;
   - `AtivarRequest` gets `flow_id: str = "valeria_botoes_v1"`, written into the new profile's `flow_id`;
   - the channels endpoint includes the profile's `flow_id`;
   - for `card:<id>` PUT validation, resolve prices with `valeria_tabela.resolver_card` against the current catalog (`agent.catalog._fetch_active_products`) and reject with 422 if it returns None.

- [ ] **Step 1: Write the failing tests.**
  - **Dispatch:**
    - `fluxo_efetivo` returns `flow_state.flow` when it is a ValerIA flow, enabled, and different from the profile's;
    - it returns the profile's flow when `flow_state` is absent, from Recuperação, or corrupted;
    - a disabled profile → None;
    - `_runner_do_fluxo("valeria_botoes_v2") is processor.run_valeria_botoes_v2`;
    - `config.enabled("valeria_botoes_v2")` follows `VALERIA_BOTOES_ENABLED`.
  - **Router** (FastAPI TestClient, the same setup as `test_valeria_flow_router_2026_09_30.py`):
    - `GET ?flow_id=valeria_botoes_v2` returns VA with 3 `cards` and the `textos` list;
    - `PUT card:classico` with 161 chars → 422;
    - `PUT faq:atacado:frete` → 200;
    - unknown `flow_id` → 400;
    - `POST /activate` with `flow_id=valeria_botoes_v2` creates a profile with that `flow_id`;
    - the existing v1 calls without `flow_id` behave as before.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement** the changes above.
- [ ] **Step 4: Run** the new tests and every "must stay green" file listed above; all should pass.
- [ ] **Step 5: Commit** `git add` the 5 modified files, the stub `valeria_runner_v2.py` and the 2 test files, then `git commit -m "feat(valeria-v2): kill switch, despacho por flow_state e API do editor por flow_id"`

---

### Task 7: Frontend — version selector (v1/v2)

**Files:**
- Modify: `frontend/src/components/campaigns/valeria-flow-modal.tsx`, `valeria-flow-editor.tsx`, `valeria-flow-channels.tsx`, `valeria-flow-types.ts`, `valeria-flow-shared.ts`
- Test: the existing `*.test.tsx` next to them; add cases there.

Contract C7 is the API. Read the components and their tests first. They follow existing patterns, and per CLAUDE.md the App Router conventions differ from training data.

- [ ] **Step 1: Write failing vitest cases.**
  - The modal shows a segmented control "Versão: v1 · v2 (vitrine)" and, when v2 is chosen, fetches `/api/valeria-flow?flow_id=valeria_botoes_v2`.
  - The editor renders `cards` (one textarea per card, with a live counter "x/160", shown red over 160) and the `textos` list (regras, como funciona, each FAQ).
  - Saving a card PUTs `card:<id>?flow_id=valeria_botoes_v2`.
  - Activation sends `flow_id` and the channels list shows each channel's current `flow_id` as a badge ("v1"/"v2").
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/campaigns` and confirm the new cases fail.
- [ ] **Step 3: Implement**, reusing the existing editor components for corpo and label editing.
- [ ] **Step 4: Run** vitest for that folder and `npx tsc --noEmit -p .`; both should pass.
- [ ] **Step 5: Commit** only the frontend files: `git commit -m "feat(crm): editor da ValerIA escolhe v1/v2 e edita cards e textos da vitrine"`

---

### Task 8: v2 runner

**Files:**
- Create: `backend/app/button_flow/valeria_runner_v2.py`, replacing T6's stub
- Test: `backend/tests/test_valeria_v2_runner.py`
- Read fully first: `valeria_runner.py` (v1) and `tests/test_valeria_runner_2026_09_29.py`, for how provider, supabase and effects are mocked.

**Reuse from v1 by import, without copying:**
- `_reler_estado`, `_motivo_para_nao_rodar`, `_notificar_sem_rodar`, `_montar_evento`, `_e_robo_do_lead`;
- `_evidencia_do_turno`, `_rotulo_clicado`, `aplicar_criterios`, `_persistir_estado`;
- `url_publica_da_foto`, `_enviar_cartao`, `_cartao_do_terminal`, `CARTOES`, `_resolver`, `_persistir_mensagem`.

If a v1 helper hardcodes `reg.FLOW_ID` (`no_atual`, `proximo_estado`, `estado_inicial`), write the v2 equivalents locally against `valeria_registry_v2.FLOW_ID`.

**Turn flow** (`processar_inbound(**same kwargs as v1) -> str | None`, never raises):

1. Kill switch `config.enabled(r2.FLOW_ID)`.
2. Re-read the state, check `_motivo_para_nao_rodar` and robot detection exactly as v1 does.
3. Load content: `valeria_content.carregar(r2.FLOW_ID)` → apply to `r2.NOS`/`r2.TERMINAIS` using the `registry=` argument from T6. Also read the overrides for `CHAVES_TEXTO`, `card:<id>` corpo, `faq:<ramo>:<id>`, regras and como-funciona.
4. `no = no_atual_v2(estado)`. Build the event:
   - first contact → `Texto`;
   - otherwise, if the event is `Texto`, call `valeria_classifier.classificar(...)` with:
     - the current node's buttons; for VA/VP, the 3 action buttons plus card ids;
     - the FAQ dict for the ramo: `FAQ_DESCRICAO` filtered to `FAQ[ramo]` keys plus `"preco"`;
     - the last bot message (the last `messages` row with role assistant and sent_by `valeria_botoes` for this conversation; the v1 helper `_reler_estado` shows how to query);
   - then wrap the result into `TextoClassificado`;
   - a click stays a `Clique`.
5. `decisao = valeria_engine_v2.decidir(...)`; if `ignorar`, return.
6. `effects.aplicar(decisao.efeitos, ..., fluxo=effects.FLUXO_VALERIA)`; abort when it returns False, exactly as v1.
7. **Send**, in order:
   1. If `decisao.faq`: send the FAQ text, either the override `faq:<ramo>:<id>` or `r2.FAQ[ramo][id]`, resolving `{preco:...}` via `valeria_tabela`, as `send_text`.
   2. If the destination is VA or VP and `vitrine == "completa"`:
      - read the catalog once (`agent.catalog._fetch_active_products`, in `to_thread`);
      - **message 1, the carousel:** resolve each card with `resolver_card`, using the override corpo if present. With ≥2 cards → `send_interactive_carousel`, where each card's image is `url_publica_da_foto(card.foto)` and its button is `(f"card:{card.id}", card.rotulo_botao)`;
      - with <2 cards → `send_text` of the resolved card texts joined by blank lines;
      - if the carousel send raises → fallback: `send_interactive_buttons(body=node.corpo, buttons=action buttons, image_url=photo of the first card)`, logged at `error`, and then skip message 3, since the buttons already went;
      - **message 2:** atacado → `tabela_atacado(precos, regras)`; PL → `como_funciona_pl(precos, modelo)`;
      - if message 2 is None (catalog empty) → send `"nossa tabela tá sendo atualizada; o João te manda agora"`, switch the decision to the ramo's handoff terminal and go to step 7.4;
      - **message 3:** `send_interactive_buttons(CORPO_ACOES, action buttons)`.
   3. If `vitrine == "tabela"`: send messages 2 and 3. If `vitrine == "acoes"`: send message 3 only.
   4. Otherwise send the node or terminal screen exactly as v1's `_enviar` does, with no photo on `marcar_nudge` (VO / lists / buttons / terminals + card).
   5. Persist every outbound message to `messages` (`sent_by="valeria_botoes"`). For the carousel, save one row whose content is the body plus the card texts, with `message_type="interactive"`.
8. **Handoff note**, when `decisao.efeitos.handoff`: build the summary from spec §5.3 and append it via `append_lead_observation`:
   - ramo and interesse (card id → card label);
   - the score fields gathered (segment, monthly_volume_kg) from `flow_state.respostas` mapped to button labels;
   - which FAQs were asked (keep `flow_state.faqs` as a list, appended whenever `decisao.faq`);
   - the lead's free-text messages from this conversation (role user, not type button), up to the last 5, each ≤ 200 chars;
   - `decisao.repasse_motivo`.

   Also save it as a `system` message, so the seller sees it in the chat.
9. `aplicar_criterios` as in v1.
10. **New state:** `proximo_estado_v2(estado, decisao)` merges `decisao.memoria` (dicts are merged one level deep for `respostas`), sets `flow`, `node`, `nudges` and appends `faqs`. Then persist.

Also export, for T9:

```python
async def repassar_parado(*, lead: dict, conversation: dict, channel: dict, provider, horas: float) -> bool:
    """Repasse automático (spec §8): aplica o handoff do ramo como se o lead tivesse pedido.

    Devolve True só se ESTE chamador ganhou a trava (`flow_state.repasse_auto`).
    """
```

It runs:
- a conditional update of `conversations.flow_state`, done with PostgREST `.update(...).eq("id", ...).eq("flow_state->>node", node).is_("flow_state->>repasse_auto", "null")`. If PostgREST does not support this filter combination, use an RPC-free re-read-then-write and record the race in a docstring;
- `effects.aplicar` for the ramo's handoff terminal;
- sending the message `"vou deixar o João te chamando por aqui pra seguir com você 🙂"` + the seller card;
- the note with `repasse_motivo=f"automático — parado há {horas:.0f}h em {node}"`.

- [ ] **Step 1: Write the failing tests** with a fake provider (record calls), plus patches for supabase, effects, catalog, classifier and `url_publica_da_foto`. Cases:
  - first contact with the atacado ad message → carousel (3 cards) + table + action buttons, and state `{node: "VA", ramo: "atacado"}`;
  - first contact with "oi" → N0 list;
  - catalog without Microlote PL at `min_lot` 100 → the PL carousel has 2 cards;
  - catalog with only 1 atacado card resolvable → text instead of the carousel, then table + buttons;
  - carousel send raises → fallback buttons with image, and no third message;
  - empty catalog → "tabela sendo atualizada" + handoff;
  - text in QA1 classified `FAQ frete` → FAQ text then the QA1 screen again, with `faqs=["frete"]` in the state;
  - text classified `BOTAO cafeteria` in QA1 → QA2 screen, and the score criterion is saved;
  - text classified `PERGUNTA` in QA2 → T_HANDOFF corpo + card + note containing the lead's text;
  - 2× `RUIDO` → nudge then handoff;
  - a click goes through without calling the classifier;
  - the kill switch off does nothing;
  - `human_control` true → v1 motive, returned unchanged;
  - `repassar_parado`:
    - wins the lock → handoff + message + note;
    - loses the lock (the update affects 0 rows) → nothing is sent.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests plus `tests/test_valeria_runner_2026_09_29.py`, `tests/test_valeria_runner_gaps_2026_09_30.py` and `tests/test_valeria_v2_engine.py`; all should pass.
- [ ] **Step 5: Commit** `git add backend/app/button_flow/valeria_runner_v2.py backend/tests/test_valeria_v2_runner.py && git commit -m "feat(valeria-v2): runner — vitrine, texto livre classificado, nota de repasse"`

---

### Task 9: Stalled-lead sweep

**Files:**
- Create: `backend/app/button_flow/valeria_repasse.py`
- Modify: `backend/app/worker/main.py` (register `("valeria_repasse_parados", <type used for periodic jobs>, varrer, 600)`, following the existing table at ~line 82)
- Test: `backend/tests/test_valeria_v2_repasse.py`

`varrer()`:
- If `os.getenv("VALERIA_REPASSE_AUTO_ENABLED", "").strip().lower() not in ("1", "on", "true")`, return 0.
- **Selection** (spec §8): conversations on the NUMERO VALERIA channel, or more generally any conversation with `flow_state->>flow = 'valeria_botoes_v2'`, where:
  - `flow_state->>node` is in `NOS_COM_INTENCAO`;
  - `flow_state->>repasse_auto` is null;
  - `last_customer_message_at` is between now−22h and now−2h.
- Join the lead and skip it when `human_control` is true or `opt_out` is true.
- Paginate with `.range()` in pages of 200 (the PostgREST cap is 1000) and stop after 50 handoffs per run.
- For each conversation, resolve channel + provider the same way the follow-up worker does. Find how `follow_up` obtains a provider for a channel and reuse that function.
- Call `valeria_runner_v2.repassar_parado(...)`.
- Count the wins, log one summary line, and return the count.
- Never raise; log per-conversation failures.

- [ ] **Step 1: Write the failing tests:**
  - kill switch off → 0 and no DB call;
  - selects only the right nodes and time window (filters asserted on the fake query builder);
  - skips `human_control` and opt-out;
  - the 50 cap;
  - a conversation whose `repassar_parado` returns False is not counted;
  - an exception in one conversation doesn't stop the rest;
  - the worker registers the job with a 600 s interval.
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** `git add backend/app/button_flow/valeria_repasse.py backend/app/worker/main.py backend/tests/test_valeria_v2_repasse.py && git commit -m "feat(valeria-v2): repasse automático de quem mostrou intenção e parou"`

---

### Task 10: Integration check and report

- [ ] Run the full backend suite (command in the ground rules, without a file argument, with `-m 'not integration'`). Expected: the previous baseline (~4437 passed) + the new tests, with 0 failures. If there are failures, use superpowers:systematic-debugging and fix them before continuing.
- [ ] Run `cd frontend && npx vitest run && npx tsc --noEmit -p .`
- [ ] Use superpowers:requesting-code-review on the branch diff `master...HEAD`.
- [ ] Write the activation checklist (spec §10) into the final report for the user. Do NOT push, deploy, activate or send any real WhatsApp message: the user authorizes those.

---

## Self-review notes

- **Spec coverage:**
  - §5.1 → T4 + T5 rule 2.
  - §5.2 nodes → T4.
  - §5.3 note → T8 step 8.
  - §6 vitrine + degradation → T2 + T8 step 7.
  - §6.4 FAQ → T4 + T8.
  - §7 → T3 + T5 rule 7 + T8 step 4.
  - §8 → T8 `repassar_parado` + T9.
  - §9 table → T1–T9.
  - §10 rollout → T6 `fluxo_efetivo` + T10 checklist.
  - §11 tests → each task.
  - §12 measurement is post-launch and stays out of code scope.
- **Correction vs. spec §5.2:** `produto_interesse` is NOT a score criterion (`lead_score/model.CRITERIA_FIELDS` rejects unknown keys), so it lives in `flow_state.interesse` (T5 rule 6). Only `purchase_intent` goes to `criterios`.
- **Type names** used across tasks: `Card`, `No.cards`, `DecisaoV2`, `TextoClassificado`, `Classificacao`, `send_interactive_carousel`, `resolver_card`, `tabela_atacado`, `como_funciona_pl`, `fluxo_efetivo`, `repassar_parado`, `varrer`. They are consistent across C1–C7.
