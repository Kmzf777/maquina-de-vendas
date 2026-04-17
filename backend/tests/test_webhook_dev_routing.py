import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.webhook.router import router as evo_router

EVOLUTION_PAYLOAD = {
    "event": "messages.upsert",
    "instance": {"instanceName": "test-instance"},
    "data": {
        "key": {
            "remoteJid": "5511999999999@s.whatsapp.net",
            "fromMe": False,
            "id": "msg123",
        },
        "pushName": "Dev Tester",
        "message": {"conversation": "oi"},
        "messageType": "conversation",
        "messageTimestamp": 1764253714,
    },
}

FAKE_CHANNEL = {
    "id": "ch-test",
    "is_active": True,
    "provider": "evolution",
    "provider_config": {"instance": "test-instance"},
}


@pytest.fixture
def evo_client(fake_redis):
    app = FastAPI()
    app.include_router(evo_router)
    app.state.redis = fake_redis
    return TestClient(app, raise_server_exceptions=True)


def test_evolution_dev_number_skips_buffer_and_forwards(evo_client, fake_redis):
    """Dev-whitelisted sender: forward called, push_to_buffer not called."""
    with patch("app.webhook.router.get_channel_by_provider_config", return_value=FAKE_CHANNEL), \
         patch("app.webhook.router.get_provider") as mock_provider, \
         patch("app.webhook.router.push_to_buffer", new_callable=AsyncMock) as mock_push, \
         patch("app.webhook.router.is_dev_number", new_callable=AsyncMock, return_value=True), \
         patch("app.webhook.router.forward_to_dev", new_callable=AsyncMock) as mock_forward:

        mock_provider.return_value.mark_read = AsyncMock()

        response = evo_client.post(
            "/webhook/evolution",
            content=json.dumps(EVOLUTION_PAYLOAD),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_push.assert_not_called()
        mock_forward.assert_called_once()
        call_kwargs = mock_forward.call_args
        assert call_kwargs.kwargs["path"] == "/webhook/evolution"


def test_evolution_non_dev_number_processes_normally(evo_client, fake_redis):
    """Non-whitelisted sender: push_to_buffer called, forward not called."""
    with patch("app.webhook.router.get_channel_by_provider_config", return_value=FAKE_CHANNEL), \
         patch("app.webhook.router.get_provider") as mock_provider, \
         patch("app.webhook.router.push_to_buffer", new_callable=AsyncMock) as mock_push, \
         patch("app.webhook.router.is_dev_number", new_callable=AsyncMock, return_value=False), \
         patch("app.webhook.router.forward_to_dev", new_callable=AsyncMock) as mock_forward:

        mock_provider.return_value.mark_read = AsyncMock()

        response = evo_client.post(
            "/webhook/evolution",
            content=json.dumps(EVOLUTION_PAYLOAD),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 200
        mock_push.assert_called_once()
        mock_forward.assert_not_called()

from app.webhook.meta_router import router as meta_router

META_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "WABA_ID",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "PHONE_ID"},
                        "messages": [
                            {
                                "from": "5511999999999",
                                "id": "msg-meta-001",
                                "timestamp": "1764253714",
                                "type": "text",
                                "text": {"body": "ola pelo meta"},
                            }
                        ],
                    },
                    "field": "messages",
                }
            ],
        }
    ],
}

FAKE_META_CHANNEL = {
    "id": "ch-meta-test",
    "is_active": True,
    "provider": "meta_cloud",
    "provider_config": {"phone_number_id": "PHONE_ID", "app_secret": ""},
}


@pytest.fixture
def meta_client(fake_redis):
    app = FastAPI()
    app.include_router(meta_router)
    app.state.redis = fake_redis
    return TestClient(app, raise_server_exceptions=True)


def test_meta_dev_number_skips_buffer_and_forwards(meta_client):
    with patch("app.webhook.meta_router.get_channel_by_provider_config", return_value=FAKE_META_CHANNEL), \
         patch("app.webhook.meta_router.get_provider") as mock_provider, \
         patch("app.webhook.meta_router.push_to_buffer", new_callable=AsyncMock) as mock_push, \
         patch("app.webhook.meta_router.is_dev_number", new_callable=AsyncMock, return_value=True), \
         patch("app.webhook.meta_router.forward_to_dev", new_callable=AsyncMock) as mock_forward:

        mock_provider.return_value.mark_read = AsyncMock()

        response = meta_client.post(
            "/webhook/meta",
            content=json.dumps(META_PAYLOAD),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 200
        mock_push.assert_not_called()
        mock_forward.assert_called_once()
        assert mock_forward.call_args.kwargs["path"] == "/webhook/meta"


def test_meta_non_dev_number_processes_normally(meta_client):
    with patch("app.webhook.meta_router.get_channel_by_provider_config", return_value=FAKE_META_CHANNEL), \
         patch("app.webhook.meta_router.get_provider") as mock_provider, \
         patch("app.webhook.meta_router.push_to_buffer", new_callable=AsyncMock) as mock_push, \
         patch("app.webhook.meta_router.is_dev_number", new_callable=AsyncMock, return_value=False), \
         patch("app.webhook.meta_router.forward_to_dev", new_callable=AsyncMock) as mock_forward:

        mock_provider.return_value.mark_read = AsyncMock()

        response = meta_client.post(
            "/webhook/meta",
            content=json.dumps(META_PAYLOAD),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 200
        mock_push.assert_called_once()
        mock_forward.assert_not_called()
