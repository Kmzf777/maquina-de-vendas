"""Tests for WhatsApp 24h window tracking in the meta webhook handler."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.webhook.meta_router import _track_inbound_message_time, _mark_read_bg, router as meta_router

META_PAYLOAD = {
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "messages": [
                            {
                                "from": "553496654020",
                                "id": "wamid.test123",
                                "text": {"body": "Oi, quero informações"},
                                "type": "text",
                            }
                        ],
                        "metadata": {"phone_number_id": "PHONE_ID"},
                    }
                }
            ]
        }
    ]
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


# --- unit tests for _track_inbound_message_time ---

def test_track_inbound_message_time_updates_lead():
    """Must call supabase update with the correct phone and a non-null timestamp."""
    mock_sb = MagicMock()
    with patch("app.webhook.meta_router.get_supabase", return_value=mock_sb):
        _track_inbound_message_time("553496654020")

    mock_sb.table.assert_called_with("leads")
    update_payload = mock_sb.table.return_value.update.call_args.args[0]
    assert "last_customer_message_at" in update_payload
    assert update_payload["last_customer_message_at"] is not None
    mock_sb.table.return_value.update.return_value.eq.assert_called_with("phone", "5534996654020")


def test_track_inbound_message_time_swallows_exceptions():
    """Must not propagate exceptions — silently log and continue."""
    with patch("app.webhook.meta_router.get_supabase", side_effect=Exception("DB down")):
        _track_inbound_message_time("553496654020")  # should not raise


def test_track_inbound_message_time_supabase_failure_swallowed():
    """Even if the table().update() chain raises, the function must not propagate."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.side_effect = RuntimeError("connection lost")
    with patch("app.webhook.meta_router.get_supabase", return_value=mock_sb):
        _track_inbound_message_time("553496654020")  # should not raise


# --- integration tests: webhook handler schedules the background task ---

def test_meta_webhook_schedules_window_tracking_for_inbound_message(meta_client):
    """Every normal inbound meta message must schedule _track_inbound_message_time."""
    with (
        patch("app.webhook.meta_router.get_channel_by_provider_config", return_value=FAKE_META_CHANNEL),
        patch("app.webhook.meta_router.get_provider") as mock_provider,
        patch("app.webhook.meta_router.push_to_buffer", new_callable=AsyncMock),
        patch("app.webhook.meta_router.get_dev_route", new_callable=AsyncMock, return_value=None),
        patch("app.webhook.meta_router._track_inbound_message_time") as mock_track,
    ):
        response = meta_client.post(
            "/webhook/meta",
            content=json.dumps(META_PAYLOAD),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 200
        mock_track.assert_called_once_with("553496654020")


def test_meta_webhook_no_tracking_for_resetar_command(meta_client):
    """!resetar command skips both tracking and buffer — window timestamp must not be touched."""
    resetar_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "553496654020",
                                    "id": "wamid.resetar",
                                    "text": {"body": "!resetar"},
                                    "type": "text",
                                }
                            ],
                            "metadata": {"phone_number_id": "PHONE_ID"},
                        }
                    }
                ]
            }
        ]
    }

    with (
        patch("app.webhook.meta_router.get_channel_by_provider_config", return_value=FAKE_META_CHANNEL),
        patch("app.webhook.meta_router.get_provider") as mock_provider,
        patch("app.webhook.meta_router.push_to_buffer", new_callable=AsyncMock) as mock_push,
        patch("app.webhook.meta_router.get_dev_route", new_callable=AsyncMock, return_value=None),
        patch("app.webhook.meta_router.get_or_create_lead", return_value={"id": "lead-1"}),
        patch("app.webhook.meta_router.reset_lead"),
        patch("app.webhook.meta_router._track_inbound_message_time") as mock_track,
    ):
        mock_provider.return_value.send_text = AsyncMock()

        response = meta_client.post(
            "/webhook/meta",
            content=json.dumps(resetar_payload),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 200
        mock_track.assert_not_called()
        mock_push.assert_not_called()


def test_meta_webhook_tracks_multiple_messages_in_one_payload(meta_client):
    """If the payload contains multiple messages, each must schedule its own tracking call."""
    multi_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "5511111111111",
                                    "id": "wamid.msg1",
                                    "text": {"body": "primeira"},
                                    "type": "text",
                                },
                                {
                                    "from": "5522222222222",
                                    "id": "wamid.msg2",
                                    "text": {"body": "segunda"},
                                    "type": "text",
                                },
                            ],
                            "metadata": {"phone_number_id": "PHONE_ID"},
                        }
                    }
                ]
            }
        ]
    }

    with (
        patch("app.webhook.meta_router.get_channel_by_provider_config", return_value=FAKE_META_CHANNEL),
        patch("app.webhook.meta_router.get_provider") as mock_provider,
        patch("app.webhook.meta_router.push_to_buffer", new_callable=AsyncMock),
        patch("app.webhook.meta_router.get_dev_route", new_callable=AsyncMock, return_value=None),
        patch("app.webhook.meta_router._track_inbound_message_time") as mock_track,
    ):
        meta_client.post(
            "/webhook/meta",
            content=json.dumps(multi_payload),
            headers={"content-type": "application/json"},
        )

        assert mock_track.call_count == 2
        called_phones = {c.args[0] for c in mock_track.call_args_list}
        assert called_phones == {"5511111111111", "5522222222222"}


# --- tests for _mark_read_bg background task ---

@pytest.mark.anyio
async def test_mark_read_bg_calls_provider():
    """_mark_read_bg must build a provider and call mark_read with the message_id."""
    mock_provider = AsyncMock()
    channel = {"provider": "meta_cloud", "provider_config": {}}
    with patch("app.webhook.meta_router.get_provider", return_value=mock_provider):
        await _mark_read_bg(channel, "wamid.abc123")
    mock_provider.mark_read.assert_awaited_once_with("wamid.abc123")


@pytest.mark.anyio
async def test_mark_read_bg_swallows_exceptions():
    """_mark_read_bg must not propagate exceptions when get_provider raises — only log a warning."""
    channel = {"provider": "meta_cloud", "provider_config": {}}
    with patch("app.webhook.meta_router.get_provider", side_effect=RuntimeError("network error")):
        await _mark_read_bg(channel, "wamid.fail")  # must not raise


@pytest.mark.anyio
async def test_mark_read_bg_swallows_mark_read_exception():
    """_mark_read_bg must not propagate exceptions when provider.mark_read raises — only log."""
    mock_provider = AsyncMock()
    mock_provider.mark_read = AsyncMock(side_effect=RuntimeError("mark_read failed"))
    channel = {"provider": "meta_cloud", "provider_config": {}}
    with patch("app.webhook.meta_router.get_provider", return_value=mock_provider):
        await _mark_read_bg(channel, "wamid.fail_mark_read")  # must not raise
    mock_provider.mark_read.assert_awaited_once_with("wamid.fail_mark_read")


def test_meta_webhook_schedules_mark_read_as_background_task(meta_client):
    """Verify that _mark_read_bg is SCHEDULED via BackgroundTasks.add_task, not awaited inline.

    Patching _mark_read_bg directly and asserting it was called is not sufficient proof of
    scheduling: FastAPI's TestClient runs background tasks synchronously, so the assertion
    would also pass if the code awaited _mark_read_bg inline.

    Instead, we patch BackgroundTasks.add_task itself and assert that one of its calls
    registered _mark_read_bg (the patched mock object the production code references) with
    the expected (channel, message_id) arguments. If the production code switched to an
    inline await, _mark_read_bg would never appear in add_task's call list and this test
    would fail.

    Note: add_task is also used for _register_lead, _track_inbound_message_time, log_inbound,
    and _handle_delivery_status; we only assert that _mark_read_bg is among the registered
    callables.
    """
    with (
        patch("app.webhook.meta_router.get_channel_by_provider_config", return_value=FAKE_META_CHANNEL),
        patch("app.webhook.meta_router.push_to_buffer", new_callable=AsyncMock),
        patch("app.webhook.meta_router.get_dev_route", new_callable=AsyncMock, return_value=None),
        patch("app.webhook.meta_router._track_inbound_message_time"),
        patch("app.webhook.meta_router._mark_read_bg") as mock_mark_read_bg,
        patch("fastapi.BackgroundTasks.add_task") as mock_add_task,
    ):
        response = meta_client.post(
            "/webhook/meta",
            content=json.dumps(META_PAYLOAD),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 200

        # The production code calls background_tasks.add_task(_mark_read_bg, channel, message_id).
        # After patching, the name _mark_read_bg in the module namespace resolves to
        # mock_mark_read_bg.  So we check that add_task was called with that mock object
        # as the first positional arg and the correct (channel, message_id) following args.
        mark_read_calls = [
            call for call in mock_add_task.call_args_list
            if call.args and call.args[0] is mock_mark_read_bg
        ]
        assert len(mark_read_calls) == 1, (
            f"Expected exactly one add_task call with _mark_read_bg; got: {mock_add_task.call_args_list}"
        )
        _, channel_arg, message_id_arg = mark_read_calls[0].args
        assert channel_arg == FAKE_META_CHANNEL
        assert message_id_arg == "wamid.test123"
