"""Fix 2: o processor sincroniza a persona efetiva na conversa (display do frontend).

Sem isso, o frontend lia o pin estático agent_profile_id (escolha do broadcast) e mostrava
outbound enquanto o backend rodava inbound — a "mentira visual". Agora a persona realmente
resolvida é gravada na conversa a cada turno (fail-soft).
"""
from unittest.mock import patch

from app.buffer import processor


def test_sync_grava_quando_persona_muda():
    calls = {}

    def _fake_update(conv_id, **fields):
        calls["conv_id"] = conv_id
        calls["fields"] = fields

    conv = {"id": "conv-1", "agent_persona": None}
    with patch("app.buffer.processor.update_conversation", side_effect=_fake_update):
        processor._sync_conversation_persona(conv, "valeria_outbound")

    assert calls["conv_id"] == "conv-1"
    assert calls["fields"] == {"agent_persona": "valeria_outbound"}
    assert conv["agent_persona"] == "valeria_outbound"  # atualiza o dict em memória


def test_sync_nao_regrava_quando_persona_igual():
    conv = {"id": "conv-1", "agent_persona": "valeria_outbound"}
    with patch("app.buffer.processor.update_conversation") as mock_upd:
        processor._sync_conversation_persona(conv, "valeria_outbound")
    mock_upd.assert_not_called()


def test_sync_failsoft_em_erro_de_escrita():
    # ex.: coluna ainda não existe no schema (PGRST) — não pode quebrar o processamento
    conv = {"id": "conv-1", "agent_persona": None}
    with patch("app.buffer.processor.update_conversation", side_effect=RuntimeError("PGRST204")):
        processor._sync_conversation_persona(conv, "valeria_inbound")  # não levanta
