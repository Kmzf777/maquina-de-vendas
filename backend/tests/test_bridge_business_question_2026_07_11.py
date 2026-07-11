"""Via do meio na ponte pós-handoff: pergunta de negócio → silêncio (S2, 11/07).

Auditoria 11/07 (casos Mateus/Leonardo): lead já transbordado pergunta "Qual o
valor da unidade" / "valor das sacas no grão" e a ponte respondia com o carimbo
estático (_BRIDGE_TEXT) + cartão — aborrece o lead e enterra a pergunta que o
humano deveria ler. Novo contrato: pergunta de negócio (qualquer "?" OU token do
vocabulário de negócio) → silêncio total + marcador system p/ QA, SEM consumir o
cooldown. Fail-safe por diretriz: na dúvida a mensagem fica intocada pro humano;
superabranger é aceitável (um silêncio a mais < um carimbo em cima de pergunta
de preço). Vácuo puro (sem "?" nem termo de negócio) segue recebendo o carimbo.
"""
from unittest.mock import patch

import pytest

from app.buffer import processor as P
from tests.test_processor_handoff_bridge_2026_07_03 import (
    _BridgeFakeRedis, _make_lead, _make_channel, _make_conversation, _make_provider,
)


# ---------------------------------------------------------------------------
# _looks_like_business_question (puro)
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
# _maybe_send_handoff_bridge: pergunta de negócio → silêncio total
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bridge_pergunta_de_negocio_silencio_total_com_marcador():
    """Inbound "Qual o valor da unidade" com handoff formal → NADA enviado (nem
    texto, nem cartão, nem reação), cooldown NÃO consumido (um vácuo puro logo
    depois ainda recebe a ponte) e marcador system persistido p/ QA."""
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

    assert sent is False
    provider.send_text.assert_not_awaited()
    provider.send_contact.assert_not_awaited()
    provider.send_reaction.assert_not_awaited()
    # Cooldown NÃO consumido: o return acontece ANTES do redis.set da ponte.
    assert f"bridge:{conversation['id']}" not in fake_redis._strings

    # Marcador system p/ QA/watchdog (mesma forma de chamada do cartão na ponte).
    assert mock_save.call_count == 1
    call = mock_save.call_args_list[0]
    assert call.args[0] == conversation["id"]
    assert call.args[1] == lead["id"]
    assert call.args[2] == "system"
    assert "pergunta de negócio" in call.args[3]
    assert call.args[4] == conversation["stage"]
    assert call.kwargs["sent_by"] == "bridge"


@pytest.mark.asyncio
async def test_bridge_pergunta_de_negocio_save_message_falhando_fail_soft():
    """Marcador é telemetria: save_message levantando → ainda retorna False sem
    propagar (nunca pode quebrar o fluxo do processor)."""
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

    assert sent is False
    provider.send_text.assert_not_awaited()
    provider.send_contact.assert_not_awaited()


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
