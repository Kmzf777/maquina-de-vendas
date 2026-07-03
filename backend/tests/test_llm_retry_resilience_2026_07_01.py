"""TDD do endurecimento do retry do LLM (2026-07-01).

Causa raiz forense (lead Welita 5564984794946): a partir de 18:02 UTC toda chamada
ao Gemini falhava; _create_with_retry só retentava erros de conexão, então um 429
(quota) era relançado cru, run_agent lançava e o processor caía em [AGENT FAILED]
silencioso — lead fantasmado. Aqui garantimos: retry de 429/5xx com backoff, 4xx
relançado na hora, e LLMUnavailableError ao esgotar (sinal para o fallback de handoff).

Migração 2026-07-02: transporte 100%% nativo google-genai. As exceções de provedor
agora são `google.genai.errors.APIError` (ClientError=4xx, ServerError=5xx) com o
status HTTP em `.code` — não mais as classes `openai.*`. A política de retry é idêntica.
"""
import pytest
from unittest.mock import AsyncMock, patch

from google.genai import errors as genai_errors

from app.agent.orchestrator import _create_with_retry, LLMUnavailableError


def _status_error(status: int) -> genai_errors.APIError:
    """Constrói o erro nativo google-genai equivalente ao status HTTP dado.

    ClientError para 4xx (429/403/400), ServerError para 5xx — ambos carregam o
    status em `.code`, que é o que _create_with_retry inspeciona.
    """
    body = {"error": {"code": status, "message": f"synthetic {status}", "status": "SYNTHETIC"}}
    if status >= 500:
        return genai_errors.ServerError(status, body)
    return genai_errors.ClientError(status, body)


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
        with pytest.raises(genai_errors.ClientError):
            await _create_with_retry(client)
    assert client._calls["n"] == 1  # sem retry em 4xx não-retentável


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
