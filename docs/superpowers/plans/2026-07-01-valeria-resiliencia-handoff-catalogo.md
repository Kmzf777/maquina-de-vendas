# Valéria — Resiliência, Handoff e Catálogo: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar resets de contexto, duplicação de mensagens, divergência de regras de negócio e falhas de handoff da IA Valéria, em três fases por risco (P0/P1/P2).

**Architecture:** Backend FastAPI + Redis + Supabase. As correções seguem os pontos de intervenção já mapeados na spec: montagem de histórico (`conversations/service.py`), re-coalescência (`buffer/processor.py`), ferramentas do agente (`agent/tools.py`), catálogo/preço (`agent/pricing.py`, `agent/catalog.py`, tabela `products`), handoff/SLA (`follow_up/*`, nova tabela `vendors`) e resposta vazia (`agent/orchestrator.py`).

**Tech Stack:** Python 3, FastAPI, `pytest` (asyncio_mode=auto), Supabase (supabase-py), Redis (redis.asyncio), Gemini via endpoint OpenAI-compat + `generateContent`.

## Global Constraints

- **Fluxo git:** branch local → `git pull origin master` → `git push origin <branch>:master` (push só com autorização do usuário). Sem PRs.
- **Redes:** dentro de container use nomes de serviço (`redis`, `db`, `api`); `127.0.0.1` só em `.env.local`. Código deve funcionar nos dois ambientes sem modificação.
- **WhatsApp:** foco exclusivo no fluxo Meta Graph API (`app/whatsapp/meta.py`, `app/webhook/meta_*`). Ignorar Evolution API.
- **Testes:** `pytest.ini` com `asyncio_mode = auto`. Fixtures em `backend/tests/conftest.py` (`FakeRedis`, `fake_redis`, `_stub_catalog` autouse). Rodar a partir de `backend/`.
- **Regra de negócio canônica de lote mínimo:** 100 unidades padrão; 50 unidades **apenas** no Microlote quando o cliente usa a própria embalagem (100 com embalagem Café Canastra).
- **Política de preço:** preço de tabela é firme — proibido "amaciar" ("por volta de", "na faixa de", "mais ou menos").
- **Destino de handoff hoje:** somente João está `enabled`. Arthur entra `enabled=false`. A IA nunca nomeia ao lead um vendedor que não fará o contato.

**Comando de teste padrão** (sempre a partir de `backend/`): `python -m pytest tests/<arquivo>::<teste> -v`

---

## Coordenação com o baseline pós-deploy (master, 2026-07-01)

Este plano foi rebaseado sobre `origin/master` **após** os deploys de hoje de "resiliência a BSUID" e "resiliência de LLM/observabilidade". A branch `att-valeria-outb` já foi sincronizada (fast-forward). O código-base agora contém `LLMUnavailableError`, `_create_with_retry` com retry 429/5xx e a identidade telefone-ou-BSUID. As restrições de isolamento abaixo são **obrigatórias** e estão embutidas nas tarefas afetadas:

- **`whatsapp/meta.py` está FORA do escopo de escrita (Task 10).** A série BSUID reescreveu `_post`/roteamento de destinatário. A idempotência de envio é implementada **inteiramente** em `buffer/processor.py` via `SETNX` no Redis; o `_post` e seu roteamento BSUID permanecem intocados.
- **`agent/orchestrator.py` (Task 7):** atuar **somente** em `_empty_fallback_text` (L94) e na sumarização de entrada dentro de `run_agent`. **Não tocar** `_create_with_retry` (L383), `class LLMUnavailableError` (L375) nem o ramo `except LLMUnavailableError`/`[AGENT FAILED]` do processor (L906/L924) — pertencem à iniciativa de resiliência de LLM já em produção.
- **`agent/tools.py` → `encaminhar_humano` (Task 13):** este handler é agora o alvo do **fallback automático** quando o LLM cai (o processor chama `execute_tool("encaminhar_humano", {"vendedor": "Joao Bras", ...})` em L906). A resolução via tabela `vendors` **deve recair no João** quando o segmento/stage do chamador não for claro (fallback `enabled`), preservando esse caminho.
- **`follow_up/service.py` (Task 9) e chave de buffer (Task 3):** preservar a compatibilidade BSUID. O rescue (`schedule_handoff_rescue`) e o cancelamento já operam por `is_bsuid`/`id_col`; a régua `_has_pending_buffered_inbound(phone, channel_id)` deve receber a **mesma identidade telefone-ou-BSUID** usada por `push_to_buffer` (`normalize_phone(from_number) or bsuid`), pois a chave `buffer:{phone}:{channel_id}` não mudou de formato.

**Line numbers de referência (código sincronizado):** `get_history` L288 · `enviar_fotos` L936 · `_has_newer_inbound` L1125 · `_has_pending_buffered_inbound` L1180 · `turn_watermark` L673 · `_empty_fallback_text` L94.

---

## FASE P0 — Hotfixes de baixo risco

### Task 1: Corrigir a janela do `get_history`

**Files:**
- Modify: `backend/app/conversations/service.py` (`get_history`, ~L288)
- Test: `backend/tests/test_get_history_window.py`

**Interfaces:**
- Consumes: `app.db.supabase.get_supabase()` (cliente já usado no módulo).
- Produces: `get_history(conversation_id: str, limit: int = 30) -> list[dict]` — **contrato inalterado**: retorna mensagens em ordem cronológica ascendente; muda apenas a janela (60 mais recentes em vez de 60 mais antigas).

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_get_history_window.py
from unittest.mock import MagicMock
import app.conversations.service as svc


class _FakeQuery:
    """Captura a cadeia de chamadas do supabase-py e devolve dados controlados."""
    def __init__(self, rows):
        self._rows = rows
        self.desc_used = None
        self.limit_used = None

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def order(self, _col, desc=False):
        self.desc_used = desc
        return self
    def limit(self, n):
        self.limit_used = n
        return self
    def execute(self):
        # Simula o DB devolvendo, na ordem pedida, a fatia dos dados.
        rows = list(reversed(self._rows)) if self.desc_used else list(self._rows)
        result = MagicMock()
        result.data = rows[: self.limit_used] if self.limit_used else rows
        return result


def test_get_history_returns_most_recent_in_chronological_order(monkeypatch):
    # 70 mensagens, created_at crescente "msg-00".."msg-69"
    all_rows = [{"role": "user", "content": f"m{i}", "created_at": f"2026-07-01T00:{i:02d}:00"} for i in range(70)]
    fake_q = _FakeQuery(all_rows)
    fake_sb = MagicMock()
    fake_sb.table.return_value = fake_q
    monkeypatch.setattr(svc, "get_supabase", lambda: fake_sb)

    out = svc.get_history("conv-1", limit=60)

    # Deve trazer as 60 MAIS RECENTES (m10..m69), em ordem CRONOLÓGICA (m10 primeiro).
    assert len(out) == 60
    assert out[0]["content"] == "m10"
    assert out[-1]["content"] == "m69"
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `python -m pytest tests/test_get_history_window.py -v`
Expected: FAIL — hoje `get_history` usa `desc=False` + `limit`, retornando m0..m59 (as mais antigas), então `out[0]["content"]` é `"m0"`.

- [ ] **Step 3: Implementar a correção**

Em `backend/app/conversations/service.py`, substituir o corpo de `get_history`:

```python
def get_history(conversation_id: str, limit: int = 30) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("role, content, stage, created_at, wamid, quoted_wamid, message_type, metadata, sent_by")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)   # 60 MAIS RECENTES
        .limit(limit)
        .execute()
    )
    rows = result.data or []
    rows.reverse()                        # volta à ordem cronológica ascendente (contrato inalterado)
    return rows
```

- [ ] **Step 4: Rodar o teste para confirmar que passa**

Run: `python -m pytest tests/test_get_history_window.py -v`
Expected: PASS

- [ ] **Step 5: Rodar a suíte que exercita histórico para garantir não-regressão**

Run: `python -m pytest tests/test_agent_tools.py tests/test_buffer.py -v`
Expected: PASS (nenhuma regressão)

- [ ] **Step 6: Commit**

```bash
git add backend/app/conversations/service.py backend/tests/test_get_history_window.py
git commit -m "fix(history): get_history retorna as 60 mensagens mais recentes (corrige reset de contexto em conversas longas)"
```

---

### Task 2: `enviar_fotos` aborta reenvio (idempotência de lote)

**Files:**
- Modify: `backend/app/agent/tools.py` (`enviar_fotos`, ~L936–968)
- Test: `backend/tests/test_enviar_fotos_idempotente.py`

**Interfaces:**
- Consumes: `get_history(lead_id, limit=100)`, `_deferred_media` (dict de módulo), `PHOTO_CAPTIONS`.
- Produces: comportamento de `execute_tool("enviar_fotos", ...)` — quando o marcador `[enviar_fotos]` já existe no histórico de sistema, **não re-enfileira** e retorna string de no-op.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_enviar_fotos_idempotente.py
import app.agent.tools as tools


def test_enviar_fotos_nao_reenfileira_quando_ja_enviado(monkeypatch):
    conv_id = "conv-1"
    lead_id = "lead-1"
    # Histórico já contém o marcador de fotos enviadas.
    monkeypatch.setattr(
        tools, "get_history",
        lambda *_a, **_k: [{"role": "system", "content": "[enviar_fotos] Fotos de atacado enviadas (5/5)"}],
    )
    # Garante fila limpa.
    tools._deferred_media.pop(conv_id, None)

    result = tools.execute_tool(
        "enviar_fotos", {"categoria": "atacado"},
        lead_id=lead_id, stage="atacado", conversation_id=conv_id,
    )

    # Não deve ter enfileirado nada.
    assert tools._deferred_media.get(conv_id) in (None, [])
    assert "ja" in result.lower() or "nao reenviar" in result.lower()
```

> Nota de execução: confira a assinatura real de `execute_tool` em `tools.py` (`get_tools_for_stage`/`execute_tool`) e ajuste os kwargs do teste para casar exatamente com os parâmetros esperados (`lead_id`, `stage`, `conversation_id`).

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `python -m pytest tests/test_enviar_fotos_idempotente.py -v`
Expected: FAIL — hoje `enviar_fotos` apenas loga o dedup e segue enfileirando o lote.

- [ ] **Step 3: Implementar o aborto antecipado**

Em `enviar_fotos`, trocar o bloco que só loga por um `return` antecipado (espelhando `enviar_foto_produto`):

```python
    elif tool_name == "enviar_fotos":
        history = get_history(lead_id, limit=100)
        system_messages = [m for m in history if m.get("role") == "system"]
        if any("[enviar_fotos]" in m.get("content", "") for m in system_messages):
            logger.info(
                "enviar_fotos: fotos de %s ja enviadas para lead %s — nao reenviar",
                args.get("categoria"), lead_id,
            )
            return "fotos ja enviadas nesta conversa — nao reenviar"

        categoria = args["categoria"]
        # ... (restante inalterado: glob, captions, enfileiramento em _deferred_media, save_message)
```

- [ ] **Step 4: Rodar o teste para confirmar que passa**

Run: `python -m pytest tests/test_enviar_fotos_idempotente.py -v`
Expected: PASS

- [ ] **Step 5: Rodar os testes de tools para não-regressão**

Run: `python -m pytest tests/test_agent_tools.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/tools.py backend/tests/test_enviar_fotos_idempotente.py
git commit -m "fix(fotos): enviar_fotos aborta reenvio do lote (elimina fotos duplicadas)"
```

---

### Task 3: Desempate de timestamp na re-coalescência

**Files:**
- Modify: `backend/app/buffer/processor.py` (`_has_newer_inbound`, **L1125** no código sincronizado)
- Test: `backend/tests/test_recoalesce_timestamp_tie.py`

> **Mitigação (obrigatório):** `processor.py` também contém o tratamento de `LLMUnavailableError` (L906) e o ramo `[AGENT FAILED]` (L924) — **NÃO tocar**. Editar apenas `_has_newer_inbound` e seus dois call sites. A `_has_pending_buffered_inbound(phone, channel_id)` (L1180) deve receber a identidade **telefone-ou-BSUID** usada por `push_to_buffer` (`normalize_phone(from_number) or bsuid`); a chave `buffer:{phone}:{channel_id}` não mudou de formato.

**Interfaces:**
- Consumes: `get_supabase()`.
- Produces: `_has_newer_inbound(conversation_id: str, watermark: dict | None) -> bool` — **assinatura muda**: o segundo argumento passa a ser o dict da mensagem-âncora (contendo `created_at` e `id`) em vez de só a string `created_at`, para permitir desempate por `id`. Fail-open mantido.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_recoalesce_timestamp_tie.py
from unittest.mock import MagicMock
import app.buffer.processor as proc


class _FakeMsgQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def gt(self, col, val): self._filters.append(("gt", col, val)); return self
    def or_(self, expr): self._filters.append(("or", expr)); return self
    def limit(self, _n): return self
    def execute(self):
        # Reproduz o desempate: "mais nova" = created_at > wm OU (created_at == wm E id > wm_id).
        res = MagicMock()
        res.data = self._rows
        return res


def test_timestamp_tie_is_resolved_by_id(monkeypatch):
    # msg irmã tem MESMO created_at do watermark, mas id maior → deve contar como mais nova.
    sibling = {"id": "id-002"}
    fake_q = _FakeMsgQuery([sibling])
    fake_sb = MagicMock()
    fake_sb.table.return_value = fake_q
    monkeypatch.setattr(proc, "get_supabase", lambda: fake_sb)

    watermark = {"created_at": "2026-07-01T00:00:00", "id": "id-001"}
    assert proc._has_newer_inbound("conv-1", watermark) is True


def test_no_newer_inbound_returns_false(monkeypatch):
    fake_q = _FakeMsgQuery([])  # nada mais novo
    fake_sb = MagicMock()
    fake_sb.table.return_value = fake_q
    monkeypatch.setattr(proc, "get_supabase", lambda: fake_sb)

    watermark = {"created_at": "2026-07-01T00:00:00", "id": "id-001"}
    assert proc._has_newer_inbound("conv-1", watermark) is False
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `python -m pytest tests/test_recoalesce_timestamp_tie.py -v`
Expected: FAIL — hoje `_has_newer_inbound` recebe uma string e usa só `.gt("created_at")` estrito; a assinatura com dict e o desempate por `id` não existem.

- [ ] **Step 3: Implementar o desempate**

Substituir `_has_newer_inbound`:

```python
def _has_newer_inbound(conversation_id: str, watermark: dict | None) -> bool:
    """True se há inbound (role='user') mais novo que a mensagem-âncora deste turno.

    Desempate: 'mais novo' = created_at > wm.created_at OU (created_at == wm.created_at E id > wm.id).
    Corrige o vetor de duplicação por COLISÃO de timestamp (dois workers respondendo).
    Fail-open: sem watermark ou erro → False (nunca aborta às cegas).
    """
    if not watermark or not watermark.get("created_at"):
        return False
    wm_created = watermark["created_at"]
    wm_id = watermark.get("id") or ""
    try:
        sb = get_supabase()
        result = (
            sb.table("messages")
            .select("id")
            .eq("conversation_id", conversation_id)
            .eq("role", "user")
            # created_at > wm  OU  (created_at == wm  E  id > wm_id)
            .or_(f"created_at.gt.{wm_created},and(created_at.eq.{wm_created},id.gt.{wm_id})")
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception as exc:
        logger.warning(
            "[RECOALESCE] falha ao checar inbound mais novo p/ conv %s: %s — fail-open (não aborta)",
            conversation_id, exc,
        )
        return False
```

- [ ] **Step 4: Atualizar os dois call sites para passar o dict-âncora**

Nos dois pontos que chamam `_has_newer_inbound` (aquisição do lock ~L800 e in-flight entre bolhas ~L897), passar o dict da mensagem salva em vez de `turn_watermark` string. Localizar `turn_watermark = _saved_user.get("created_at")` (~L596) e trocar por:

```python
    turn_watermark = {"id": _saved_user.get("id"), "created_at": _saved_user.get("created_at")}
```

Garantir que `_saved_user` inclui `id` (a inserção de `save_message` deve retornar `id`; se não retornar, ajustar o `select` do insert para incluir `id`).

- [ ] **Step 5: Rodar teste + suíte de buffer para não-regressão**

Run: `python -m pytest tests/test_recoalesce_timestamp_tie.py tests/test_buffer.py tests/test_buffer_manager.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/buffer/processor.py backend/tests/test_recoalesce_timestamp_tie.py
git commit -m "fix(recoalesce): desempate por id em colisao de timestamp (evita turno duplicado)"
```

---

### Task 4: Política de preço firme + alinhar valor de lote mínimo no prompt

**Files:**
- Modify: `backend/app/agent/prompts/valeria_inbound/atacado.py`
- Modify: `backend/app/agent/prompts/base.py`
- Test: `backend/tests/test_base_prompt.py` (estender)

**Interfaces:**
- Consumes: strings de prompt (constantes `ATACADO_PROMPT`, `build_base_prompt`).
- Produces: prompts sem obrigação de "amaciar" preço; lote mínimo referenciando a autoridade do catálogo.

- [ ] **Step 1: Escrever o teste que falha**

```python
# adicionar em backend/tests/test_base_prompt.py
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
from app.agent.prompts.base import build_base_prompt


def test_atacado_nao_obriga_amaciar_preco():
    txt = ATACADO_PROMPT.lower()
    # Política de preço firme: não deve MANDAR usar suavizadores.
    for softener in ["por volta de", "na faixa de", "em torno de", "mais ou menos"]:
        assert f'"{softener}"' not in txt, f"prompt ainda obriga amaciar: {softener}"


def test_base_nao_crava_lote_hardcoded():
    # base não deve cravar "100 unidades" como número fixo (autoridade é o catálogo).
    txt = build_base_prompt(stage="atacado", prompt_key="valeria_inbound").lower()
    assert "100 unidades" not in txt
```

> Nota: confira a assinatura real de `build_base_prompt` (parâmetros) antes de rodar; ajuste os kwargs do teste conforme a função exige.

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `python -m pytest tests/test_base_prompt.py::test_atacado_nao_obriga_amaciar_preco tests/test_base_prompt.py::test_base_nao_crava_lote_hardcoded -v`
Expected: FAIL

- [ ] **Step 3: Editar os prompts**

Em `valeria_inbound/atacado.py`: remover a seção que obriga qualificadores de preço ("por volta de" etc.) e substituir por instrução de preço firme coerente com o bloco `<catalogo_de_produtos>` ("cite o preço de tabela diretamente, sem suavizar"). Em `base.py`: substituir as ocorrências de "100 unidades"/preços hardcoded por remissão ao catálogo ("o lote mínimo e os preços seguem estritamente o `<catalogo_de_produtos>`").

- [ ] **Step 4: Rodar para confirmar que passa**

Run: `python -m pytest tests/test_base_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts/valeria_inbound/atacado.py backend/app/agent/prompts/base.py backend/tests/test_base_prompt.py
git commit -m "fix(prompt): preco firme (sem amaciar) e lote minimo delegado ao catalogo"
```

---

## FASE P1 — Robustez estrutural

### Task 5: Lote mínimo estruturado na tabela `products` (migração)

**Files:**
- Create: `backend/migrations/2026XXXX_products_min_lot_structured.sql`

**Interfaces:**
- Produces: colunas `min_lot_qty int` e `min_lot_packaging_rule jsonb` na tabela `public.products`.

- [ ] **Step 1: Escrever a migração**

```sql
-- backend/migrations/2026XXXX_products_min_lot_structured.sql
-- Lote mínimo estruturado e validável. Substitui o uso de min_lot (texto livre)
-- como autoridade. min_lot_qty = quantidade padrão (ex.: 100). min_lot_packaging_rule
-- modela a exceção do Microlote: {"cliente_embalagem": 50, "canastra_embalagem": 100}.
ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS min_lot_qty integer,
    ADD COLUMN IF NOT EXISTS min_lot_packaging_rule jsonb;

COMMENT ON COLUMN public.products.min_lot_qty IS 'Lote minimo padrao em unidades (autoridade).';
COMMENT ON COLUMN public.products.min_lot_packaging_rule IS 'Excecao condicional por embalagem, ex.: {"cliente_embalagem":50,"canastra_embalagem":100}.';

-- Backfill conservador: onde houver texto "100" em min_lot, semear 100.
UPDATE public.products
   SET min_lot_qty = 100
 WHERE min_lot_qty IS NULL AND (min_lot IS NULL OR min_lot ILIKE '%100%');
```

- [ ] **Step 2: Aplicar em homolog e recarregar o cache do PostgREST**

Aplicar via MCP `supabase-homolog` (`apply_migration`) OU pelo painel. Depois **recarregar o schema cache** (necessário para supabase-py enxergar as colunas novas):

```sql
NOTIFY pgrst, 'reload schema';
```

- [ ] **Step 3: Verificar as colunas**

Confirmar via `list_tables`/`execute_sql` que `min_lot_qty` e `min_lot_packaging_rule` existem em `products`.

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/2026XXXX_products_min_lot_structured.sql
git commit -m "feat(db): lote minimo estruturado (min_lot_qty + min_lot_packaging_rule) em products"
```

---

### Task 6: Validação de lote mínimo no cálculo de orçamento

**Files:**
- Modify: `backend/app/agent/pricing.py`
- Modify: `backend/app/agent/catalog.py`
- Test: `backend/tests/test_min_lot_validation.py`

**Interfaces:**
- Consumes: linhas de `products` com `min_lot_qty` e `min_lot_packaging_rule`.
- Produces: `validate_min_lot(qty: int, product: dict, cliente_embalagem: bool = False) -> tuple[bool, int]` — retorna `(ok, minimo_aplicavel)`. `minimo_aplicavel` = 50 se `cliente_embalagem` e a regra permitir, senão `min_lot_qty` (default 100).

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_min_lot_validation.py
from app.agent.pricing import validate_min_lot


def test_min_lot_default_100():
    prod = {"min_lot_qty": 100, "min_lot_packaging_rule": {"cliente_embalagem": 50, "canastra_embalagem": 100}}
    ok, minimo = validate_min_lot(80, prod, cliente_embalagem=False)
    assert minimo == 100 and ok is False


def test_min_lot_microlote_cliente_embalagem_50():
    prod = {"min_lot_qty": 100, "min_lot_packaging_rule": {"cliente_embalagem": 50, "canastra_embalagem": 100}}
    ok, minimo = validate_min_lot(60, prod, cliente_embalagem=True)
    assert minimo == 50 and ok is True


def test_min_lot_sem_regra_usa_qty():
    prod = {"min_lot_qty": 100, "min_lot_packaging_rule": None}
    ok, minimo = validate_min_lot(120, prod, cliente_embalagem=True)
    assert minimo == 100 and ok is True
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `python -m pytest tests/test_min_lot_validation.py -v`
Expected: FAIL — `validate_min_lot` não existe.

- [ ] **Step 3: Implementar `validate_min_lot`**

Em `backend/app/agent/pricing.py`:

```python
def validate_min_lot(qty: int, product: dict, cliente_embalagem: bool = False) -> tuple[bool, int]:
    """Valida a quantidade contra o lote mínimo estruturado do produto.

    Retorna (ok, minimo_aplicavel). Regra: 50 unidades SOMENTE quando o cliente usa a
    própria embalagem E a regra do produto o permite; caso contrário min_lot_qty (default 100).
    """
    default_qty = int(product.get("min_lot_qty") or 100)
    rule = product.get("min_lot_packaging_rule") or {}
    if cliente_embalagem and isinstance(rule, dict) and rule.get("cliente_embalagem"):
        minimo = int(rule["cliente_embalagem"])
    else:
        minimo = default_qty
    return (qty >= minimo, minimo)
```

Em `catalog.py`, ajustar `_format_products` para renderizar `min_lot_qty` (e a nota da exceção quando `min_lot_packaging_rule` existir) no lugar do `min_lot` de texto livre.

- [ ] **Step 4: Rodar para confirmar que passa**

Run: `python -m pytest tests/test_min_lot_validation.py tests/test_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/pricing.py backend/app/agent/catalog.py backend/tests/test_min_lot_validation.py
git commit -m "feat(pricing): validate_min_lot com regra condicional 50/100; catalogo renderiza lote estruturado"
```

---

### Task 7: Retomada contextual no fallback de resposta vazia + condensação de narrativa longa

**Files:**
- Modify: `backend/app/agent/orchestrator.py` (`_empty_fallback_text` **L94**; sumarização na entrada de `run_agent`)
- Test: `backend/tests/test_empty_response_recovery.py`

> **Mitigação (obrigatório):** atuar **somente** no caminho de resposta vazia genuína. **NÃO tocar** `_create_with_retry` (L383), `class LLMUnavailableError` (L375) nem o ramo de LLM-down — pertencem à resiliência de LLM já em produção. Esta task apenas estende `_empty_fallback_text` e adiciona a condensação de narrativa na montagem de entrada do `run_agent`.

**Interfaces:**
- Consumes: `_STAGE_TRANSITION_FALLBACKS`, dossiê/último assunto derivável do histórico.
- Produces: `_empty_fallback_text(media_tool_used, transitioned_to_stage=None, last_topic=None) -> str` — quando `last_topic` existe e não há transição/mídia, retorna uma retomada que cita o assunto em vez do genérico "me embolei".

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_empty_response_recovery.py
from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_GENERIC


def test_retomada_cita_ultimo_assunto():
    out = _empty_fallback_text(media_tool_used=False, transitioned_to_stage=None, last_topic="café pro seu restaurante")
    assert "café pro seu restaurante" in out
    assert out != _SAFETY_FALLBACK_GENERIC


def test_sem_assunto_cai_no_generico():
    out = _empty_fallback_text(media_tool_used=False, transitioned_to_stage=None, last_topic=None)
    assert out == _SAFETY_FALLBACK_GENERIC


def test_transicao_tem_prioridade_sobre_retomada():
    out = _empty_fallback_text(media_tool_used=False, transitioned_to_stage="atacado", last_topic="qualquer coisa")
    assert "revender" in out.lower() or "estabelecimento" in out.lower()
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `python -m pytest tests/test_empty_response_recovery.py -v`
Expected: FAIL — `_empty_fallback_text` não aceita `last_topic`.

- [ ] **Step 3: Implementar**

Estender `_empty_fallback_text` mantendo a ordem de prioridade (transição > mídia > retomada > genérico):

```python
def _empty_fallback_text(media_tool_used: bool, transitioned_to_stage: str | None = None,
                         last_topic: str | None = None) -> str:
    if transitioned_to_stage and transitioned_to_stage in _STAGE_TRANSITION_FALLBACKS:
        return _STAGE_TRANSITION_FALLBACKS[transitioned_to_stage]
    if media_tool_used:
        return _SAFETY_FALLBACK_MEDIA
    if last_topic:
        return f"sobre {last_topic}\n\nme repete só a parte final que eu já sigo com você"
    return _SAFETY_FALLBACK_GENERIC
```

No call site (~L908), derivar `last_topic` do histórico/dossiê (ex.: última pergunta em aberto ou segmento ativo) e passá-lo. Adicionar a condensação de narrativa longa: quando o texto do usuário exceder um limiar (ex.: 1200 chars), gerar uma versão condensada antes de compor o turno (reaproveitar o cliente LLM já instanciado; função `_condense_long_message(text) -> str` com fallback ao texto original em erro).

- [ ] **Step 4: Rodar para confirmar que passa**

Run: `python -m pytest tests/test_empty_response_recovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/orchestrator.py backend/tests/test_empty_response_recovery.py
git commit -m "fix(fallback): retomada contextual sem reset generico + condensacao de narrativa longa"
```

---

### Task 8: Captura estruturada de CNPJ/intenção + briefing enriquecido

**Files:**
- Modify: `backend/app/agent/tools.py` (nova tool `salvar_dados_pedido`)
- Modify: `backend/app/agent/summary.py`
- Test: `backend/tests/test_agent_summary.py` (estender)

**Interfaces:**
- Produces: tool `salvar_dados_pedido(cnpj: str | None, intencao: str | None)` que persiste em `lead.metadata`/campos; `generate_qualification_summary` inclui CNPJ no briefing.

- [ ] **Step 1: Escrever o teste que falha**

```python
# adicionar em backend/tests/test_agent_summary.py
from app.agent.summary import generate_qualification_summary


def test_summary_inclui_cnpj(monkeypatch):
    lead = {"name": "Maycon", "metadata": {"cnpj": "12.345.678/0001-90", "intencao": "grão verde 300kg"}}
    # mockar a chamada LLM interna para retornar um corpo previsível...
    # (seguir o padrão de mock já usado nos demais testes deste arquivo)
    summary = generate_qualification_summary(lead=lead, history=[], stage="exportacao")
    assert "12.345.678/0001-90" in summary
```

> Nota: siga o padrão de mock de LLM já existente em `test_agent_summary.py`.

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `python -m pytest tests/test_agent_summary.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar**

Adicionar a tool `salvar_dados_pedido` ao `TOOLS_SCHEMA` e ao `execute_tool` (persistindo `cnpj`/`intencao` em `lead.metadata` via `update_lead`). Em `summary.py`, incluir o CNPJ (de `lead.metadata`) no cabeçalho do briefing "NOVO LEAD QUALIFICADO".

- [ ] **Step 4: Rodar para confirmar que passa**

Run: `python -m pytest tests/test_agent_summary.py tests/test_agent_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/app/agent/summary.py backend/tests/test_agent_summary.py
git commit -m "feat(handoff): captura estruturada de CNPJ/intencao e briefing enriquecido"
```

---

### Task 9: Guards de SLA do handoff (confirmação imediata, retry 4xx, canal órfão)

**Files:**
- Modify: `backend/app/follow_up/service.py`, `backend/app/follow_up/scheduler.py`
- Test: `backend/tests/test_handoff_sla_guards.py`

> **Mitigação (obrigatório):** `follow_up/service.py` é agora BSUID-aware (`is_bsuid`/`id_col` no cancelamento; rescue keyed por telefone-ou-BSUID). Preservar essa compatibilidade: os novos guards **não** podem assumir que a identidade é sempre telefone. Editar `schedule_handoff_rescue` (L257) / `_clamp_to_business_window` (L31) sem regredir o caminho BSUID.

**Interfaces:**
- Produces: (a) confirmação imediata desacoplada da janela comercial para o 1º toque; (b) `_process_handoff_rescue` faz retry/alerta em 4xx em vez de cancelar em silêncio; (c) guard de canal órfão em `encaminhar_humano` que emite alerta quando não há canal ativo.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_handoff_sla_guards.py
import app.follow_up.scheduler as sched


def test_rescue_4xx_agenda_retry_ou_alerta(monkeypatch):
    # Simula erro Meta 4xx no envio do template e verifica que NÃO cancela silenciosamente:
    # ou reagenda, ou marca alerta (assert sobre o efeito observável do seu design).
    ...
```

> Nota: modele os mocks a partir do padrão de `test_broadcast_worker.py`/testes de follow-up existentes; o teste deve travar o comportamento novo (retry/alerta) contra o cancelamento silencioso atual em `scheduler.py:773-779`.

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `python -m pytest tests/test_handoff_sla_guards.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar**

(a) Em `encaminhar_humano`/rescue, enviar imediatamente a confirmação do 1º toque sem passar pelo `_clamp_to_business_window`. (b) Em `_process_handoff_rescue`, em erro 4xx, distinguir erro recuperável (reagendar com backoff) de definitivo (marcar `metadata.sla_alert=true` + log de alerta) em vez de `_cancel_job` cego. (c) Em `encaminhar_humano`, quando `get_channel_for_lead` vier vazio, não marcar o lead como resolvido silenciosamente — registrar alerta para intervenção humana.

- [ ] **Step 4: Rodar para confirmar que passa**

Run: `python -m pytest tests/test_handoff_sla_guards.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/follow_up/service.py backend/app/follow_up/scheduler.py backend/tests/test_handoff_sla_guards.py
git commit -m "fix(sla): confirmacao imediata, retry/alerta em 4xx e guard de canal orfao no handoff"
```

---

### Task 10: Guard de idempotência de envio (camada de aplicação)

**Files:**
- Modify: `backend/app/buffer/processor.py` (ponto de envio de bolha/mídia)
- Test: `backend/tests/test_send_idempotency.py`
- **NÃO tocar `backend/app/whatsapp/meta.py`** (mitigação): a série BSUID reescreveu `_post`/roteamento de destinatário; a idempotência vive 100% no processor. O hash da mídia deve considerar o alvo resolvido (que pode ser BSUID via `resolve_send_target`), mas o guard NÃO altera o `_post`.

**Interfaces:**
- Produces: `_already_sent(conversation_id: str, payload_hash: str) -> bool` via Redis `SETNX seen_send:{conversation_id}:{hash}` TTL curto (ex.: 30s). Antes de enviar uma bolha/mídia, calcula o hash e pula se já enviado.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_send_idempotency.py
import hashlib
import app.buffer.processor as proc


async def test_second_identical_send_is_skipped(fake_redis, monkeypatch):
    monkeypatch.setattr(proc, "_get_buffer_redis", lambda: fake_redis, raising=False)
    conv = "conv-1"
    h = hashlib.sha256("olá".encode()).hexdigest()
    first = await proc._already_sent(conv, h)
    second = await proc._already_sent(conv, h)
    assert first is False   # primeira vez: não visto → envia
    assert second is True    # segunda vez: já visto → pula
```

> Nota: ajuste `_get_buffer_redis` ao acessor real do cliente Redis no processor.

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `python -m pytest tests/test_send_idempotency.py -v`
Expected: FAIL — `_already_sent` não existe.

- [ ] **Step 3: Implementar**

```python
async def _already_sent(conversation_id: str, payload_hash: str, ttl: int = 30) -> bool:
    """True se esta bolha/mídia idêntica já foi enviada nesta conversa na janela `ttl`.
    Usa SETNX: retorna False na 1ª vez (e marca), True nas repetições. Fail-open → False."""
    try:
        r = _get_buffer_redis()
        key = f"seen_send:{conversation_id}:{payload_hash}"
        was_set = await r.set(key, "1", ex=ttl, nx=True)
        return was_set is None  # None = já existia → já enviado
    except Exception:
        return False
```

Envolver o envio de cada bolha de texto e de cada mídia com esse guard (hash do texto ou do `b64`/caption).

- [ ] **Step 4: Rodar para confirmar que passa**

Run: `python -m pytest tests/test_send_idempotency.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/buffer/processor.py backend/tests/test_send_idempotency.py
git commit -m "fix(envio): guard de idempotencia (SETNX) evita bolha/foto duplicada no retry"
```

---

## FASE P2 — Novas capacidades

### Task 11: Tabela `vendors` (migração + seed)

**Files:**
- Create: `backend/migrations/2026XXXX_vendors_table.sql`

**Interfaces:**
- Produces: tabela `public.vendors(name, phone_number_id, whatsapp, segments text[], enabled bool, created_at)`, semeada com João (`enabled=true`) e Arthur (`enabled=false`, `segments={exportacao,grao_verde}`).

- [ ] **Step 1: Escrever a migração**

```sql
-- backend/migrations/2026XXXX_vendors_table.sql
CREATE TABLE IF NOT EXISTS public.vendors (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    phone_number_id text,
    whatsapp        text,
    segments        text[] NOT NULL DEFAULT '{}',
    enabled         boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.vendors (name, phone_number_id, whatsapp, segments, enabled)
VALUES
  ('João - Café Canastra', '1049315514934778', '553491461669',
   ARRAY['atacado','private_label','consumo','secretaria'], true),
  ('Arthur - Exportação', NULL, NULL,
   ARRAY['exportacao','grao_verde'], false)
ON CONFLICT DO NOTHING;
```

- [ ] **Step 2: Aplicar em homolog + reload do schema cache**

Aplicar via MCP `supabase-homolog`; depois `NOTIFY pgrst, 'reload schema';`.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/2026XXXX_vendors_table.sql
git commit -m "feat(db): tabela vendors (seed Joao enabled, Arthur disabled)"
```

---

### Task 12: `vendors/service.py` — resolução de destino por segmento

**Files:**
- Create: `backend/app/vendors/__init__.py`, `backend/app/vendors/service.py`
- Test: `backend/tests/test_vendor_routing.py`

**Interfaces:**
- Produces: `resolve_vendor_for_segment(segment: str) -> dict | None` — retorna o vendedor `enabled=true` cujo `segments` contém `segment`; se nenhum habilitado cobre o segmento, faz fallback para o vendedor `enabled=true` de maior cobertura padrão (João). Retorna dict com `name`, `whatsapp`, `phone_number_id`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_vendor_routing.py
import app.vendors.service as vsvc


def _fake_vendors():
    return [
        {"name": "João - Café Canastra", "whatsapp": "553491461669", "phone_number_id": "1049315514934778",
         "segments": ["atacado", "private_label", "consumo", "secretaria"], "enabled": True},
        {"name": "Arthur - Exportação", "whatsapp": None, "phone_number_id": None,
         "segments": ["exportacao", "grao_verde"], "enabled": False},
    ]


def test_exportacao_com_arthur_disabled_cai_no_joao(monkeypatch):
    monkeypatch.setattr(vsvc, "_load_vendors", lambda: _fake_vendors())
    v = vsvc.resolve_vendor_for_segment("exportacao")
    assert v["name"].startswith("João")   # Arthur disabled → contato vai pro João


def test_atacado_resolve_joao(monkeypatch):
    monkeypatch.setattr(vsvc, "_load_vendors", lambda: _fake_vendors())
    v = vsvc.resolve_vendor_for_segment("atacado")
    assert v["name"].startswith("João")
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `python -m pytest tests/test_vendor_routing.py -v`
Expected: FAIL — módulo não existe.

- [ ] **Step 3: Implementar**

```python
# backend/app/vendors/service.py
from app.db.supabase import get_supabase


def _load_vendors() -> list[dict]:
    sb = get_supabase()
    return (sb.table("vendors").select("*").execute().data) or []


def resolve_vendor_for_segment(segment: str) -> dict | None:
    """Vendedor enabled cujo segments cobre `segment`; senão, o João (fallback enabled)."""
    vendors = _load_vendors()
    enabled = [v for v in vendors if v.get("enabled")]
    for v in enabled:
        if segment in (v.get("segments") or []):
            return v
    # fallback: primeiro enabled (João cobre os segmentos padrão)
    return enabled[0] if enabled else None
```

- [ ] **Step 4: Rodar para confirmar que passa**

Run: `python -m pytest tests/test_vendor_routing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/vendors/ backend/tests/test_vendor_routing.py
git commit -m "feat(vendors): resolve_vendor_for_segment filtra por enabled (fonte unica de roteamento)"
```

---

### Task 13: `encaminhar_humano` e rescue resolvem destino via `vendors`

**Files:**
- Modify: `backend/app/agent/tools.py` (`encaminhar_humano`, consts `_SUPERVISOR_*`)
- Modify: `backend/app/follow_up/scheduler.py` (`_JOAO_*` → destino resolvido)
- Modify: `backend/app/agent/prompts/base.py`, `backend/app/agent/prompts/valeria_inbound/exportacao.py` (regra de nomeação derivada)
- Test: `backend/tests/test_vendor_routing.py` (estender com o efeito no handoff)

> **Mitigação (obrigatório):** `encaminhar_humano` é agora o alvo do **fallback automático de LLM-down** (o processor o chama em L906 com `vendedor="Joao Bras"` e sem segmento claro). A resolução via `vendors` **deve** recair no João nesse caso — garantir que `resolve_vendor_for_segment(None/desconhecido)` retorne o primeiro vendedor `enabled` (João). Adicionar teste explícito para o caminho de fallback sem segmento, além do de exportação.

**Interfaces:**
- Consumes: `resolve_vendor_for_segment`.
- Produces: cartão/rescue usam o `whatsapp`/`phone_number_id` do vendedor resolvido; a IA nomeia apenas vendedor `enabled` para o segmento.

- [ ] **Step 1: Escrever o teste que falha**

```python
# estender backend/tests/test_vendor_routing.py
def test_handoff_usa_vendedor_resolvido(monkeypatch):
    import app.agent.tools as tools
    # com Arthur disabled, um handoff de exportacao deve usar o whatsapp do João
    ...
```

> Nota: modele o mock a partir de `test_agent_tools.py`; trave que o cartão de contato usa o `whatsapp` do vendedor resolvido, não `_SUPERVISOR_PHONE` hardcoded.

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `python -m pytest tests/test_vendor_routing.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar**

Substituir o uso de `_SUPERVISOR_NAME`/`_SUPERVISOR_PHONE` em `encaminhar_humano` por `resolve_vendor_for_segment(stage_ou_segmento)`. No scheduler, resolver o vendedor do rescue da mesma forma. Nos prompts, tornar a regra de nomeação única: "nomeie ao lead apenas o vendedor habilitado para este segmento; se o vendedor do segmento estiver indisponível, confirme o repasse sem citar nome". Remover a instrução contraditória de `exportacao.py` que obriga citar "Arthur".

- [ ] **Step 4: Rodar para confirmar que passa**

Run: `python -m pytest tests/test_vendor_routing.py tests/test_agent_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/app/follow_up/scheduler.py backend/app/agent/prompts/base.py backend/app/agent/prompts/valeria_inbound/exportacao.py backend/tests/test_vendor_routing.py
git commit -m "feat(handoff): destino resolvido via vendors; fim da promessa falsa (nao nomeia vendedor disabled)"
```

---

### Task 14: Visão nativa leve para imagens inbound

**Files:**
- Create: `backend/app/agent/vision.py`
- Modify: `backend/app/buffer/processor.py` (`_resolve_media`, ~L1229–1235)
- Remove: `backend/app/whatsapp/media.py` (código morto)
- Test: `backend/tests/test_inbound_vision.py`

**Interfaces:**
- Produces: `describe_image_inbound(image_bytes: bytes, mimetype: str) -> str` via Gemini `generateContent` (mesmo padrão de `_transcribe_audio`); no `_resolve_media`, o placeholder de imagem vira `[imagem: <descrição>]` (fallback `[imagem]` em erro).

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_inbound_vision.py
import app.agent.vision as vision


async def test_describe_image_inbound_retorna_descricao(monkeypatch):
    async def _fake_call(*_a, **_k):
        return "logo de uma marca de café com fundo marrom"
    monkeypatch.setattr(vision, "_gemini_vision_call", _fake_call, raising=False)
    out = await vision.describe_image_inbound(b"\x89PNG...", "image/png")
    assert "café" in out


async def test_describe_image_inbound_fail_open(monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("api down")
    monkeypatch.setattr(vision, "_gemini_vision_call", _boom, raising=False)
    out = await vision.describe_image_inbound(b"x", "image/png")
    assert out == ""   # fail-open: chamador injeta o marcador cego [imagem]
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `python -m pytest tests/test_inbound_vision.py -v`
Expected: FAIL — módulo não existe.

- [ ] **Step 3: Implementar**

Criar `backend/app/agent/vision.py` com `describe_image_inbound` (reaproveitando o padrão de `_transcribe_audio`: `generateContent` com `inline_data`, prompt "Descreva em uma frase curta o que há nesta imagem", timeout/retry, fail-open retornando `""`). Em `_resolve_media` do processor, quando a mídia é imagem: baixar bytes (reusar `_download_media_with_retry`), chamar `describe_image_inbound`; se retornar texto, injetar `[imagem: <descrição>]`, senão manter o marcador `[imagem]`. Remover `backend/app/whatsapp/media.py` (confirmar via grep que não há imports: `grep -rn "from app.whatsapp.media" backend/` → 0).

- [ ] **Step 4: Rodar para confirmar que passa**

Run: `python -m pytest tests/test_inbound_vision.py tests/test_24h_window_processor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/vision.py backend/app/buffer/processor.py backend/tests/test_inbound_vision.py
git rm backend/app/whatsapp/media.py
git commit -m "feat(vision): descricao nativa de imagens inbound ([imagem: ...]) e remocao de codigo morto"
```

---

## Verificação Final da Fase

Ao concluir cada fase, rodar a suíte completa a partir de `backend/`:

Run: `python -m pytest -q`
Expected: PASS (sem regressões)

Seguir o fluxo git do projeto (branch → `git pull origin master` → `git push origin <branch>:master`) **somente após autorização do usuário** para subir a produção.

---

## Self-Review (cobertura spec → tarefas)

- §3.1 get_history → Task 1 ✅
- §3.2 resposta vazia / narrativa longa → Task 7 ✅
- §3.3 visão inbound (P2) → Task 14 ✅
- §4.1 tabela vendors → Tasks 11, 12 ✅
- §4.2 fim da promessa falsa → Task 13 (P2) + ajuste textual em Task 4/base (P0/P1) ✅
- §4.3 captura CNPJ/intenção → Task 8 ✅
- §4.4 SLA (confirmação imediata, 4xx, órfão) → Task 9 ✅
- §5.1 autoridade DB lote mínimo → Tasks 5, 6 ✅
- §5.2 preço firme → Task 4 ✅
- §5.3 álbum/duplicação/idempotência/desempate → Tasks 2, 3, 10 ✅
- Testes exigidos (get_history, enviar_fotos, colisão timestamp, destino handoff) → Tasks 1, 2, 3, 12/13 ✅
