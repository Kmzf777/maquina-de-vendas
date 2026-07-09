"""Resiliência da máscara no LLM-down — auditoria do outage 17:39–17:52 de 08/07.

Falhas reais:
- Fernanda respondeu "Não" e Letícia era um AUTORESPONDER de gelateria; ambas
  caíram no fallback e receberam "Perfeito! Seu atendimento agora será
  continuado pelo João..." — maiúsculas, "!", emoji e ponto final: a antítese
  da persona, no momento mais frágil.
- Nenhum alerta llm_down disparou (limiar fixo de 3 falhas consecutivas; houve 2
  em plena janela de disparo ativo).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent.tools import _HANDOFF_MSG

GELATO_AUTOREPLY = (
    "‎Duo Gelatto Nova Era agradece seu contato. \n\n"
    "Para entrega acesse os links abaixo:\n\n"
    "https://www.ifood.com.br/delivery/a\nhttps://www.ifood.com.br/delivery/b\n"
    "Para outros assuntos, continue por aqui."
)


def test_handoff_msg_na_voz_da_valeria():
    assert "Perfeito" not in _HANDOFF_MSG
    assert "!" not in _HANDOFF_MSG
    assert "👉" not in _HANDOFF_MSG
    assert _HANDOFF_MSG[0].islower(), "persona abre em minúscula"
    assert "wa.me/553491461669" in _HANDOFF_MSG, "o link do João é funcional e fica"


@pytest.mark.asyncio
async def test_llm_down_nao_encaminha_autoresponder(monkeypatch):
    from app.buffer import processor
    import app.agent.tools as tools_mod

    called = {}

    async def fake_exec(*a, **k):
        called["handoff"] = True

    monkeypatch.setattr(tools_mod, "execute_tool", fake_exec)
    monkeypatch.setattr(processor, "_record_llm_failure", AsyncMock(return_value=1))
    monkeypatch.setattr(processor, "_broadcast_recently_active", lambda: False)

    await processor._handle_llm_down(
        {"id": "L1"}, "5562998354407", {"id": "c1"}, inbound_text=GELATO_AUTOREPLY,
    )
    assert "handoff" not in called, "autoresponder nunca vira handoff pro João"


@pytest.mark.asyncio
async def test_llm_down_texto_humano_encaminha(monkeypatch):
    from app.buffer import processor
    import app.agent.tools as tools_mod

    called = {}

    async def fake_exec(*a, **k):
        called["handoff"] = True

    monkeypatch.setattr(tools_mod, "execute_tool", fake_exec)
    monkeypatch.setattr(processor, "_record_llm_failure", AsyncMock(return_value=1))
    monkeypatch.setattr(processor, "_broadcast_recently_active", lambda: False)

    await processor._handle_llm_down({"id": "L1"}, "5534999", {"id": "c1"}, inbound_text="Não")
    assert called.get("handoff") is True


@pytest.mark.asyncio
async def test_alerta_com_2_falhas_durante_disparo_ativo(monkeypatch):
    from app.buffer import processor
    import app.agent.tools as tools_mod

    fired = {}
    monkeypatch.setattr(tools_mod, "execute_tool", AsyncMock())
    monkeypatch.setattr(processor, "_record_llm_failure", AsyncMock(return_value=2))
    monkeypatch.setattr(processor, "_broadcast_recently_active", lambda: True)
    monkeypatch.setattr(processor, "_fire_llm_down_alert", lambda *a, **k: fired.setdefault("x", True))

    await processor._handle_llm_down({"id": "L1"}, "5534999", {"id": "c1"}, inbound_text="oi")
    assert fired.get("x") is True, "2 falhas em janela de disparo ativo devem alertar"


@pytest.mark.asyncio
async def test_sem_disparo_ativo_mantem_limiar_3(monkeypatch):
    from app.buffer import processor
    import app.agent.tools as tools_mod

    fired = {}
    monkeypatch.setattr(tools_mod, "execute_tool", AsyncMock())
    monkeypatch.setattr(processor, "_record_llm_failure", AsyncMock(return_value=2))
    monkeypatch.setattr(processor, "_broadcast_recently_active", lambda: False)
    monkeypatch.setattr(processor, "_fire_llm_down_alert", lambda *a, **k: fired.setdefault("x", True))

    await processor._handle_llm_down({"id": "L1"}, "5534999", {"id": "c1"}, inbound_text="oi")
    assert "x" not in fired, "fora de disparo, o limiar continua 3 (2 falhas não alertam)"
