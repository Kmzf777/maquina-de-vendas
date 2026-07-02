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
    if status == 403:
        return openai.PermissionDeniedError("billing dunning deny", response=resp, body=None)
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
