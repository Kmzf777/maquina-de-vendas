"""Clique em linha de lista é CLIQUE, não texto.

meta_parser.py rebaixava list_reply para texto (comentário: "Listas estão fora do
escopo do bot de botões — segue como texto"). Com a tela de entrada (4 opções) e a
de destino de exportação (6 mercados) sendo listas — Meta limita reply buttons a 3 —
o fluxo da ValerIA morreria na primeira tela: o toque viraria texto livre e o motor
responderia com nudge, em loop.

API real confirmada em test_button_flow_parser_2026_08_20.py:
`parse_meta_webhook_payload` (não `parse_meta_webhook`), e o objeto retornado usa
`.type` / `.metadata` (não `.message_type`).
"""
from app.webhook.meta_parser import parse_meta_webhook_payload


def _payload(mensagem: dict) -> dict:
    # `messaging_product` é obrigatório: o parser descarta o change sem ele.
    return {"entry": [{"changes": [{"value": {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "123"},
        "contacts": [{"wa_id": "5534988861441", "profile": {"name": "Fulano"}}],
        "messages": [{"from": "5534988861441", "id": "wamid.X",
                      "timestamp": "1700000000", **mensagem}],
    }}]}]}


def test_list_reply_vira_clique_com_id_no_payload():
    msgs = parse_meta_webhook_payload(_payload({
        "type": "interactive",
        "interactive": {
            "type": "list_reply",
            "list_reply": {"id": "negocio", "title": "Pro meu negócio",
                           "description": "revenda"},
        },
    }))
    assert len(msgs) == 1
    assert msgs[0].type == "button"
    assert msgs[0].metadata["payload"] == "negocio"
    assert msgs[0].metadata["title"] == "Pro meu negócio"


def test_list_reply_sem_id_cai_no_titulo():
    msgs = parse_meta_webhook_payload(_payload({
        "type": "interactive",
        "interactive": {"type": "list_reply", "list_reply": {"title": "Europa"}},
    }))
    assert msgs[0].metadata["payload"] == "Europa"


def test_button_reply_segue_igual():
    """Regressão: a recuperação depende deste caminho."""
    msgs = parse_meta_webhook_payload(_payload({
        "type": "interactive",
        "interactive": {"type": "button_reply",
                        "button_reply": {"id": "repor", "title": "Preciso repor"}},
    }))
    assert msgs[0].type == "button"
    assert msgs[0].metadata["payload"] == "repor"
