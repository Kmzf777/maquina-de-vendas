"""TDD do endurecimento do retry do LLM (2026-07-01).

Causa raiz forense (lead Welita 5564984794946): a partir de 18:02 UTC toda chamada
ao Gemini falhava; o wrapper de retry só retentava erros de conexão, então um 429
(quota) era relançado cru, run_agent lançava e o processor caía em [AGENT FAILED]
silencioso — lead fantasmado. Aqui garantimos: retry de 429/5xx com backoff, 4xx
relançado na hora, e LLMUnavailableError ao esgotar (sinal para o fallback de handoff).

Migração 2026-07-02: transporte 100%% nativo google-genai. As exceções de provedor
são `google.genai.errors.APIError` (ClientError=4xx, ServerError=5xx) com o
status HTTP em `.code`. A política de retry é idêntica.

Migração 09/07 (Gemini 100% nativo, sem fachada OpenAI): o wrapper virou
`_generate_with_retry(**kwargs)` e chama `app.agent.orchestrator.generate` —
o teste patcha esse símbolo com side_effect de exceções, no lugar do antigo
`client.chat.completions.create`.
"""
import pytest
from unittest.mock import AsyncMock, patch

from google.genai import errors as genai_errors

from app.agent.gemini_client import user_content
from app.agent.orchestrator import _generate_with_retry, LLMUnavailableError


def _status_error(status: int) -> genai_errors.APIError:
    """Constrói o erro nativo google-genai equivalente ao status HTTP dado.

    ClientError para 4xx (429/403/400), ServerError para 5xx — ambos carregam o
    status em `.code`, que é o que _generate_with_retry inspeciona.
    """
    body = {"error": {"code": status, "message": f"synthetic {status}", "status": "SYNTHETIC"}}
    if status >= 500:
        return genai_errors.ServerError(status, body)
    return genai_errors.ClientError(status, body)


def _gen_raising(*exceptions) -> AsyncMock:
    """Mock de generate() que lança cada exceção em sequência; depois devolve 'OK'."""
    async def _side_effect(**kwargs):
        i = _side_effect.calls
        _side_effect.calls += 1
        if i < len(exceptions):
            raise exceptions[i]
        return "OK"
    _side_effect.calls = 0
    return AsyncMock(side_effect=_side_effect)


async def _call_with(m_gen: AsyncMock):
    """Invoca o wrapper com kwargs nativos mínimos (generate está mockado)."""
    with patch("app.agent.orchestrator.generate", new=m_gen), \
         patch("app.agent.orchestrator.asyncio.sleep", new=AsyncMock()):
        return await _generate_with_retry(
            model="gemini-2.5-flash", contents=[user_content("ping")],
        )


@pytest.mark.asyncio
async def test_retry_on_429_then_success():
    m_gen = _gen_raising(_status_error(429))
    result = await _call_with(m_gen)
    assert result == "OK"
    assert m_gen.await_count == 2  # 1 falha (429) + 1 sucesso


@pytest.mark.asyncio
async def test_retry_on_503_then_success():
    m_gen = _gen_raising(_status_error(503))
    result = await _call_with(m_gen)
    assert result == "OK"
    assert m_gen.await_count == 2


@pytest.mark.asyncio
async def test_exhaust_raises_llm_unavailable():
    m_gen = _gen_raising(*[_status_error(429)] * 5)  # sempre 429
    with pytest.raises(LLMUnavailableError):
        await _call_with(m_gen)
    assert m_gen.await_count == 3  # _LLM_RETRY_ATTEMPTS


@pytest.mark.asyncio
async def test_400_reraised_immediately_not_wrapped():
    m_gen = _gen_raising(*[_status_error(400)] * 5)
    with pytest.raises(genai_errors.ClientError):
        await _call_with(m_gen)
    assert m_gen.await_count == 1  # sem retry em 4xx não-retentável


@pytest.mark.asyncio
async def test_retry_on_403_billing_then_success():
    # 403 (billing/dunning) é indisponibilidade, não erro de request → retenta.
    m_gen = _gen_raising(_status_error(403))
    result = await _call_with(m_gen)
    assert result == "OK"
    assert m_gen.await_count == 2  # 1 falha (403) + 1 sucesso


@pytest.mark.asyncio
async def test_exhaust_403_raises_llm_unavailable():
    # 403 persistente → LLMUnavailableError (aciona o handoff no processor).
    m_gen = _gen_raising(*[_status_error(403)] * 5)
    with pytest.raises(LLMUnavailableError):
        await _call_with(m_gen)
    assert m_gen.await_count == 3  # _LLM_RETRY_ATTEMPTS
