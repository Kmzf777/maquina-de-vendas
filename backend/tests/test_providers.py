import pytest
import httpx
import respx
from app.providers.meta_cloud import MetaCloudProvider, HTTPX_TIMEOUT


def _make_meta_provider():
    return MetaCloudProvider({
        "phone_number_id": "12345678901234567",
        "access_token": "EAABs_test_token",
        "api_version": "v21.0",
    })


def test_httpx_timeout_constante_definida():
    """HTTPX_TIMEOUT deve existir como constante no módulo."""
    assert HTTPX_TIMEOUT is not None
    assert isinstance(HTTPX_TIMEOUT, httpx.Timeout)
    # Connect timeout <= 10s
    assert HTTPX_TIMEOUT.connect <= 10.0
    # Read timeout deve estar definido (não None/infinito)
    assert HTTPX_TIMEOUT.read is not None
    assert HTTPX_TIMEOUT.read <= 60.0


@respx.mock
async def test_send_text_usa_bearer_token():
    provider = _make_meta_provider()
    route = respx.post(
        "https://graph.facebook.com/v21.0/12345678901234567/messages"
    ).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.123"}]}))

    await provider.send_text("5511999999999", "Olá!")

    assert route.called
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer EAABs_test_token"


@respx.mock
async def test_download_media_nao_envia_bearer_para_cdn():
    """A requisição à CDN não deve incluir o header Authorization."""
    provider = _make_meta_provider()
    media_id = "media_abc123"

    # Mock: primeira chamada resolve media_id → URL
    respx.get(f"https://graph.facebook.com/v21.0/{media_id}").mock(
        return_value=httpx.Response(200, json={
            "url": "https://mmg.whatsapp.net/v/t62/some-signed-cdn-url",
            "mime_type": "audio/ogg",
        })
    )
    # Mock: segunda chamada baixa da CDN
    cdn_route = respx.get("https://mmg.whatsapp.net/v/t62/some-signed-cdn-url").mock(
        return_value=httpx.Response(200, content=b"audio_bytes", headers={"content-type": "audio/ogg"})
    )

    content, mime = await provider.download_media(media_id)

    assert content == b"audio_bytes"
    assert mime == "audio/ogg"
    cdn_request = cdn_route.calls[0].request
    # CDN NÃO deve receber Authorization header
    assert "authorization" not in {k.lower() for k in cdn_request.headers.keys()}


@respx.mock
async def test_mark_read_usa_bearer_token():
    provider = _make_meta_provider()
    respx.post(
        "https://graph.facebook.com/v21.0/12345678901234567/messages"
    ).mock(return_value=httpx.Response(200, json={}))

    await provider.mark_read("wamid.test123")

    request = respx.calls[0].request
    assert request.headers["Authorization"] == "Bearer EAABs_test_token"
