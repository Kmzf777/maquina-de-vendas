"""Filtro de intenção na ponte pós-handoff (item 2 do plano 11/07).

Auditoria 11/07: lead já transbordado manda "obrigado"/"OK obrigado"/"Ok, Deus
abençoe 🙏" e a ponte respondia com o texto de roteamento — ruído em cima de um
encerramento social. Agora: encerramento social → reação ❤️ (fail-soft, silêncio
em erro) e NUNCA o texto da ponte; reação inbound → silêncio; dúvida real →
ponte exatamente como antes.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.buffer import processor as P
from tests.test_processor_handoff_bridge_2026_07_03 import (
    _BridgeFakeRedis, _make_lead, _make_channel, _make_conversation, _make_provider,
)


# ---------------------------------------------------------------------------
# _is_social_closing (puro)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "obrigado",
    "Obrigada!",
    "muito obrigado",
    "OK obrigado",
    "Ok, Deus abençoe 🙏",
    "valeu",
    "vlw",
    "blz",
    "show",
    "👍",
    "🙏🙏",
    "obrigado pela atencao",
    "perfeito, obrigado",
    "tamo junto",
])
def test_social_closing_true(text):
    assert P._is_social_closing(text) is True


@pytest.mark.parametrize("text", [
    "obrigado, mas qual o preço?",
    "Tem algum problema vocês responderem?",
    "cade a resposta?",
    "?",
    "quando o João me chama?",
    "quero falar com o joão",
    "bom dia",
    "oi",
    "",
    None,
    "[imagem]",
    "[áudio]",
])
def test_social_closing_false(text):
    assert P._is_social_closing(text) is False


# ---------------------------------------------------------------------------
# _maybe_send_handoff_bridge com filtro de intenção
# ---------------------------------------------------------------------------

def _reaction_provider() -> AsyncMock:
    provider = _make_provider()
    provider.send_reaction = AsyncMock(return_value={"messages": [{"id": "wamid.react1"}]})
    return provider


@pytest.mark.asyncio
async def test_bridge_obrigado_reage_com_coracao_sem_texto():
    """Encerramento social com wamid → reação ❤️, sem texto da ponte, sem cartão;
    linha de reação persistida (message_type=reaction, metadata com alvo)."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _reaction_provider()
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="obrigado", inbound_wamid="wamid.LEAD1",
            inbound_message_type="text",
        )

    assert sent is False
    provider.send_reaction.assert_awaited_once_with(lead["phone"], "wamid.LEAD1", "❤️")
    provider.send_text.assert_not_awaited()
    provider.send_contact.assert_not_awaited()

    assert mock_save.call_count == 1
    call = mock_save.call_args_list[0]
    assert call.args[2] == "assistant"
    assert call.kwargs["message_type"] == "reaction"
    assert call.kwargs["metadata"] == {"emoji": "❤️", "target_wamid": "wamid.LEAD1"}
    assert call.kwargs["sent_by"] == "bridge"
    assert call.kwargs["wamid"] == "wamid.react1"
    # NÃO consome o cooldown da ponte: uma dúvida real logo depois ainda recebe o texto.
    assert f"bridge:{conversation['id']}" not in fake_redis._strings


@pytest.mark.asyncio
async def test_bridge_obrigado_reacao_falha_fica_em_silencio():
    """Janela 24h fechada / erro Meta na reação → silêncio total (fail-soft), sem
    cair de volta no texto da ponte."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _reaction_provider()
    provider.send_reaction = AsyncMock(side_effect=RuntimeError("(#131047) janela fechada"))
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="valeu", inbound_wamid="wamid.LEAD2",
            inbound_message_type="text",
        )

    assert sent is False
    provider.send_text.assert_not_awaited()
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_obrigado_sem_wamid_silencio():
    """Sem wamid do inbound não há alvo para reagir → silêncio (nunca o texto)."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _reaction_provider()
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="obrigado", inbound_wamid=None,
            inbound_message_type="text",
        )

    assert sent is False
    provider.send_reaction.assert_not_awaited()
    provider.send_text.assert_not_awaited()
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_reacao_inbound_silencio():
    """Lead reagiu a uma mensagem nossa pós-handoff → silêncio (a Meta rejeita
    reação-sobre-reação, e reação não é dúvida)."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _reaction_provider()
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="👍", inbound_wamid="wamid.LEAD3",
            inbound_message_type="reaction",
        )

    assert sent is False
    provider.send_reaction.assert_not_awaited()
    provider.send_text.assert_not_awaited()
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_duvida_real_segue_enviando_texto():
    """Vácuo puro → comportamento intacto: texto da ponte + cartão.

    Mudança de contrato (S2, 11/07): o inbound original deste teste era
    "e o orçamento que pedi?" — sob o novo contrato isso é pergunta de negócio
    ("?" + token "orcamento") e agora SILENCIA para o humano ler (ver
    test_bridge_business_question_2026_07_11.py). O carimbo ficou reservado ao
    vácuo puro (sem "?" nem termo de negócio), então o inbound aqui virou um.
    """
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _reaction_provider()
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message"):
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="alô, tem alguém aí", inbound_wamid="wamid.LEAD4",
            inbound_message_type="text",
        )

    assert sent is True
    provider.send_reaction.assert_not_awaited()
    provider.send_text.assert_awaited_once_with(lead["phone"], P._BRIDGE_TEXT)


@pytest.mark.asyncio
async def test_bridge_provider_sem_send_reaction_fail_soft():
    """Provider que não implementa send_reaction (Evolution herda o default do
    base) → NotImplementedError vira silêncio, nunca exceção nem texto."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    provider.send_reaction = AsyncMock(side_effect=NotImplementedError("não suporta"))
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
            inbound_text="obrigado", inbound_wamid="wamid.LEAD5",
            inbound_message_type="text",
        )

    assert sent is False
    provider.send_text.assert_not_awaited()
    mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Wiring: gate ai_enabled passa o contexto do inbound à ponte
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_processor_gate_obrigado_reage_e_nao_manda_ponte():
    from unittest.mock import MagicMock
    from tests.test_processor_handoff_bridge_2026_07_03 import _sb_mock

    lead = _make_lead()
    channel = _make_channel()
    conversation = _make_conversation()
    provider = _reaction_provider()
    fake_redis = _BridgeFakeRedis()

    P_ = "app.buffer.processor."
    with patch(P_ + "get_or_create_lead", return_value=lead), \
         patch(P_ + "get_channel_by_id", return_value=channel), \
         patch(P_ + "get_provider", return_value=provider), \
         patch(P_ + "get_or_create_conversation", return_value=conversation), \
         patch(P_ + "get_active_enrollment", return_value=None), \
         patch(P_ + "save_message") as mock_save, \
         patch(P_ + "run_agent") as mock_agent, \
         patch(P_ + "_is_recent_duplicate", return_value=False), \
         patch(P_ + "get_supabase", return_value=_sb_mock()), \
         patch(P_ + "_get_buffer_redis", return_value=fake_redis), \
         patch(P_ + "_update_last_msg"):

        await P.process_buffered_messages(
            lead["phone"], "OK obrigado", channel["id"], wamid="wamid.INBOUND9",
        )

    mock_agent.assert_not_called()
    provider.send_reaction.assert_awaited_once_with(lead["phone"], "wamid.INBOUND9", "❤️")
    provider.send_text.assert_not_awaited()
    # user message + linha da reação
    assert mock_save.call_count == 2
    assert mock_save.call_args_list[0].args[2] == "user"
    assert mock_save.call_args_list[1].kwargs.get("message_type") == "reaction"
