"""Gate de reação isolada (forense 11/07, caso Anderson 5511987506497).

Reação inbound (🙏) atravessava o buffer como mensagem normal e rodava run_agent
completo — a IA emitia um turno de venda novo sem o lead ter dito nada ("falando
sozinha"). Agora: reação ISOLADA é persistida no histórico e alimenta o contexto
dos próximos turnos, mas NÃO engatilha turno de IA. Texto + reação coalescidos
seguem rodando o agente normalmente (há pergunta real no pacote).
"""
from unittest.mock import patch

import pytest

from app.buffer import processor as P
from tests.test_processor_handoff_bridge_2026_07_03 import (
    _make_channel, _make_conversation, _make_lead, _make_provider, _sb_mock,
)


# ---------------------------------------------------------------------------
# _is_reaction_only_turn (puro)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,mtype,expected", [
    ("[reagiu com 🙏🏻]", "reaction", True),
    ("[reagiu com 👍]", "reaction", True),
    ("", "reaction", True),                      # decode da reação falhou → ainda é só reação
    ("adorei! [reagiu com 👍]", "reaction", False),  # coalescida com texto → turno normal
    ("[reagiu com 👍] e o preço?", "reaction", False),
    ("[reagiu com 👍]", "text", False),           # texto literal do lead, não reação
    ("oi", "text", False),
    ("oi", None, False),
])
def test_is_reaction_only_turn(text, mtype, expected):
    assert P._is_reaction_only_turn(text, mtype) is expected


# ---------------------------------------------------------------------------
# Integração: reação isolada não roda a IA (lead com IA LIGADA)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reacao_isolada_salva_mensagem_mas_nao_roda_agente():
    lead = _make_lead(ai_enabled=True, human_control=False)
    channel = _make_channel()
    conversation = _make_conversation()
    provider = _make_provider()

    # Payload como chega do buffer: marcador meta_b64 de reaction (mesmo formato
    # que o webhook enfileira e _resolve_media decodifica).
    import base64 as _b64
    import json as _json
    meta_payload = _b64.b64encode(_json.dumps(
        {"emoji": "🙏🏻", "target_wamid": "wamid.ALVO"}
    ).encode()).decode()
    combined_text = f"[reaction: meta_b64={meta_payload}]"

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
         patch(P_ + "_update_last_msg") as mock_update_last:

        await P.process_buffered_messages(
            lead["phone"], combined_text, channel["id"], wamid="wamid.REACT_IN",
        )

    mock_agent.assert_not_called()
    provider.send_text.assert_not_awaited()
    # A reação É persistida (contexto p/ CRM e próximos turnos), com o tipo certo.
    assert mock_save.call_count == 1
    save_call = mock_save.call_args_list[0]
    assert save_call.args[2] == "user"
    assert save_call.kwargs.get("message_type") == "reaction"
    mock_update_last.assert_called_once_with(conversation["id"])
