import asyncio
import json
import os
from pathlib import Path

import pytest

from app.whatsapp.mock_provider import MockProvider


@pytest.mark.asyncio
async def test_send_text_logs_and_returns_ok(tmp_path, monkeypatch):
    log_file = tmp_path / "rehearsal.jsonl"
    monkeypatch.setenv("REHEARSAL_LOG_PATH", str(log_file))
    provider = MockProvider({"name": "test"})

    result = await provider.send_text("+5500000000", "ola")

    assert result["status"] == "mock_ok"
    lines = log_file.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["method"] == "send_text"
    assert entry["to"] == "+5500000000"
    assert entry["body"] == "ola"


@pytest.mark.asyncio
async def test_send_image_base64_logs_summary(tmp_path, monkeypatch):
    log_file = tmp_path / "rehearsal.jsonl"
    monkeypatch.setenv("REHEARSAL_LOG_PATH", str(log_file))
    provider = MockProvider({})

    await provider.send_image_base64("+5500000000", "A" * 10000, caption="foto")

    entry = json.loads(log_file.read_text().splitlines()[0])
    assert entry["method"] == "send_image_base64"
    assert entry["caption"] == "foto"
    assert "base64_size_bytes" in entry
    assert entry["base64_size_bytes"] == 10000


@pytest.mark.asyncio
async def test_send_template_logs(tmp_path, monkeypatch):
    log_file = tmp_path / "rehearsal.jsonl"
    monkeypatch.setenv("REHEARSAL_LOG_PATH", str(log_file))
    provider = MockProvider({})

    await provider.send_template("+5500000000", "tpl_outbound", {"body": ["Joao"]})

    entry = json.loads(log_file.read_text().splitlines()[0])
    assert entry["method"] == "send_template"
    assert entry["template_name"] == "tpl_outbound"


@pytest.mark.asyncio
async def test_no_log_file_if_env_unset(monkeypatch):
    monkeypatch.delenv("REHEARSAL_LOG_PATH", raising=False)
    provider = MockProvider({})
    result = await provider.send_text("+5500000000", "ola")
    assert result["status"] == "mock_ok"
