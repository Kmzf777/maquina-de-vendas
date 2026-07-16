"""Barramento de eventos (wake-up) — emissão fail-open sobre Redis Streams."""
from unittest.mock import MagicMock

from app.events import bus


def _fresh_client(mock_client):
    """Injeta client mockado e limpa o cache module-level."""
    bus._client = mock_client


def test_emit_event_faz_xadd_no_stream_do_dominio():
    client = MagicMock()
    _fresh_client(client)
    ok = bus.emit_event("followups", {"job_id": "abc"})
    assert ok is True
    args, kwargs = client.xadd.call_args
    assert args[0] == "events:followups"
    assert kwargs.get("maxlen") == 1024 and kwargs.get("approximate") is True


def test_emit_event_fail_open_quando_redis_fora():
    client = MagicMock()
    client.xadd.side_effect = ConnectionError("redis down")
    _fresh_client(client)
    assert bus.emit_event("broadcasts") is False  # não levanta


def test_emit_event_rejeita_dominio_desconhecido():
    client = MagicMock()
    _fresh_client(client)
    assert bus.emit_event("nope") is False
    client.xadd.assert_not_called()


def test_stream_key():
    assert bus.stream_key("automation") == "events:automation"
