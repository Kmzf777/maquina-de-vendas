"""Logging estruturado: uma linha JSON por registro, com fallback text p/ dev."""
import json
import logging

from app.logging_setup import JsonFormatter, setup_logging


def _record(msg="olá [FOLLOWUP] mundo", exc=None):
    return logging.LogRecord(
        name="app.teste", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=exc,
    )


def test_json_formatter_emite_json_valido_com_campos():
    out = JsonFormatter().format(_record())
    data = json.loads(out)
    assert data["level"] == "INFO"
    assert data["logger"] == "app.teste"
    assert data["msg"] == "olá [FOLLOWUP] mundo"
    assert "ts" in data


def test_json_formatter_serializa_excecao():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        out = JsonFormatter().format(_record(exc=sys.exc_info()))
    data = json.loads(out)
    assert "ValueError: boom" in data["exc_info"]


def test_setup_logging_json_por_default(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    try:
        setup_logging()
        assert any(isinstance(h.formatter, JsonFormatter) for h in root.handlers)
    finally:
        root.handlers = old_handlers


def test_setup_logging_text_para_dev(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "text")
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    try:
        setup_logging()
        assert not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers)
    finally:
        root.handlers = old_handlers
