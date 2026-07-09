"""Guarda de pergunta repetida no run_agent — o caso Luciano (2026-07-08).

Transcrição real: o lead disse "Sou o Luciano mas não tenho mais a cafeteria",
recebeu o carimbo com a pergunta "café pra você é mais um prazer do dia a dia ou
tem a ver com algum projeto seu?"; repetiu "Eu tinha uma cafeteria mas fechei." e
recebeu a MESMA pergunta verbatim. Na 3ª insistência foi para sem_interesse — uma
conversão B2C óbvia perdida por um loop de script.

A guarda detecta a pergunta repetida no texto final e faz UMA regeneração
corretiva ancorada; se a correção vier limpa, ela substitui o texto.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_PERGUNTA = (
    "café pra você é mais um prazer do dia a dia ou tem a ver com algum projeto seu?"
)

_OPENER = (
    "que bom, Luciano\n\n"
    "a gente é a torrefação de café especial da Serra da Canastra e antes de qualquer "
    "coisa gosta de entender quem tá do outro lado, " + _PERGUNTA
)

_REPETIDA = "ah, entendi\n\nque pena que a cafeteria fechou\n\ne me conta, o " + _PERGUNTA
_CORRIGIDA = (
    "entendi, você fechou a cafeteria\n\n"
    "e hoje na sua casa, continua tomando um café especial?"
)

_USER_TEXT = "Eu tinha uma cafeteria mas fechei."


def _make_response(content):
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    msg.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


def _conversation():
    return {
        "id": "conv-luciano",
        "stage": "secretaria",
        "leads": {"id": "lead-luciano", "name": "Luciano", "phone": "5551999847567", "ai_enabled": True},
    }


def _history():
    base = {"stage": "secretaria", "wamid": None, "quoted_wamid": None, "message_type": "text", "metadata": None}
    return [
        {**base, "role": "assistant", "content": _OPENER, "created_at": "2026-07-08T22:58:51Z"},
        {**base, "role": "user", "content": "Sou o Luciano mas não tenho mais a cafeteria.", "created_at": "2026-07-08T22:58:32Z"},
        {**base, "role": "user", "content": _USER_TEXT, "created_at": "2026-07-08T23:00:55Z"},
    ]


@pytest.mark.asyncio
async def test_pergunta_repetida_dispara_regeneracao_corretiva():
    from app.agent.orchestrator import run_agent

    calls = {"n": 0}
    responses = [_make_response(_REPETIDA), _make_response(_CORRIGIDA)]

    async def fake_create(**kwargs):
        resp = responses[calls["n"]]
        calls["n"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=_history()), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-luciano", "ai_enabled": True}), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation(), _USER_TEXT)

    assert calls["n"] == 2, "deve ter feito exatamente UMA regeneração corretiva"
    assert "continua tomando um café especial" in result
    assert "prazer do dia a dia" not in result


@pytest.mark.asyncio
async def test_correcao_ainda_repetida_envia_mesmo_assim():
    """Fail-open: se a regeneração também repetir, entrega o texto (nunca silêncio)."""
    from app.agent.orchestrator import run_agent

    calls = {"n": 0}
    responses = [_make_response(_REPETIDA), _make_response(_REPETIDA)]

    async def fake_create(**kwargs):
        resp = responses[calls["n"]]
        calls["n"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=_history()), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-luciano", "ai_enabled": True}), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation(), _USER_TEXT)

    assert calls["n"] == 2
    assert result, "fail-open: melhor repetir do que fantasmar o lead"


@pytest.mark.asyncio
async def test_pergunta_inedita_nao_regenera():
    from app.agent.orchestrator import run_agent

    calls = {"n": 0}

    async def fake_create(**kwargs):
        calls["n"] += 1
        return _make_response(_CORRIGIDA)

    with patch("app.agent.orchestrator.get_history", return_value=_history()), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-luciano", "ai_enabled": True}), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation(), _USER_TEXT)

    assert calls["n"] == 1, "sem repetição não há chamada extra"
    assert "continua tomando um café especial" in result
