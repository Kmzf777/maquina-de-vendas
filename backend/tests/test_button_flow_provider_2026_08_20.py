"""Envio de mensagem interativa com botões de resposta (Meta Cloud API).

Mesmo padrão dos outros métodos opcionais do provider (send_contact,
send_reaction): default não-suportado na base, implementação real na Meta e
uma versão de ensaio no mock.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.whatsapp.base import WhatsAppProvider
from app.whatsapp.meta import MetaCloudClient
from app.whatsapp.mock_provider import MockProvider

CONFIG = {"phone_number_id": "123", "access_token": "tok"}
BOTOES = [("prazo_1m", "Daqui a 1 mês"), ("prazo_3m", "Daqui a 3 meses")]


async def test_meta_monta_o_payload_interativo():
    client = MetaCloudClient(CONFIG)
    with patch.object(client, "_post", new=AsyncMock(return_value={"messages": [{"id": "w1"}]})) as post:
        await client.send_interactive_buttons("5511999999999", "Quando te chamo?", BOTOES)

    enviado = post.await_args.args[0]
    assert enviado["type"] == "interactive"
    assert enviado["interactive"]["type"] == "button"
    assert enviado["interactive"]["body"]["text"] == "Quando te chamo?"
    assert enviado["interactive"]["action"]["buttons"] == [
        {"type": "reply", "reply": {"id": "prazo_1m", "title": "Daqui a 1 mês"}},
        {"type": "reply", "reply": {"id": "prazo_3m", "title": "Daqui a 3 meses"}},
    ]


async def test_meta_identifica_a_chamada_na_auditoria():
    """request_type vira a linha do meta_audit — sem ele o envio some do log."""
    client = MetaCloudClient(CONFIG)
    with patch.object(client, "_post", new=AsyncMock(return_value={"messages": [{"id": "w1"}]})) as post:
        await client.send_interactive_buttons("5511999999999", "corpo", BOTOES)

    assert post.await_args.kwargs.get("request_type") == "send_interactive_buttons"


async def test_meta_rejeita_resposta_sem_messages():
    """Mesma defesa de send_text: a Meta devolve 200 com erro embutido."""
    client = MetaCloudClient(CONFIG)
    with patch.object(client, "_post", new=AsyncMock(return_value={"error": {"code": 131042}})):
        with pytest.raises(RuntimeError):
            await client.send_interactive_buttons("5511999999999", "corpo", BOTOES)


async def test_meta_recusa_mais_de_tres_botoes():
    client = MetaCloudClient(CONFIG)
    with pytest.raises(ValueError):
        await client.send_interactive_buttons(
            "5511999999999", "corpo",
            [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")],
        )


async def test_meta_recusa_lista_vazia():
    client = MetaCloudClient(CONFIG)
    with pytest.raises(ValueError):
        await client.send_interactive_buttons("5511999999999", "corpo", [])


async def test_base_devolve_nao_suportado():
    """Evolution (descontinuado) herda o default e não precisa implementar."""

    class _Nu(WhatsAppProvider):
        async def send_text(self, to, body): ...
        async def send_image(self, to, image_url, caption=None): ...
        async def send_image_base64(self, to, base64_data, mimetype="image/jpeg", caption=None): ...
        async def send_audio(self, to, audio_url): ...
        async def send_template(self, to, template_name, components=None, language_code="pt_BR"): ...
        async def mark_read(self, message_id, remote_jid=""): ...

    with pytest.raises(NotImplementedError):
        await _Nu().send_interactive_buttons("551199", "corpo", BOTOES)


async def test_mock_registra_o_envio(tmp_path, monkeypatch):
    """No ensaio o envio não sai — mas precisa aparecer no log, como os outros."""
    log = tmp_path / "rehearsal.jsonl"
    monkeypatch.setenv("REHEARSAL_LOG_PATH", str(log))

    res = await MockProvider({}).send_interactive_buttons("5511999999999", "corpo", BOTOES)

    assert res["status"] == "mock_ok"
    assert res["method"] == "send_interactive_buttons"
    entrada = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert entrada["method"] == "send_interactive_buttons"
    assert entrada["to"] == "5511999999999"
    assert entrada["buttons"] == [list(b) for b in BOTOES]
