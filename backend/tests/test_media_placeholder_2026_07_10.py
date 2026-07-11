"""describe_media_placeholder — Trilha A da auditoria inbound 10/07.

Mensagens de mídia enviadas pelo vendedor via CRM eram persistidas com
content="" (sem placeholder textual), cegando o histórico do LLM/dossiê/QA.
Este helper mapeia content vazio + message_type para um placeholder legível,
preservando content não-vazio intocado.
"""
import pytest

from app.conversations.service import describe_media_placeholder


@pytest.mark.parametrize(
    "row, expected",
    [
        # content não-vazio permanece intocado, seja qual for o message_type.
        ({"content": "oi tudo bem", "message_type": "text"}, "oi tudo bem"),
        ({"content": "oi tudo bem", "message_type": "audio"}, "oi tudo bem"),
        ({"content": "  oi  ", "message_type": None}, "  oi  "),
        # content vazio/None + message_type mapeado -> placeholder.
        ({"content": "", "message_type": "audio"}, "[áudio]"),
        ({"content": None, "message_type": "audio"}, "[áudio]"),
        ({"content": "   ", "message_type": "audio"}, "[áudio]"),
        ({"content": "", "message_type": "image"}, "[imagem]"),
        ({"content": "", "message_type": "video"}, "[vídeo]"),
        ({"content": "", "message_type": "document"}, "[documento]"),
        ({"content": "", "message_type": "sticker"}, "[sticker]"),
        ({"content": "", "message_type": "location"}, "[localização]"),
        ({"content": "", "message_type": "contact"}, "[contato]"),
        ({"content": "", "message_type": "contacts"}, "[contato]"),
        ({"content": "", "message_type": "reaction"}, "[mídia]"),  # tipo desconhecido não-text
        # content vazio + message_type ausente/None/"text" -> preserva original (comportamento atual).
        ({"content": "", "message_type": None}, ""),
        ({"content": "", "message_type": "text"}, ""),
        ({"content": "", "message_type": ""}, ""),
        ({"content": None, "message_type": "text"}, None),
        ({"content": "", "message_type": None}, ""),
        ({"content": ""}, ""),  # message_type ausente da row
        ({"content": None}, None),
    ],
)
def test_describe_media_placeholder(row, expected):
    assert describe_media_placeholder(row) == expected
