"""Eixo 3A — Idempotência de agendar_retorno.

Bug do Walter (5565999550023): a IA chamou agendar_retorno 3x seguidas (a cada despedida
do lead), reagendando o mesmo retorno e re-confirmando em loop. A tool agora detecta um
retorno pending para a conversa e instrui o LLM a NÃO reagendar.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest


def _future_iso():
    return (datetime.now(timezone.utc) + timedelta(days=2)).astimezone(
        timezone(timedelta(hours=-3))
    ).replace(microsecond=0).isoformat()


@pytest.mark.asyncio
async def test_agendar_retorno_nao_duplica_quando_ja_pendente(monkeypatch):
    from app.agent import tools

    fire = datetime.now(timezone.utc) + timedelta(days=2)
    monkeypatch.setattr(
        tools, "find_pending_ai_return",
        lambda conversation_id: {"id": "job-0", "fire_at": fire.isoformat(), "metadata": {}},
    )
    scheduled = []
    monkeypatch.setattr(tools, "schedule_ai_return", lambda **k: scheduled.append(k) or fire)
    monkeypatch.setattr(tools, "get_channel_for_lead", lambda lead_id: {"id": "ch-1"})
    monkeypatch.setattr(tools, "get_lead", lambda lead_id: {"id": lead_id, "name": "Walter"})

    with patch("app.agent.tools.save_message"):
        result = await tools.execute_tool(
            "agendar_retorno",
            {"data_hora": _future_iso(), "motivo": "fala segunda"},
            lead_id="lead-1", phone="5565999550023", conversation_id="conv-1",
        )

    assert scheduled == [], "não deve reagendar quando já há retorno pendente"
    low = result.lower()
    assert "nao chame agendar_retorno de novo" in low
    assert "ja tem um retorno agendado" in low


@pytest.mark.asyncio
async def test_agendar_retorno_agenda_quando_nao_ha_pendente(monkeypatch):
    from app.agent import tools

    fire = datetime.now(timezone.utc) + timedelta(days=2)
    monkeypatch.setattr(tools, "find_pending_ai_return", lambda conversation_id: None)
    scheduled = []
    monkeypatch.setattr(tools, "schedule_ai_return", lambda **k: scheduled.append(k) or fire)
    monkeypatch.setattr(tools, "get_channel_for_lead", lambda lead_id: {"id": "ch-1"})
    monkeypatch.setattr(tools, "get_lead", lambda lead_id: {"id": lead_id, "name": "Walter"})

    with patch("app.agent.tools.save_message"):
        result = await tools.execute_tool(
            "agendar_retorno",
            {"data_hora": _future_iso(), "motivo": "fala segunda"},
            lead_id="lead-1", phone="5565999550023", conversation_id="conv-1",
        )

    assert len(scheduled) == 1
    assert "agendad" in result.lower()


def test_find_pending_ai_return_filtra_por_conversa_e_status(monkeypatch):
    from app.follow_up import service

    captured = {}

    class _Q:
        def select(self, *a):
            return self
        def eq(self, col, val):
            captured[col] = val
            return self
        def limit(self, n):
            return self
        def execute(self):
            from unittest.mock import MagicMock
            return MagicMock(data=[{"id": "job-9"}])

    monkeypatch.setattr(service, "get_supabase",
                        lambda: type("S", (), {"table": lambda self, n: _Q()})())

    result = service.find_pending_ai_return("conv-1")
    assert result["id"] == "job-9"
    assert captured["conversation_id"] == "conv-1"
    assert captured["status"] == "pending"
    assert captured["job_type"] == "ai_scheduled_return"
