"""Motivo da falha da Meta gravado na mensagem (cartão 7c6b70e7, 06/11/2026).

O webhook de status 'failed' traz errors[] (ex.: 131026 "Message undeliverable"), mas
só o caminho de broadcast guardava o erro. Mensagens do vendedor ficavam com o ícone
vermelho sem motivo. Agora qualquer 'failed' grava metadata.delivery_error, com merge
(sem apagar metadata.interativo etc.).
"""
from unittest.mock import MagicMock, patch

import pytest

ERR_131026 = {
    "code": 131026,
    "title": "Message undeliverable",
    "message": "Message undeliverable",
    "error_data": {"details": "Message Undeliverable."},
}


def _sb_with_row(row):
    sb = MagicMock()
    msgs = MagicMock()
    sel = msgs.select.return_value.eq.return_value.limit.return_value.execute
    sel.return_value = MagicMock(data=[row] if row else [])
    sb.table.return_value = msgs
    return sb, msgs


def test_record_delivery_error_merges_into_existing_metadata():
    from app.webhook.meta_router import _record_delivery_error
    sb, msgs = _sb_with_row({"id": "m1", "metadata": {"interativo": {"tipo": "botoes"}}})
    assert _record_delivery_error(sb, "wamid.X", [ERR_131026], "1793988307") is True
    payload = msgs.update.call_args[0][0]
    md = payload["metadata"]
    assert md["interativo"] == {"tipo": "botoes"}
    assert md["delivery_error"]["code"] == 131026
    assert md["delivery_error"]["title"] == "Message undeliverable"
    assert md["delivery_error"]["details"] == "Message Undeliverable."
    assert md["delivery_error"]["at"].startswith("2026-11-06T")
    msgs.update.return_value.eq.assert_called_with("id", "m1")


def test_record_delivery_error_null_metadata():
    from app.webhook.meta_router import _record_delivery_error
    sb, msgs = _sb_with_row({"id": "m1", "metadata": None})
    assert _record_delivery_error(sb, "wamid.X", [ERR_131026], None) is True
    assert msgs.update.call_args[0][0]["metadata"]["delivery_error"]["code"] == 131026


def test_record_delivery_error_row_missing_returns_false():
    from app.webhook.meta_router import _record_delivery_error
    sb, msgs = _sb_with_row(None)
    assert _record_delivery_error(sb, "wamid.X", [ERR_131026], None) is False
    msgs.update.assert_not_called()


def test_record_delivery_error_without_errors_is_noop():
    from app.webhook.meta_router import _record_delivery_error
    sb, msgs = _sb_with_row({"id": "m1", "metadata": {}})
    assert _record_delivery_error(sb, "wamid.X", [], None) is True
    msgs.update.assert_not_called()


@pytest.mark.asyncio
async def test_handle_failed_records_error():
    from app.webhook import meta_router
    sb = MagicMock()
    with patch.object(meta_router, "get_supabase", return_value=sb), \
         patch.object(meta_router, "_apply_message_status", return_value=True), \
         patch.object(meta_router, "_record_delivery_error", return_value=True) as rec, \
         patch("app.broadcast.service.find_broadcast_lead_by_wamid", return_value=None):
        await meta_router._handle_delivery_status("wamid.X", "failed", [ERR_131026], "5537932140027")
    rec.assert_called_once()
    assert rec.call_args[0][1] == "wamid.X"


@pytest.mark.asyncio
async def test_handle_delivered_does_not_record_error():
    from app.webhook import meta_router
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    with patch.object(meta_router, "get_supabase", return_value=sb), \
         patch.object(meta_router, "_apply_message_status", return_value=True), \
         patch.object(meta_router, "_record_delivery_error") as rec, \
         patch("app.broadcast.service.find_broadcast_lead_by_wamid", return_value=None):
        await meta_router._handle_delivery_status("wamid.X", "delivered", [], "553732140027")
    rec.assert_not_called()


@pytest.mark.asyncio
async def test_handle_failed_row_missing_schedules_retry():
    """Corrida com a persistência: linha ainda não existe → agenda retentativa."""
    from app.webhook import meta_router
    sb = MagicMock()
    scheduled = []

    def _fake_create_task(coro):
        scheduled.append(coro.__qualname__)
        coro.close()

    with patch.object(meta_router, "get_supabase", return_value=sb), \
         patch.object(meta_router, "_apply_message_status", return_value=True), \
         patch.object(meta_router, "_record_delivery_error", return_value=False), \
         patch.object(meta_router.asyncio, "create_task", _fake_create_task), \
         patch("app.broadcast.service.find_broadcast_lead_by_wamid", return_value=None):
        await meta_router._handle_delivery_status("wamid.X", "failed", [ERR_131026], None, "1793988307")
    assert scheduled == ["_retry_record_delivery_error"]


@pytest.mark.asyncio
async def test_retry_record_delivery_error_stops_when_row_appears():
    from app.webhook import meta_router
    calls = []

    async def _no_sleep(_):
        return None

    def _rec(sb, wamid, errors, ts):
        calls.append(wamid)
        return len(calls) >= 2

    with patch.object(meta_router, "get_supabase", return_value=MagicMock()), \
         patch.object(meta_router, "_record_delivery_error", side_effect=_rec), \
         patch.object(meta_router.asyncio, "sleep", _no_sleep):
        await meta_router._retry_record_delivery_error("wamid.X", [ERR_131026], None)
    assert calls == ["wamid.X", "wamid.X"]
