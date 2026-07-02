import pytest
from unittest.mock import patch

import app.agent.tools as tools


@pytest.mark.asyncio
async def test_enviar_fotos_nao_reenfileira_quando_ja_enviado():
    """When [enviar_fotos] marker exists in history, abort and don't re-enqueue batch."""
    from app.agent.tools import _deferred_media

    conv_id = "conv-1"
    lead_id = "lead-1"

    # Histórico já contém o marcador de fotos enviadas.
    history_com_fotos = [
        {"role": "system", "content": "[enviar_fotos] Fotos de atacado enviadas (5/5)"},
    ]

    # Garante fila limpa.
    _deferred_media.pop(conv_id, None)

    with patch("app.agent.tools.get_history", return_value=history_com_fotos), \
         patch("app.agent.tools.save_message"):
        result = await tools.execute_tool(
            "enviar_fotos",
            {"categoria": "atacado"},
            lead_id=lead_id,
            phone="5511999990000",
            conversation_id=conv_id,
        )

    # Não deve ter enfileirado nada.
    assert _deferred_media.get(conv_id) in (None, [])
    assert "ja" in result.lower() or "nao reenviar" in result.lower()
