"""Testes unitários para payload builders do outbound rehearsal runner."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_build_button_reply_payload_structure():
    from scripts.outbound_rehearsal_runner import _build_button_reply_payload

    phone = "5511900000001"
    payload = _build_button_reply_payload(phone, "sim", "Sim")

    entry = payload["entry"][0]
    change = entry["changes"][0]["value"]
    msg = change["messages"][0]

    assert payload["object"] == "whatsapp_business_account"
    assert change["contacts"][0]["wa_id"] == phone
    assert msg["from"] == phone
    assert msg["type"] == "interactive"
    assert msg["interactive"]["type"] == "button_reply"
    assert msg["interactive"]["button_reply"]["id"] == "sim"
    assert msg["interactive"]["button_reply"]["title"] == "Sim"


def test_build_text_payload_structure():
    from scripts.outbound_rehearsal_runner import _build_text_payload

    phone = "5511900000002"
    payload = _build_text_payload(phone, "oi quem é?? café??")

    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    assert msg["type"] == "text"
    assert msg["text"]["body"] == "oi quem é?? café??"


def test_build_first_message_payload_button():
    from scripts.outbound_rehearsal_runner import _build_first_message_payload

    phone = "5511900000003"
    first_message = {"type": "button_reply", "button_id": "nao", "button_title": "Não"}
    payload = _build_first_message_payload(phone, first_message)

    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    assert msg["type"] == "interactive"
    assert msg["interactive"]["button_reply"]["id"] == "nao"


def test_build_first_message_payload_text():
    from scripts.outbound_rehearsal_runner import _build_first_message_payload

    phone = "5511900000004"
    payload = _build_first_message_payload(phone, "oi quem é??")

    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    assert msg["type"] == "text"
    assert msg["text"]["body"] == "oi quem é??"


def test_build_outbound_template_payload():
    """Verifica estrutura do payload do template de disparo inicial."""
    from scripts.outbound_rehearsal_runner import build_outbound_template_payload

    phone = "5511900000005"
    payload = build_outbound_template_payload(phone)

    assert payload["messaging_product"] == "whatsapp"
    assert payload["to"] == phone
    assert payload["type"] == "template"
    tmpl = payload["template"]
    assert tmpl["name"] == "utilidade_22_04_2026_16_40"
    assert tmpl["language"]["code"] == "en"

    components = tmpl.get("components", [])
    button_component = next((c for c in components if c["type"] == "button"), None)
    assert button_component is not None, "Nenhum component de botão encontrado"
    buttons = button_component.get("buttons", [])
    assert len(buttons) == 3
    titles = [b["text"] for b in buttons]
    assert "Sim" in titles
    assert "Não" in titles
    assert "Parar mensagens" in titles
