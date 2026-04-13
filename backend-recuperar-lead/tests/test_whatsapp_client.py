import pytest
import httpx

from app.whatsapp import client


@pytest.fixture
def mock_evolution_api(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "https://evo.test.com")
    monkeypatch.setenv("EVOLUTION_API_KEY", "test-key")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "test-instance")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")

    # Reset cached settings
    import app.config
    app.config._settings = None

    captured = {}

    async def fake_post(self, url, json=None, headers=None, **kwargs):
        captured["url"] = str(url)
        captured["json"] = json
        captured["headers"] = headers
        request = httpx.Request("POST", url)
        return httpx.Response(201, json={"key": {"id": "msg123"}}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return captured


async def test_send_text(mock_evolution_api):
    result = await client.send_text("5534999999999", "oi, tudo bem?")
    assert "/message/sendText/test-instance" in mock_evolution_api["url"]
    assert mock_evolution_api["json"]["number"] == "5534999999999"
    assert mock_evolution_api["json"]["text"] == "oi, tudo bem?"
    assert mock_evolution_api["headers"]["apikey"] == "test-key"


async def test_send_image(mock_evolution_api):
    result = await client.send_image("5534999999999", "https://img.com/cafe.jpg", "nosso cafe")
    assert "/message/sendMedia/test-instance" in mock_evolution_api["url"]
    assert mock_evolution_api["json"]["mediatype"] == "image"
    assert mock_evolution_api["json"]["caption"] == "nosso cafe"


async def test_mark_read(mock_evolution_api):
    result = await client.mark_read("msg123", "5534999999999@s.whatsapp.net")
    assert "/chat/markMessageAsRead/test-instance" in mock_evolution_api["url"]
    assert mock_evolution_api["json"]["readMessages"][0]["id"] == "msg123"
