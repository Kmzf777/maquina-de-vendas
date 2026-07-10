"""Roteamento do Dossiê do Lead para gemini-2.5-flash-lite (FinOps 08/07/2026).

Consolidar o dossiê é tarefa MECÂNICA (merge estruturado de JSON com thinking já
desligado, temperatura 0.2) e roda no worker a cada tick — não precisa do 2.5-flash.
O flash-lite custa 1/3 no input e 1/6 no output. Roteado via settings (env MEMORY_MODEL)
para reverter sem deploy se a qualidade do merge degradar.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_memory_model_default_flash_lite():
    from app.config import Settings
    field = Settings.model_fields["memory_model"]
    assert field.default == "gemini-2.5-flash-lite"


@pytest.mark.asyncio
async def test_refresh_usa_memory_model_das_settings(monkeypatch):
    from app.agent import memory_manager

    monkeypatch.setattr(memory_manager, "_claim_lock", lambda sb, lead_id, now: True)
    monkeypatch.setattr(memory_manager, "_release_lock", lambda sb, lead_id: None)
    monkeypatch.setattr(memory_manager, "get_supabase", lambda: MagicMock())
    monkeypatch.setattr(
        memory_manager, "get_lead",
        lambda _id: {"rolling_summary": "", "rolling_summary_updated_at": None},
    )
    monkeypatch.setattr(
        memory_manager, "get_history",
        lambda _id, since=None, limit=30, latest=False: [
            {"role": "user", "content": "oi", "created_at": "2026-07-08T10:00:00+00:00"}
        ],
    )
    monkeypatch.setattr(memory_manager, "update_lead", lambda *a, **k: None)

    seen = {}

    async def fake_generate(prior, delta, client, model, lead_id=None, stage=""):
        seen["model"] = model
        return "## DOSSIÊ DO LEAD\n* novo"

    monkeypatch.setattr(memory_manager, "generate_rolling_summary", fake_generate)

    ok = await memory_manager.refresh_lead_memory("L1", client=MagicMock())
    assert ok is True
    assert seen["model"] == "gemini-2.5-flash-lite"
