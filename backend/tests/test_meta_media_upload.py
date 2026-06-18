import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.whatsapp.meta import MetaCloudClient

CONFIG = {
    "phone_number_id": "123456",
    "access_token": "test_token",
    "api_version": "v21.0",
}
FAKE_JPEG = b'\xff\xd8\xff' + b'\x00' * 20
FAKE_B64 = base64.b64encode(FAKE_JPEG).decode()


def _make_mock_resp(json_data: dict, success: bool = True):
    resp = MagicMock()
    resp.is_success = success
    resp.json = MagicMock(return_value=json_data)
    resp.raise_for_status = MagicMock()
    resp.status_code = 200 if success else 400
    resp.reason_phrase = "OK" if success else "Bad Request"
    resp.text = str(json_data)
    return resp


def _patch_httpx(responses: list):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=responses)
    return patch("app.whatsapp.meta.httpx.AsyncClient", return_value=mock_client), mock_client


@pytest.mark.anyio
async def test_upload_media_returns_media_id():
    client = MetaCloudClient(CONFIG)
    upload_resp = _make_mock_resp({"id": "media_abc123"})

    ctx, mock_http = _patch_httpx([upload_resp])
    with ctx:
        media_id = await client.upload_media(FAKE_JPEG, "image/jpeg")

    assert media_id == "media_abc123"
    call = mock_http.post.call_args
    assert "123456/media" in call.args[0]
    assert call.kwargs["data"]["messaging_product"] == "whatsapp"
    assert call.kwargs["data"]["type"] == "image/jpeg"
    assert "file" in call.kwargs["files"]


@pytest.mark.anyio
async def test_send_contact_builds_contacts_payload():
    """send_contact monta a mensagem tipo `contacts` e normaliza o telefone."""
    client = MetaCloudClient(CONFIG)
    client._post = AsyncMock(return_value={"messages": [{"id": "wamid.789"}]})

    result = await client.send_contact(
        "5511999999999", contact_name="João", contact_phone="55 (34) 9146-1669"
    )

    assert result["messages"][0]["id"] == "wamid.789"
    payload = client._post.call_args.args[0]
    assert payload["type"] == "contacts"
    assert payload["to"] == "5511999999999"
    contact = payload["contacts"][0]
    assert contact["name"]["formatted_name"] == "João"
    phone = contact["phones"][0]
    assert phone["phone"] == "+553491461669"  # dígitos normalizados, com '+'
    assert phone["wa_id"] == "553491461669"


@pytest.mark.anyio
async def test_send_contact_raises_when_meta_rejects():
    """Sem 'messages' na resposta (erro embutido da Meta), send_contact levanta."""
    client = MetaCloudClient(CONFIG)
    client._post = AsyncMock(return_value={"error": {"message": "invalid"}})
    with pytest.raises(RuntimeError):
        await client.send_contact("5511999999999", contact_name="João", contact_phone="553491461669")


@pytest.mark.anyio
async def test_upload_media_logs_error_on_failure():
    client = MetaCloudClient(CONFIG)
    error_resp = _make_mock_resp(
        {"error": {"message": "Invalid token", "code": 190}},
        success=False,
    )
    error_resp.raise_for_status = MagicMock(side_effect=Exception("HTTP 400"))

    ctx, _ = _patch_httpx([error_resp])
    with ctx, pytest.raises(Exception, match="HTTP 400"):
        await client.upload_media(FAKE_JPEG, "image/jpeg")


@pytest.mark.anyio
async def test_send_image_bytes_uses_media_id_not_data_url():
    client = MetaCloudClient(CONFIG)

    with patch.object(client, "upload_media", new_callable=AsyncMock, return_value="media_abc") as mock_upload, \
         patch.object(client, "_post", new_callable=AsyncMock, return_value={"messages": [{"id": "wamid_xyz"}]}) as mock_post:
        await client.send_image_bytes("5511999...", FAKE_JPEG, "image/jpeg", caption="Foto 1")

    mock_upload.assert_called_once_with(FAKE_JPEG, "image/jpeg")
    payload = mock_post.call_args[0][0]
    assert payload["image"]["id"] == "media_abc"
    assert payload["image"]["caption"] == "Foto 1"
    assert "link" not in payload["image"]


@pytest.mark.anyio
async def test_send_image_bytes_no_caption():
    client = MetaCloudClient(CONFIG)

    with patch.object(client, "upload_media", new_callable=AsyncMock, return_value="media_no_cap"), \
         patch.object(client, "_post", new_callable=AsyncMock, return_value={}) as mock_post:
        await client.send_image_bytes("5511999...", FAKE_JPEG, "image/jpeg")

    payload = mock_post.call_args[0][0]
    assert "caption" not in payload["image"]


@pytest.mark.anyio
async def test_send_image_base64_delegates_to_send_image_bytes():
    client = MetaCloudClient(CONFIG)

    with patch.object(client, "send_image_bytes", new_callable=AsyncMock, return_value={}) as mock_send:
        await client.send_image_base64("5511999...", FAKE_B64, "image/jpeg", caption="hello")

    mock_send.assert_called_once_with("5511999...", FAKE_JPEG, "image/jpeg", caption="hello")
