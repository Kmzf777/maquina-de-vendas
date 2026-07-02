# Valéria LLM Resilience & Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando o LLM (Gemini) cai, nenhum lead é fantasmado — ele é encaminhado ao humano (cartão do João) — e o apagão vira um incidente visível em `system_alerts`.

**Architecture:** Três mudanças isoladas: (1) `_create_with_retry` passa a retentar 429/5xx com backoff e lança `LLMUnavailableError` ao esgotar; (2) o processor, ao receber `LLMUnavailableError`, aciona `encaminhar_humano` em vez de retornar mudo; (3) um contador Redis de falhas consecutivas dispara um alerta `llm_down` em `system_alerts` (dedup 1/h) e zera no 1º sucesso.

**Tech Stack:** Python 3.11, pytest, `openai` (endpoint OpenAI-compat do Gemini), `httpx`, `redis.asyncio`, Supabase (`system_alerts`).

## Global Constraints

- Provedor WhatsApp ativo = **Meta Graph API** (`MetaCloudClient`); ignorar Evolution. (CLAUDE.md §6)
- Paridade de ambiente: o código roda dentro do container e no host sem modificação. (CLAUDE.md §3)
- Número/nome do supervisor já definidos: `_SUPERVISOR_PHONE = "553491461669"`, `_SUPERVISOR_NAME = "João - Café Canastra"` (`backend/app/agent/tools.py:117-118`).
- Retry consts existentes: `_LLM_RETRY_ATTEMPTS = 3`, `_LLM_RETRY_DELAY = 2` (`orchestrator.py:371-372`) — reutilizar, não duplicar.
- Vendedor do handoff automático: `"Joao Bras"`; motivo verbatim: `"IA temporariamente indisponível — atendimento encaminhado ao humano"`.
- Limiar de alerta: **3** falhas consecutivas. Dedup do alerta: 1 não-resolvido por hora (padrão de `fire_billing_alert`, `backend/app/alerts/service.py:31-60`).
- Comando de teste base: rodar dentro de `backend/` com `python -m pytest`.

---

## File Structure

- `backend/app/agent/orchestrator.py` — **Modify**: adiciona `LLMUnavailableError` e endurece `_create_with_retry` (linhas 375-389).
- `backend/app/buffer/processor.py` — **Modify**: importa `LLMUnavailableError`; adiciona helpers de contador Redis + `_handle_llm_down` + `_fire_llm_down_alert`; ramo `LLMUnavailableError` no loop de `run_agent`; reset do contador no sucesso (linhas ~818-843).
- `backend/tests/test_llm_retry_resilience_2026_07_01.py` — **Create**: testes do retry/exceção.
- `backend/tests/test_processor_llm_down_handoff_2026_07_01.py` — **Create**: testes do fallback de handoff + contador/alerta.

---

## Task 1: Retry hardening + `LLMUnavailableError` (orchestrator)

**Files:**
- Modify: `backend/app/agent/orchestrator.py:375-389`
- Test: `backend/tests/test_llm_retry_resilience_2026_07_01.py`

**Interfaces:**
- Consumes: `_LLM_RETRY_ATTEMPTS`, `_LLM_RETRY_DELAY`, `openai`, `httpx`, `asyncio`, `logger` (já no módulo).
- Produces:
  - `class LLMUnavailableError(Exception)` — lançada por `_create_with_retry` quando o LLM está persistentemente indisponível (conexão/429/5xx esgotados).
  - `async def _create_with_retry(client, **kwargs)` — retorna a resposta em sucesso; retenta 429/5xx/conexão com backoff exponencial; **relança cru** 4xx não-retentável (400/401); lança `LLMUnavailableError` ao esgotar.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_retry_resilience_2026_07_01.py`:

```python
"""TDD do endurecimento do retry do LLM (2026-07-01).

Causa raiz forense (lead Welita 5564984794946): a partir de 18:02 UTC toda chamada
ao Gemini falhava; _create_with_retry só retentava erros de conexão, então um 429
(quota) era relançado cru, run_agent lançava e o processor caía em [AGENT FAILED]
silencioso — lead fantasmado. Aqui garantimos: retry de 429/5xx com backoff, 4xx
relançado na hora, e LLMUnavailableError ao esgotar (sinal para o fallback de handoff).
"""
import httpx
import openai
import pytest
from unittest.mock import AsyncMock, patch

from app.agent.orchestrator import _create_with_retry, LLMUnavailableError


def _status_error(status: int) -> openai.APIStatusError:
    req = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/openai/")
    resp = httpx.Response(status, request=req)
    if status == 429:
        return openai.RateLimitError("rate limited", response=resp, body=None)
    if status >= 500:
        return openai.InternalServerError("upstream boom", response=resp, body=None)
    return openai.BadRequestError("bad request", response=resp, body=None)


def _client_raising(*exceptions):
    """Cliente cujo create() lança cada exceção em sequência; o restante devolve 'OK'."""
    calls = {"n": 0}

    async def _create(**kwargs):
        i = calls["n"]
        calls["n"] += 1
        if i < len(exceptions):
            raise exceptions[i]
        return "OK"

    client = AsyncMock()
    client.chat.completions.create = _create
    client._calls = calls
    return client


@pytest.mark.asyncio
async def test_retry_on_429_then_success():
    client = _client_raising(_status_error(429))
    with patch("app.agent.orchestrator.asyncio.sleep", new=AsyncMock()):
        result = await _create_with_retry(client)
    assert result == "OK"
    assert client._calls["n"] == 2  # 1 falha (429) + 1 sucesso


@pytest.mark.asyncio
async def test_retry_on_503_then_success():
    client = _client_raising(_status_error(503))
    with patch("app.agent.orchestrator.asyncio.sleep", new=AsyncMock()):
        result = await _create_with_retry(client)
    assert result == "OK"
    assert client._calls["n"] == 2


@pytest.mark.asyncio
async def test_exhaust_raises_llm_unavailable():
    client = _client_raising(*[_status_error(429)] * 5)  # sempre 429
    with patch("app.agent.orchestrator.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(LLMUnavailableError):
            await _create_with_retry(client)
    assert client._calls["n"] == 3  # _LLM_RETRY_ATTEMPTS


@pytest.mark.asyncio
async def test_400_reraised_immediately_not_wrapped():
    client = _client_raising(*[_status_error(400)] * 5)
    with patch("app.agent.orchestrator.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(openai.BadRequestError):
            await _create_with_retry(client)
    assert client._calls["n"] == 1  # sem retry em 4xx não-retentável
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_llm_retry_resilience_2026_07_01.py -q`
Expected: FAIL — `ImportError: cannot import name 'LLMUnavailableError'`.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/agent/orchestrator.py`, replace the block at lines 375-389 (the current `_create_with_retry`) with:

```python
class LLMUnavailableError(Exception):
    """LLM persistentemente indisponível após esgotar os retries (conexão/429/5xx).

    Distingue 'LLM fora' de um bug qualquer: o processor usa este tipo para acionar o
    fallback de handoff (encaminhar_humano) em vez de falhar em silêncio.
    """


async def _create_with_retry(client: AsyncOpenAI, **kwargs):
    """chat.completions.create com retry em indisponibilidade transitória.

    Retenta drops de conexão (GOAWAY/timeout) E erros HTTP transitórios do provedor
    (429 rate-limit/quota, 5xx) com backoff exponencial, honrando Retry-After. Erros
    não-retentáveis (4xx exceto 429) são relançados na hora. Ao esgotar as tentativas
    de indisponibilidade → LLMUnavailableError.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _LLM_RETRY_ATTEMPTS + 1):
        _delay = _LLM_RETRY_DELAY * (2 ** (attempt - 1))
        try:
            return await client.chat.completions.create(**kwargs)
        except (openai.APIConnectionError, openai.APITimeoutError, httpx.TransportError) as exc:
            last_exc = exc
            logger.warning(
                "[LLM RETRY] tentativa %d/%d falhou (conexão): %s",
                attempt, _LLM_RETRY_ATTEMPTS, exc,
            )
        except openai.APIStatusError as exc:
            status = getattr(exc, "status_code", None)
            if status != 429 and not (isinstance(status, int) and status >= 500):
                raise  # 4xx não-retentável (400/401/...) → relança cru
            last_exc = exc
            try:
                _retry_after = float(exc.response.headers.get("retry-after", 0) or 0)
            except Exception:
                _retry_after = 0.0
            _delay = max(_delay, _retry_after)
            logger.warning(
                "[LLM RETRY] tentativa %d/%d falhou (HTTP %s): %s",
                attempt, _LLM_RETRY_ATTEMPTS, status, exc,
            )
        if attempt < _LLM_RETRY_ATTEMPTS:
            await asyncio.sleep(_delay)
    raise LLMUnavailableError(
        f"LLM indisponível após {_LLM_RETRY_ATTEMPTS} tentativas: {last_exc}"
    ) from last_exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_llm_retry_resilience_2026_07_01.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the affected regression slice**

Run: `cd backend && python -m pytest tests/test_orchestrator_retry_post_tool_2026_07_01.py tests/test_empty_response_retry_2026_06_24.py -q`
Expected: PASS (todos verdes — o contrato de sucesso de `_create_with_retry` é inalterado).

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/orchestrator.py backend/tests/test_llm_retry_resilience_2026_07_01.py
git commit -m "feat(orchestrator): retry 429/5xx + LLMUnavailableError em _create_with_retry"
```

---

## Task 2: Fallback de handoff no processor (mata a falha silenciosa)

**Files:**
- Modify: `backend/app/buffer/processor.py` (import perto do topo; helper novo antes de `process_buffered_messages`; loop de `run_agent` ~818-843)
- Test: `backend/tests/test_processor_llm_down_handoff_2026_07_01.py`

**Interfaces:**
- Consumes: `LLMUnavailableError` (Task 1); `_get_buffer_redis()` (`processor.py:1082`); `execute_tool` (`app.agent.tools`); `pop_interest_marked`, `_update_last_msg`, `logger`.
- Produces:
  - `async def _reset_llm_failures() -> None` — zera o contador Redis de falhas consecutivas. Fail-soft.
  - `async def _record_llm_failure() -> int` — INCR do contador; retorna a contagem (0 em erro). Fail-open.
  - `async def _handle_llm_down(lead: dict, phone: str, conversation: dict) -> None` — fallback: encaminha ao humano via `execute_tool("encaminhar_humano", ...)`. Fail-soft. (Contador/alerta entram na Task 3.)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_processor_llm_down_handoff_2026_07_01.py`:

```python
"""TDD do fallback de handoff quando o LLM está fora (2026-07-01).

Antes: run_agent lançava (LLM fora) → processor caía em [AGENT FAILED] → return mudo;
o lead (ex.: Welita) recebia 'digitando…' e nada mais. Agora: LLMUnavailableError
aciona encaminhar_humano — o cartão de contato do João é disparado ao lead e a IA é
desativada — em vez do silêncio. Exceções não-LLM mantêm o comportamento antigo.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.agent.orchestrator import LLMUnavailableError
from app.buffer import processor as P


@pytest.mark.asyncio
async def test_handle_llm_down_dispara_encaminhar_humano():
    lead = {"id": "lead-1", "phone": "5564984794946"}
    conversation = {"id": "conv-1", "stage": "secretaria"}
    with patch("app.agent.tools.execute_tool", new=AsyncMock(return_value="Lead encaminhado para Joao Bras")) as mock_exec:
        await P._handle_llm_down(lead, "5564984794946", conversation)
    mock_exec.assert_awaited_once()
    args, kwargs = mock_exec.await_args
    assert args[0] == "encaminhar_humano"
    assert args[1]["vendedor"] == "Joao Bras"
    assert kwargs["lead_id"] == "lead-1"
    assert kwargs["conversation_id"] == "conv-1"


@pytest.mark.asyncio
async def test_handle_llm_down_fail_soft_quando_handoff_falha():
    lead = {"id": "lead-1", "phone": "556484794946"}
    conversation = {"id": "conv-1", "stage": "secretaria"}
    # Handoff que explode NÃO pode propagar (nunca escala a falha).
    with patch("app.agent.tools.execute_tool", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await P._handle_llm_down(lead, "556484794946", conversation)  # não levanta
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_processor_llm_down_handoff_2026_07_01.py -q`
Expected: FAIL — `AttributeError: module 'app.buffer.processor' has no attribute '_handle_llm_down'`.

- [ ] **Step 3a: Add the import**

In `backend/app/buffer/processor.py`, na linha 20 (que já tem `from app.agent.orchestrator import run_agent, resolve_prompt_key`), acrescente `LLMUnavailableError`:

```python
from app.agent.orchestrator import run_agent, resolve_prompt_key, LLMUnavailableError
```

- [ ] **Step 3b: Add the helpers**

In `backend/app/buffer/processor.py`, imediatamente **antes** de `async def process_buffered_messages(` (linha 490), insira:

```python
_LLM_FAILURE_KEY = "llm:consecutive_failures"
_LLM_DOWN_ALERT_THRESHOLD = 3


async def _reset_llm_failures() -> None:
    """Zera o contador de falhas consecutivas de LLM no 1º sucesso. Fail-soft."""
    try:
        await _get_buffer_redis().delete(_LLM_FAILURE_KEY)
    except Exception as exc:
        logger.debug("[LLM DOWN] falha ao resetar contador: %s", exc)


async def _record_llm_failure() -> int:
    """INCR do contador de falhas consecutivas de LLM. Fail-open (0 em erro)."""
    try:
        return int(await _get_buffer_redis().incr(_LLM_FAILURE_KEY))
    except Exception as exc:
        logger.warning("[LLM DOWN] falha ao incrementar contador: %s", exc)
        return 0


async def _handle_llm_down(lead: dict, phone: str, conversation: dict) -> None:
    """Fallback quando o LLM está fora: encaminha o lead ao humano (cartão do João)
    em vez de fantasmá-lo. Reutiliza encaminhar_humano (desativa IA, cria deal,
    cancela follow-ups, envia o cartão de contato do João, agenda rescue). Fail-soft:
    nenhuma falha aqui pode escalar. Contador/alerta são plugados na Task 3.
    """
    try:
        from app.agent.tools import execute_tool
        await execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras",
             "motivo": "IA temporariamente indisponível — atendimento encaminhado ao humano"},
            lead_id=lead["id"], phone=phone, conversation_id=conversation["id"],
        )
    except Exception as exc:
        logger.error(
            "[LLM DOWN] falha no handoff automático p/ %s (conv=%s): %s",
            phone, conversation.get("id"), exc, exc_info=True,
        )
```

- [ ] **Step 3c: Wire the LLMUnavailableError branch + reset-on-success**

In `backend/app/buffer/processor.py`, no bloco do loop de `run_agent` (linhas 818-843), faça duas mudanças.

(i) Reset no sucesso — logo após `response = await run_agent(...)` e antes do `break`:

```python
                    response = await run_agent(
                        conversation, resolved_text,
                        lead_context=lead_context,
                        agent_profile_id=agent_profile_id,
                    )
                    await _reset_llm_failures()
                    break
```

(ii) Ramo dedicado para LLM fora — insira um `except LLMUnavailableError` **antes** do `except Exception as e` existente:

```python
                except LLMUnavailableError as e:
                    logger.error(
                        "[LLM DOWN] LLM indisponível para %s (conv=%s): %s",
                        phone, conversation["id"], e, exc_info=True,
                    )
                    pop_interest_marked(conversation["id"])
                    await _handle_llm_down(lead, phone, conversation)
                    _update_last_msg(conversation["id"])
                    return
                except Exception as e:
```

O corpo do `except Exception as e:` existente (retry 3× → `[AGENT FAILED]`) permanece **inalterado**, preservando o comportamento para exceções não-LLM.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_processor_llm_down_handoff_2026_07_01.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the processor regression slice**

Run: `cd backend && python -m pytest tests/test_processor_errors.py tests/test_processor_human_control.py tests/test_encaminhar_humano_pipeline.py -q`
Expected: PASS (comportamento não-LLM e handoff manual intactos).

- [ ] **Step 6: Commit**

```bash
git add backend/app/buffer/processor.py backend/tests/test_processor_llm_down_handoff_2026_07_01.py
git commit -m "feat(processor): handoff automatico ao humano quando o LLM esta fora (LLMUnavailableError)"
```

---

## Task 3: Observabilidade — alerta `llm_down` em `system_alerts`

**Files:**
- Modify: `backend/app/buffer/processor.py` (`_handle_llm_down` + novo `_fire_llm_down_alert`)
- Test: `backend/tests/test_processor_llm_down_handoff_2026_07_01.py` (acrescenta casos)

**Interfaces:**
- Consumes: `create_system_alert` (`app.alerts.service`); `get_supabase` (`app.db.supabase`); `datetime`, `timedelta`, `timezone` (já importados, `processor.py:8`); `_record_llm_failure`, `_LLM_DOWN_ALERT_THRESHOLD` (Task 2).
- Produces: `def _fire_llm_down_alert(count: int) -> None` — grava 1 alerta `type="llm_down"` (dedup: 1 não-resolvido por hora). E `_handle_llm_down` passa a incrementar o contador e disparar o alerta ao atingir o limiar.

- [ ] **Step 1: Write the failing test**

Acrescente ao final de `backend/tests/test_processor_llm_down_handoff_2026_07_01.py`:

```python
@pytest.mark.asyncio
async def test_alerta_llm_down_dispara_no_limiar_e_deduplica():
    lead = {"id": "lead-1", "phone": "5564984794946"}
    conversation = {"id": "conv-1", "stage": "secretaria"}
    with patch("app.agent.tools.execute_tool", new=AsyncMock()), \
         patch("app.buffer.processor._record_llm_failure", new=AsyncMock(return_value=3)), \
         patch("app.buffer.processor._fire_llm_down_alert") as mock_alert:
        await P._handle_llm_down(lead, "5564984794946", conversation)
    mock_alert.assert_called_once_with(3)


@pytest.mark.asyncio
async def test_alerta_llm_down_nao_dispara_abaixo_do_limiar():
    lead = {"id": "lead-1", "phone": "5564984794946"}
    conversation = {"id": "conv-1", "stage": "secretaria"}
    with patch("app.agent.tools.execute_tool", new=AsyncMock()), \
         patch("app.buffer.processor._record_llm_failure", new=AsyncMock(return_value=2)), \
         patch("app.buffer.processor._fire_llm_down_alert") as mock_alert:
        await P._handle_llm_down(lead, "5564984794946", conversation)
    mock_alert.assert_not_called()


def test_fire_llm_down_alert_deduplica_por_alerta_nao_resolvido(monkeypatch):
    # Alerta não-resolvido recente já existe → NÃO cria outro.
    class _Resp:  # noqa
        data = [{"id": "a1"}]

    class _Q:  # encadeamento fluente do supabase-py
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def gte(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return _Resp()

    class _SB:
        def table(self, *a, **k): return _Q()

    monkeypatch.setattr("app.buffer.processor.get_supabase", lambda: _SB(), raising=False)
    calls = {"n": 0}
    monkeypatch.setattr("app.buffer.processor.create_system_alert",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1), raising=False)
    P._fire_llm_down_alert(3)
    assert calls["n"] == 0  # deduplicado
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_processor_llm_down_handoff_2026_07_01.py -q`
Expected: FAIL — `AttributeError: ... has no attribute '_fire_llm_down_alert'` (e o alerta ainda não é chamado em `_handle_llm_down`).

- [ ] **Step 3a: Add the imports at top of processor**

In `backend/app/buffer/processor.py`, junto aos imports do topo (após a linha 20), adicione:

```python
from app.alerts.service import create_system_alert
from app.db.supabase import get_supabase
```

(Se `get_supabase` já estiver importado no arquivo, não duplique — use o existente.)

- [ ] **Step 3b: Add `_fire_llm_down_alert`**

In `backend/app/buffer/processor.py`, logo **após** `_handle_llm_down` (da Task 2), insira:

```python
def _fire_llm_down_alert(count: int) -> None:
    """Grava 1 alerta llm_down em system_alerts (dedup: 1 não-resolvido por hora).

    Espelha o padrão de fire_billing_alert. Transforma o apagão silencioso do LLM em
    incidente visível no CRM (o caso Welita passou sem qualquer alerta). Fail-soft.
    """
    try:
        sb = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        existing = (
            sb.table("system_alerts").select("id")
            .eq("type", "llm_down").eq("resolved", False)
            .gte("created_at", cutoff).limit(1).execute()
        )
        if existing.data:
            return
    except Exception as exc:
        logger.warning("[LLM DOWN] falha ao checar alerta existente: %s", exc)
    create_system_alert(
        "llm_down",
        "IA (Valéria) indisponível — LLM fora",
        f"{count} turnos consecutivos falharam ao chamar o LLM. Leads estão sendo "
        "encaminhados automaticamente ao humano (João). Verifique quota/saúde do provedor.",
        severity="critical",
    )
```

- [ ] **Step 3c: Wire counter + alert into `_handle_llm_down`**

In `_handle_llm_down` (Task 2), **antes** do bloco `try/except` que chama `execute_tool`, insira:

```python
    try:
        _count = await _record_llm_failure()
        if _count >= _LLM_DOWN_ALERT_THRESHOLD:
            _fire_llm_down_alert(_count)
    except Exception as exc:
        logger.warning("[LLM DOWN] falha ao registrar/alertar contador p/ %s: %s", phone, exc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_processor_llm_down_handoff_2026_07_01.py -q`
Expected: PASS (5 passed — 2 da Task 2 + 3 da Task 3).

- [ ] **Step 5: Full affected-slice regression**

Run: `cd backend && python -m pytest tests/test_llm_retry_resilience_2026_07_01.py tests/test_processor_llm_down_handoff_2026_07_01.py tests/test_processor_errors.py tests/test_orchestrator_retry_post_tool_2026_07_01.py tests/test_encaminhar_humano_pipeline.py -q`
Expected: PASS (tudo verde).

- [ ] **Step 6: Commit**

```bash
git add backend/app/buffer/processor.py backend/tests/test_processor_llm_down_handoff_2026_07_01.py
git commit -m "feat(observability): alerta llm_down em system_alerts com contador consecutivo + dedup"
```

---

## Self-Review

**Spec coverage:**
- Componente 1 (retry 429/5xx + `LLMUnavailableError`, 4xx cru) → Task 1. ✅
- Componente 2 (fallback `encaminhar_humano`, cartão do João, idempotência via `ai_enabled`) → Task 2. ✅
- Componente 3 (contador Redis consecutivo, alerta `system_alerts` dedup 1/h, reset no sucesso) → Task 2 (reset/contador) + Task 3 (alerta). ✅
- Testes TDD da spec §6 → cobertos em Task 1 (retry/exceção), Task 2 (handoff + regressão não-LLM), Task 3 (alerta no limiar/dedup). ✅

**Placeholder scan:** Nenhum TBD/TODO; todo passo de código traz o código completo. ✅

**Type consistency:** `LLMUnavailableError`, `_create_with_retry`, `_handle_llm_down(lead, phone, conversation)`, `_record_llm_failure()->int`, `_reset_llm_failures()`, `_fire_llm_down_alert(count)`, `_LLM_FAILURE_KEY`, `_LLM_DOWN_ALERT_THRESHOLD` usados de forma idêntica entre tarefas. ✅

**Nota de escopo:** idempotência do handoff em turnos repetidos é fornecida pelo gate `lead.ai_enabled=false` (`processor.py:683`) já existente + dedup de despedida (`tools.py:779`) — nenhuma tarefa nova necessária (spec §5).
