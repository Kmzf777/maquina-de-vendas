"""send_reaction no provider WhatsApp (item 3 do plano 11/07).

Meta Cloud: POST /{phone_number_id}/messages com type="reaction" e
reaction={message_id: wamid alvo, emoji}. Emoji vazio remove a reação.
Base: default não-suportado (mesmo padrão de send_contact) — Evolution herda.
Mock: loga e devolve mock_ok (rehearsal nunca envia de verdade).
"""
import pytest
from unittest.mock import AsyncMock


def _make_client():
    from app.whatsapp.meta import MetaCloudClient
    return MetaCloudClient({"phone_number_id": "123456", "access_token": "tok"})


@pytest.mark.asyncio
async def test_meta_send_reaction_payload():
    client = _make_client()
    client._post = AsyncMock(return_value={"messages": [{"id": "wamid.REACT1"}]})

    result = await client.send_reaction("5511999990000", "wamid.TARGET", "❤️")

    client._post.assert_awaited_once()
    payload = client._post.await_args.args[0]
    assert payload["messaging_product"] == "whatsapp"
    assert payload["to"] == "5511999990000"
    assert payload["type"] == "reaction"
    assert payload["reaction"] == {"message_id": "wamid.TARGET", "emoji": "❤️"}
    assert client._post.await_args.kwargs.get("request_type") == "send_reaction"
    assert result == {"messages": [{"id": "wamid.REACT1"}]}


@pytest.mark.asyncio
async def test_meta_send_reaction_requires_target_wamid():
    client = _make_client()
    client._post = AsyncMock()
    with pytest.raises(ValueError):
        await client.send_reaction("5511999990000", "", "❤️")
    client._post.assert_not_awaited()


@pytest.mark.asyncio
async def test_base_default_not_supported():
    from app.whatsapp.base import WhatsAppProvider

    class _Bare(WhatsAppProvider):
        async def send_text(self, to, body): ...
        async def send_image(self, to, image_url, caption=None): ...
        async def send_image_base64(self, to, base64_data, mimetype="image/jpeg", caption=None): ...
        async def send_audio(self, to, audio_url): ...
        async def send_template(self, to, template_name, components=None, language_code="pt_BR"): ...
        async def mark_read(self, message_id, remote_jid=""): ...

    with pytest.raises(NotImplementedError):
        await _Bare().send_reaction("551199", "wamid.X", "👍")


@pytest.mark.asyncio
async def test_mock_provider_send_reaction():
    from app.whatsapp.mock_provider import MockProvider
    result = await MockProvider({}).send_reaction("551199", "wamid.X", "👍")
    assert result.get("status") == "mock_ok"
    assert result.get("method") == "send_reaction"
