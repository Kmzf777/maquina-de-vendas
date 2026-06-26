"""Eixo 3B — Fallback de janela fechada + retomada com TTL.

Janela 24h fechada não descarta mais o retorno em silêncio: dispara o template
`continuar_conversa` e marca o job `awaiting_reopen`. Quando o lead responde dentro do TTL
de 7 dias, a IA retoma o contexto salvo; após o TTL, descarta (anti-contexto-zumbi).
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest


def _job(last_customer_message_at, metadata=None):
    return {
        "id": "job-1", "lead_id": "lead-1", "conversation_id": "conv-1",
        "channels": {"id": "ch-1", "mode": "ai", "provider": "meta_cloud",
                     "provider_config": {"phone_number_id": "pid"}},
        "conversations": {"id": "conv-1", "stage": "atacado",
                          "last_customer_message_at": last_customer_message_at},
        "metadata": metadata or {"motivo": "fechar pedido de 30kg", "contexto": "lead pediu segunda"},
    }


# ── scheduler: janela fechada → template + awaiting_reopen ──
@pytest.mark.asyncio
async def test_janela_fechada_dispara_template_e_marca_awaiting_reopen(monkeypatch):
    from app.follow_up import scheduler
    now = datetime.now(timezone.utc)
    job = _job((now - timedelta(hours=48)).isoformat())
    lead = {"id": "lead-1", "phone": "5565999550023", "name": "Walter Silva",
            "ai_enabled": True, "last_customer_message_at": (now - timedelta(hours=48)).isoformat(),
            "metadata": {}, "wa_id": None}
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=lead)
    monkeypatch.setattr(scheduler, "get_supabase", lambda: sb)
    monkeypatch.setattr(scheduler, "resolve_send_target", lambda l, p: p)
    monkeypatch.setattr(scheduler, "save_message", lambda **k: None)

    marks, cancels = [], []
    monkeypatch.setattr(scheduler, "_mark_awaiting_reopen", lambda jid: marks.append(jid))
    monkeypatch.setattr(scheduler, "_cancel_job", lambda jid, r: cancels.append((jid, r)))

    sent = {}

    class FakeMeta:
        def __init__(self, cfg):
            pass

        async def send_template(self, to, name, components=None, language_code=None):
            sent.update(to=to, name=name, components=components)
            return {"messages": [{"id": "wamid.r"}]}

    monkeypatch.setattr(scheduler, "MetaCloudClient", FakeMeta)

    await scheduler._process_ai_scheduled_return(job, now)

    assert sent["name"] == "continuar_conversa"
    assert marks == ["job-1"]
    assert cancels == []  # não descarta em silêncio


# ── service: consume_reopen_context com TTL ──
class _FakeTable:
    def __init__(self, rows, updates):
        self._rows = rows
        self._updates = updates
        self._pending = {}

    def select(self, *a):
        return self

    def eq(self, col, val):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def update(self, payload):
        self._pending = dict(payload)
        return self

    def execute(self):
        if self._pending:
            self._updates.append(self._pending)
            self._pending = {}
            return MagicMock(data=[{"id": "j1"}])
        return MagicMock(data=self._rows)


def _fake_sb(rows, updates):
    return type("S", (), {"table": lambda self, n: _FakeTable(rows, updates)})()


def test_consume_reopen_dentro_do_ttl_retorna_contexto(monkeypatch):
    from app.follow_up import service
    now = datetime.now(timezone.utc)
    job = {"id": "j1", "sent_at": (now - timedelta(days=2)).isoformat(),
           "fire_at": (now - timedelta(days=2, hours=1)).isoformat(),
           "metadata": {"motivo": "fechar pedido de 30kg", "contexto": "segunda"}}
    updates = []
    monkeypatch.setattr(service, "get_supabase", lambda: _fake_sb([job], updates))

    ctx = service.consume_reopen_context("conv-1", now)
    assert ctx is not None
    assert "fechar pedido de 30kg" in ctx
    assert any(u.get("status") == "sent" for u in updates)


def test_consume_reopen_fora_do_ttl_expira_e_retorna_none(monkeypatch):
    from app.follow_up import service
    now = datetime.now(timezone.utc)
    job = {"id": "j1", "sent_at": (now - timedelta(days=10)).isoformat(),
           "fire_at": (now - timedelta(days=10)).isoformat(),
           "metadata": {"motivo": "x"}}
    updates = []
    monkeypatch.setattr(service, "get_supabase", lambda: _fake_sb([job], updates))

    ctx = service.consume_reopen_context("conv-1", now)
    assert ctx is None
    assert any(u.get("status") == "expired" for u in updates)


def test_consume_reopen_sem_job_retorna_none(monkeypatch):
    from app.follow_up import service
    updates = []
    monkeypatch.setattr(service, "get_supabase", lambda: _fake_sb([], updates))
    assert service.consume_reopen_context("conv-1", datetime.now(timezone.utc)) is None


# ── base.py renderiza o contexto de retomada ──
def test_base_renderiza_scheduled_return_context():
    from app.agent.prompts.base import build_base_prompt
    p = build_base_prompt(
        "Walter", None, datetime(2026, 6, 26, 14, 0),
        lead_context={"scheduled_return_context": "<retorno_agendado>RETOMAR XPTO</retorno_agendado>"},
    )
    assert "retorno_agendado" in p
    assert "RETOMAR XPTO" in p
