"""Ponte pós-handoff: RECLAMAÇÃO do atendimento humano → escalona p/ gerência.

Auditoria 15/07 (caso Aislan): cliente com pedido fechado e não entregue, devolvido ao
mesmo gargalo (João) em silêncio para a gestão — "esse aí é um deles que me deixou várias
vezes sem me responder. vou agradecer por tudo!". Lead perdido, ninguém acima soube.

Novo comportamento: reclamação pós-handoff → alerta CRÍTICO à gerência
(create_system_alert → WhatsApp/Sentry/system_alerts) + aviso seguro ao lead
(_BRIDGE_ESCALATION_TEXT), com cooldown de 12h pra não spammar a gerência. Escalonamento
é fail-OPEN no Redis (perder uma reclamação é pior que um alerta duplicado raro).
"""
from unittest.mock import patch

import pytest

from app.buffer import processor as P
from tests.test_processor_handoff_bridge_2026_07_03 import (
    _BridgeFakeRedis, _make_lead, _make_channel, _make_conversation, _make_provider,
)


# ---------------------------------------------------------------------------
# _looks_like_complaint (puro)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "faz quase 1 ano que estou tentando negociar com vocês e não me enviaram nada",
    "Fiz perguntas aos vendedores e não me enviaram mais nada, visualizam e não respondem",
    "esse ai é um deles que me deixou varias vezes sem me responder",
    "paguei e não chegou até hoje",
    "que descaso, ninguém me responde",
    "fechei o pedido e não entregaram",
    "faz semanas tentando falar e ninguém me atende",
])
def test_complaint_true(text):
    assert P._looks_like_complaint(text) is True


@pytest.mark.parametrize("text", [
    "qual o valor da unidade?",       # pergunta de negócio normal, não reclamação
    "obrigado",
    "quero visitar a produção",
    "",
    None,
    "boa tarde, tudo bem?",
])
def test_complaint_false(text):
    assert P._looks_like_complaint(text) is False


# ---------------------------------------------------------------------------
# _maybe_send_handoff_bridge: reclamação → escalonamento + aviso
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bridge_reclamacao_escalona_e_avisa_o_lead():
    lead = _make_lead(name="Aislan")
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.create_system_alert") as mock_alert:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="esse ai é um deles que me deixou varias vezes sem me responder",
            inbound_wamid="wamid.AISLAN", inbound_message_type="text",
        )

    assert sent is True
    provider.send_text.assert_awaited_once_with(lead["phone"], P._BRIDGE_ESCALATION_TEXT)
    # Alerta crítico disparado à gerência.
    mock_alert.assert_called_once()
    assert mock_alert.call_args.kwargs["severity"] == "critical"
    assert mock_alert.call_args.kwargs["type"] == "lead_post_handoff_complaint"
    # Cooldown de escalonamento consumido; ack NÃO (reclamação não é pergunta comum).
    assert f"bridge_escalation:{conversation['id']}" in fake_redis._strings
    assert f"bridge_ack:{conversation['id']}" not in fake_redis._strings


@pytest.mark.asyncio
async def test_bridge_reclamacao_em_cooldown_nao_realerta():
    lead = _make_lead(name="Aislan")
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()
    fake_redis._strings[f"bridge_escalation:{conversation['id']}"] = "1"  # já escalado

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.create_system_alert") as mock_alert:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="continuam sem me responder, que descaso",
            inbound_wamid="wamid.X", inbound_message_type="text",
        )

    assert sent is False
    mock_alert.assert_not_called()
    provider.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_bridge_reclamacao_fail_open_no_redis_ainda_alerta():
    """Redis fora no cooldown de escalonamento → ainda dispara o alerta 1x (fail-OPEN)."""
    lead = _make_lead(name="Aislan")
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()

    class _BoomRedis(_BridgeFakeRedis):
        async def set(self, *a, **k):
            raise RuntimeError("redis fora")

    with patch("app.buffer.processor._get_buffer_redis", return_value=_BoomRedis()), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.create_system_alert") as mock_alert:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="visualizam e não respondem faz meses",
            inbound_wamid="wamid.Y", inbound_message_type="text",
        )

    assert sent is True
    mock_alert.assert_called_once()


@pytest.mark.asyncio
async def test_bridge_reclamacao_tem_precedencia_sobre_pergunta_de_negocio():
    """Uma reclamação que também contém "?" ou termo de negócio deve ESCALAR, não só ack."""
    lead = _make_lead(name="Aislan")
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.create_system_alert") as mock_alert:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="paguei e não chegou, cadê o meu pedido?",
            inbound_wamid="wamid.Z", inbound_message_type="text",
        )

    assert sent is True
    mock_alert.assert_called_once()
    provider.send_text.assert_awaited_once_with(lead["phone"], P._BRIDGE_ESCALATION_TEXT)
