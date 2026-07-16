"""Criação de trabalho emite wake-up (Redis Stream) para o worker.

O evento é só um acorda-loop: fail-open, sem payload obrigatório. O que se
testa aqui é que cada ponto de criação chama emit_event com o domínio certo
— e que falha de insert NÃO emite (não acordar o worker para nada).
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def test_create_enrollment_emite_automation(monkeypatch):
    import app.campaigns.service as svc

    emitted = []
    monkeypatch.setattr(svc, "emit_event", lambda d, p=None: emitted.append(d))
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "e1"}]
    with patch.object(svc, "get_supabase", return_value=sb):
        row = svc.create_enrollment("camp-1", "lead-1", "node-1", datetime.now(timezone.utc))
    assert row == {"id": "e1"}
    assert emitted == ["automation"]


def test_schedule_ai_return_emite_followups(monkeypatch):
    import app.follow_up.service as svc

    emitted = []
    monkeypatch.setattr(svc, "emit_event", lambda d, p=None: emitted.append(d))
    sb = MagicMock()
    with patch.object(svc, "get_supabase", return_value=sb):
        svc.schedule_ai_return(
            "conv-1", "lead-1", "ch-1", datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
        )
    assert emitted == ["followups"]


def test_schedule_ai_return_nao_emite_em_falha_de_insert(monkeypatch):
    import app.follow_up.service as svc

    emitted = []
    monkeypatch.setattr(svc, "emit_event", lambda d, p=None: emitted.append(d))
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError("db down")
    with patch.object(svc, "get_supabase", return_value=sb):
        with pytest.raises(RuntimeError):
            svc.schedule_ai_return(
                "conv-1", "lead-1", "ch-1", datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
            )
    assert emitted == []


def test_start_broadcast_emite_broadcasts(monkeypatch):
    import app.broadcast.router as router_mod

    emitted = []
    monkeypatch.setattr(router_mod, "emit_event", lambda d, p=None: emitted.append(d))
    sb = MagicMock()
    # billing check: sem alerta aberto
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    # broadcast atual: draft
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "draft"}
    # pendentes: 3
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 3
    with patch.object(router_mod, "get_supabase", return_value=sb):
        result = asyncio.run(router_mod.start_broadcast("b-1"))
    assert result["status"] == "started"
    assert emitted == ["broadcasts"]


def test_update_broadcast_agendado_emite_broadcasts(monkeypatch):
    import app.broadcast.router as router_mod

    emitted = []
    monkeypatch.setattr(router_mod, "emit_event", lambda d, p=None: emitted.append(d))
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "draft"}
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{"id": "b-1"}]
    with patch.object(router_mod, "get_supabase", return_value=sb):
        asyncio.run(router_mod.update_broadcast("b-1", {"scheduled_at": "2026-07-15T12:00:00Z"}))
    assert emitted == ["broadcasts"]


def test_update_broadcast_sem_agendamento_nao_emite(monkeypatch):
    import app.broadcast.router as router_mod

    emitted = []
    monkeypatch.setattr(router_mod, "emit_event", lambda d, p=None: emitted.append(d))
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{"id": "b-1"}]
    with patch.object(router_mod, "get_supabase", return_value=sb):
        asyncio.run(router_mod.update_broadcast("b-1", {"name": "novo nome"}))
    assert emitted == []
