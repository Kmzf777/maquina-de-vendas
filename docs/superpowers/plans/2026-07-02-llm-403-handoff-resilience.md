# LLM 403→Handoff Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer um `403` (billing/permissão negada) do LLM virar `LLMUnavailableError`, acionando o handoff-ao-humano + alerta `llm_down` já existentes, em vez de falha silenciosa.

**Architecture:** Mudança de uma linha na classificação de status em `_create_with_retry` (orchestrator) — incluir `403` no balde já existente de `429`/`5xx`. Todo o downstream (processor `except LLMUnavailableError` → `_handle_llm_down` → `encaminhar_humano` + `_fire_llm_down_alert`) já existe e NÃO é tocado. TDD espelhando `tests/test_llm_retry_resilience_2026_07_01.py`.

**Tech Stack:** Python 3.11, pytest (asyncio_mode=auto), openai SDK (transporte do Gemini via endpoint compat).

## Global Constraints

- Rodar testes com `python -m pytest ...` a partir de `backend/`.
- **Única alteração de código:** `backend/app/agent/orchestrator.py::_create_with_retry`. NÃO alterar o processor nem `_handle_llm_down`/`_fire_llm_down_alert`/`encaminhar_humano`.
- `403` entra no MESMO comportamento de `429` (retry com backoff → `LLMUnavailableError` ao esgotar). Não curto-circuitar.
- Preservar inalterado: `429`/`5xx` (retentados) e `400`/`401`/`404` (relançados crus).
- Testes novos espelham o estilo de `tests/test_llm_retry_resilience_2026_07_01.py`.

---

### Task 1: Classificar 403 (billing) como LLM indisponível

**Files:**
- Modify: `backend/app/agent/orchestrator.py` (`_create_with_retry`, ~L370-407; docstrings ~L363 e ~L371-377)
- Test: `backend/tests/test_llm_retry_resilience_2026_07_01.py` (helper `_status_error` + 2 testes novos)

**Interfaces:**
- Consumes: `openai.APIStatusError` (e subclasses `RateLimitError`=429, `PermissionDeniedError`=403, `InternalServerError`=5xx, `BadRequestError`=400), `LLMUnavailableError`, `_create_with_retry(client, **kwargs)`.
- Produces: comportamento — `_create_with_retry` levanta `LLMUnavailableError` quando o provedor retorna `403` de forma persistente.

- [ ] **Step 1: Escrever os testes que falham**

Em `backend/tests/test_llm_retry_resilience_2026_07_01.py`, atualizar o helper `_status_error` para cobrir 403 e adicionar 2 testes. Substituir a função `_status_error` existente por:

```python
def _status_error(status: int) -> openai.APIStatusError:
    req = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/openai/")
    resp = httpx.Response(status, request=req)
    if status == 429:
        return openai.RateLimitError("rate limited", response=resp, body=None)
    if status == 403:
        return openai.PermissionDeniedError("billing dunning deny", response=resp, body=None)
    if status >= 500:
        return openai.InternalServerError("upstream boom", response=resp, body=None)
    return openai.BadRequestError("bad request", response=resp, body=None)
```

E adicionar ao final do arquivo:

```python
@pytest.mark.asyncio
async def test_retry_on_403_billing_then_success():
    # 403 (billing/dunning) é indisponibilidade, não erro de request → retenta.
    client = _client_raising(_status_error(403))
    with patch("app.agent.orchestrator.asyncio.sleep", new=AsyncMock()):
        result = await _create_with_retry(client)
    assert result == "OK"
    assert client._calls["n"] == 2  # 1 falha (403) + 1 sucesso


@pytest.mark.asyncio
async def test_exhaust_403_raises_llm_unavailable():
    # 403 persistente → LLMUnavailableError (aciona o handoff no processor).
    client = _client_raising(*[_status_error(403)] * 5)
    with patch("app.agent.orchestrator.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(LLMUnavailableError):
            await _create_with_retry(client)
    assert client._calls["n"] == 3  # _LLM_RETRY_ATTEMPTS
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_llm_retry_resilience_2026_07_01.py -q` (de `backend/`)
Expected: FALHA — `test_retry_on_403_billing_then_success` e `test_exhaust_403_raises_llm_unavailable` falham porque o 403 atual é relançado cru (`openai.PermissionDeniedError`), não retentado nem convertido em `LLMUnavailableError`.

- [ ] **Step 3: Implementar a mudança mínima**

Em `backend/app/agent/orchestrator.py`, dentro de `_create_with_retry`, trocar a condição de não-retentável (linha ~391):

```python
            if status != 429 and not (isinstance(status, int) and status >= 500):
                raise  # 4xx não-retentável (400/401/...) → relança cru
```

por:

```python
            if status not in (403, 429) and not (isinstance(status, int) and status >= 500):
                raise  # 4xx não-retentável (400/401/404/...) → relança cru
```

Atualizar as duas docstrings para refletir o 403:
- Classe `LLMUnavailableError` (~L363): trocar `(conexão/429/5xx)` por `(conexão/403/429/5xx)`.
- `_create_with_retry` (~L373-376): trocar `(429 rate-limit/quota, 5xx)` por `(429 rate-limit/quota, 403 billing/permissão negada, 5xx)`.

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_llm_retry_resilience_2026_07_01.py -q` (de `backend/`)
Expected: PASS (todos, incluindo os 2 novos; os existentes de 429/5xx/400 continuam verdes).

- [ ] **Step 5: Regressão da área + commit**

Run: `python -m pytest tests/test_llm_retry_resilience_2026_07_01.py tests/test_processor_llm_down_handoff_2026_07_01.py tests/test_orchestrator_gemini.py -q` (de `backend/`)
Expected: PASS (baseline 14 + 2 novos = 16).

```bash
git add backend/app/agent/orchestrator.py backend/tests/test_llm_retry_resilience_2026_07_01.py docs/superpowers/specs/2026-07-02-llm-403-handoff-resilience-design.md docs/superpowers/plans/2026-07-02-llm-403-handoff-resilience.md
git commit -m "fix(orchestrator): 403 billing vira LLMUnavailableError (handoff, nao silencio)"
```
