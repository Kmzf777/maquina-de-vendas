"""Ponte pós-handoff: pergunta de negócio → AVISO DE RECEBIMENTO (escudo seguro).

Contrato ORIGINAL (11/07, casos Mateus/Leonardo): pergunta de negócio pós-handoff →
silêncio TOTAL, para não carimbar por cima da pergunta que o humano precisa ler.

Contrato ATUAL (auditoria 15/07, caso Itamar — "gostaria de visitar a produção, como
faço?" morreu em silêncio absoluto): o silêncio total deixava o lead sem NENHUM retorno,
100% dependente do SLA humano. Novo comportamento: aviso curto, NÃO-comercial, de
recebimento (_BRIDGE_ACK_TEXT) — não responde a pergunta (o humano ainda lê e responde),
só fecha o vácuo — com cooldown dedicado (bridge_ack, 1h) pra não martelar a cada
mensagem. Encerramento social (❤️), reação (silêncio) e vácuo puro (carimbo) intactos.
"""
from unittest.mock import patch

import pytest

from app.buffer import processor as P
from tests.test_processor_handoff_bridge_2026_07_03 import (
    _BridgeFakeRedis, _make_lead, _make_channel, _make_conversation, _make_provider,
)


# ---------------------------------------------------------------------------
# _looks_like_business_question (puro) — inalterado
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Qual o valor da unidade",
    "gostaria de saber o valor das sacas no grão",
    "quanto custa",
    "preço?",
    "?",
    "qual o pedido mínimo",
    "e o frete pra 38400-000",
    "Vocês exportam para os EUA?",
    "tá saindo mais caro do que no supermercado",
    "Gostaria de visitar a produção, como faço?",  # caso Itamar
])
def test_business_question_true(text):
    assert P._looks_like_business_question(text) is True


@pytest.mark.parametrize("text", [
    "obrigado",
    "boa tarde",
    "ok",
    "alô, tem alguém aí",
    "",
    None,
    "🙏",
])
def test_business_question_false(text):
    assert P._looks_like_business_question(text) is False


# ---------------------------------------------------------------------------
# _maybe_send_handoff_bridge: pergunta de negócio → aviso de recebimento
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bridge_pergunta_de_negocio_envia_aviso_de_recebimento():
    """Inbound "Qual o valor da unidade" com handoff formal → AVISO DE RECEBIMENTO
    (_BRIDGE_ACK_TEXT) enviado, SEM cartão, cooldown de ack consumido, marcador salvo."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="Qual o valor da unidade", inbound_wamid="wamid.LEAD-MATEUS",
            inbound_message_type="text",
        )

    assert sent is True
    provider.send_text.assert_awaited_once_with(lead["phone"], P._BRIDGE_ACK_TEXT)
    provider.send_contact.assert_not_awaited()
    provider.send_reaction.assert_not_awaited()
    # Cooldown de ack consumido (não o cooldown do carimbo, nem o de escalonamento).
    assert f"bridge_ack:{conversation['id']}" in fake_redis._strings
    assert f"bridge:{conversation['id']}" not in fake_redis._strings
    assert f"bridge_escalation:{conversation['id']}" not in fake_redis._strings
    # Bolha do aviso (assistant) + marcador system (QA).
    saved_roles = [c.args[2] for c in mock_save.call_args_list]
    assert "assistant" in saved_roles and "system" in saved_roles
    marker = next(c.args[3] for c in mock_save.call_args_list if c.args[2] == "system")
    assert "aviso de recebimento" in marker


@pytest.mark.asyncio
async def test_bridge_ack_em_cooldown_fica_em_silencio():
    """Segunda pergunta de negócio dentro da janela de 1h → silêncio (cooldown de ack)."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()
    fake_redis._strings[f"bridge_ack:{conversation['id']}"] = "1"  # janela já aberta

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message"):
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="e o pedido mínimo?", inbound_wamid="wamid.X",
            inbound_message_type="text",
        )

    assert sent is False
    provider.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_bridge_pergunta_de_negocio_save_message_falhando_fail_soft():
    """Persistência é telemetria: save_message levantando → não propaga (o texto pode até
    sair; o que não pode é quebrar o processor)."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message", side_effect=RuntimeError("db fora")):
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="quanto custa a saca?", inbound_wamid="wamid.LEAD-LEO",
            inbound_message_type="text",
        )  # não deve levantar

    assert sent is False  # save do texto falhou → sent não vira True; mas nada propaga


@pytest.mark.asyncio
async def test_bridge_vacuo_puro_continua_recebendo_carimbo():
    """Vácuo puro (sem "?" nem termo de negócio — casos fundadores Maycon/Juliana)
    → comportamento intacto: carimbo _BRIDGE_TEXT enviado, retorno True."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message"):
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="alô, tem alguém aí", inbound_wamid="wamid.LEAD-VACUO",
            inbound_message_type="text",
        )

    assert sent is True
    provider.send_text.assert_awaited_once_with(lead["phone"], P._BRIDGE_TEXT)
