"""Recuperação de resposta vazia do LLM — auditoria leads 5549984064339 / 5551984772757, 2026-06-24.

Reincidência do bug da Carla: gemini-2.5-flash queima o budget pensando e devolve
completion_tokens=0 mesmo num input perfeitamente válido ("oi bom dia sim me chamo
Anderson"). A chamada inicial do run_agent NÃO desliga o thinking, então o turno normal
vazio caía direto no _SAFETY_FALLBACK_MESSAGE ("acho que sua mensagem chegou cortada aqui").

Comportamento desejado:
  1. resposta vazia → UM retry silencioso com thinking 100% off (recupera o texto real);
  2. se o retry trouxer texto → usa o texto (lead recebe resposta normal);
  3. se ainda vier vazio e não houver contexto coerente → aborta em silêncio (retorna ""),
     NUNCA o "chegou cortada".

Migração 09/07 (Gemini 100% nativo): o mock agora é `app.agent.orchestrator.generate`
(GenerateResult fakes) — a fachada OpenAI (.choices/.usage) não existe mais.
"""
import pytest
from unittest.mock import AsyncMock, patch

from tests.gemini_fakes import fake_text


def _conversation():
    return {
        "id": "conv-anderson",
        "stage": "secretaria",
        "leads": {"id": "lead-and", "name": "Anderson", "phone": "5551984772757", "ai_enabled": True},
    }


def _history():
    return [{
        "role": "user", "content": "oi bom dia sim me chamo Anderson", "stage": "secretaria",
        "created_at": "2026-06-24T12:38:38Z", "wamid": "wamid-a",
        "quoted_wamid": None, "message_type": "text", "metadata": None,
    }]


@pytest.mark.asyncio
async def test_empty_initial_then_retry_recovers_text():
    """Input válido, 1ª chamada vazia (gemini 0 tokens), retry sem thinking traz o texto real."""
    from app.agent.orchestrator import run_agent

    call_responses = [
        fake_text(""),                  # inicial — thinking on, 0 tokens visíveis
        fake_text("bom dia Anderson\n\nme conta o que te trouxe aqui"),  # retry off
    ]

    with patch("app.agent.orchestrator.get_history", return_value=_history()), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-and", "ai_enabled": True}), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=call_responses)) as m_gen:
        result = await run_agent(_conversation(), "oi bom dia sim me chamo Anderson")

    assert result == "bom dia Anderson\n\nme conta o que te trouxe aqui"
    assert m_gen.await_count == 2, "deve ter feito exatamente o retry silencioso"


@pytest.mark.asyncio
async def test_empty_initial_and_empty_retry_never_sends_chegou_cortada():
    """Os dois tiros vazios → retorna o fallback genérico honesto (Change C 2026-06-30).
    Garante que o texto literal do fallback enganoso NUNCA é devolvido E que o lead nunca
    fica em silêncio total."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_MESSAGE, _SAFETY_FALLBACK_GENERIC

    # Etapa 2: inicial + retry1 vazios ainda disparam o retry2 (temperatura elevada) antes
    # do fallback final — também vazio aqui, para o teste chegar ao fallback genérico.
    call_responses = [fake_text(""), fake_text(""), fake_text("")]

    with patch("app.agent.orchestrator.get_history", return_value=_history()), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-and", "ai_enabled": True}), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=call_responses)) as m_gen:
        result = await run_agent(_conversation(), "oi bom dia sim me chamo Anderson")

    # Change C: genérico honesto em vez de silêncio total
    assert result == _SAFETY_FALLBACK_GENERIC
    assert result != ""
    assert result != _SAFETY_FALLBACK_MESSAGE
    assert "chegou cortada" not in result
    assert "cortada" not in result
    assert m_gen.await_count == 3, "inicial + retry silencioso + retry2 antes do fallback"
