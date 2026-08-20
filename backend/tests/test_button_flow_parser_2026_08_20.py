"""O clique tem que chegar ao bot como CLIQUE, não como texto.

Até aqui o parser transformava clique em texto puro e jogava fora o identificador
(meta_parser.py:138-151). Sem esse identificador não dá para distinguir um lead
que TOCOU no botão de um que DIGITOU a mesma frase — e é justamente essa
diferença que torna o bot determinístico.
"""
from app.webhook.meta_parser import parse_meta_webhook_payload


def _payload(mensagem: dict) -> dict:
    # `messaging_product` é obrigatório: o parser descarta o change sem ele.
    return {"entry": [{"changes": [{"value": {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "123"},
        "contacts": [{"wa_id": "5511999999999", "profile": {"name": "Fulano"}}],
        "messages": [{"from": "5511999999999", "id": "wamid.1",
                      "timestamp": "1700000000", **mensagem}],
    }}]}]}


def test_quick_reply_de_template_vira_clique_com_payload():
    msgs = parse_meta_webhook_payload(_payload({
        "type": "button",
        "button": {"payload": "Quero comprar agora", "text": "Quero comprar agora"},
    }))
    assert len(msgs) == 1
    assert msgs[0].type == "button"
    assert msgs[0].text == "Quero comprar agora"
    assert msgs[0].metadata == {"payload": "Quero comprar agora", "title": "Quero comprar agora"}


def test_button_reply_interativo_vira_clique_com_id():
    msgs = parse_meta_webhook_payload(_payload({
        "type": "interactive",
        "interactive": {"type": "button_reply",
                        "button_reply": {"id": "prazo_3m", "title": "Daqui a 3 meses"}},
    }))
    assert msgs[0].type == "button"
    assert msgs[0].metadata == {"payload": "prazo_3m", "title": "Daqui a 3 meses"}


def test_template_sem_payload_cai_no_texto_do_botao():
    """Defensivo: se a Meta omitir `payload`, o texto do botão serve de identidade."""
    msgs = parse_meta_webhook_payload(_payload({
        "type": "button", "button": {"text": "Não quero mais receber"},
    }))
    assert msgs[0].metadata["payload"] == "Não quero mais receber"


def test_list_reply_continua_texto():
    """Listas estão fora do escopo do bot — comportamento atual preservado."""
    msgs = parse_meta_webhook_payload(_payload({
        "type": "interactive",
        "interactive": {"type": "list_reply",
                        "list_reply": {"id": "x", "title": "Opção A"}},
    }))
    assert msgs[0].type == "text"
    assert msgs[0].text == "Opção A"


def test_texto_digitado_igual_ao_rotulo_nao_vira_clique():
    """A distinção que sustenta todo o determinismo do bot."""
    msgs = parse_meta_webhook_payload(_payload({
        "type": "text", "text": {"body": "Quero comprar agora"},
    }))
    assert msgs[0].type == "text"
    assert msgs[0].metadata is None
