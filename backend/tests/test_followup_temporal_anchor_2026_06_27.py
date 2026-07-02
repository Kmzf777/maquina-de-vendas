# backend/tests/test_followup_temporal_anchor_2026_06_27.py
"""Erro 3 (parte 2): âncora temporal no follow-up evita 'outro dia' alucinado.

Produção (lead Johny): follow-up disse 'a gente se falou rapidinho outro dia' sendo que o 1º
contato foi na mesma manhã. Injetamos Δt da última mensagem + proibição de inventar período.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.follow_up import scheduler
from app.follow_up.scheduler import _build_followup_system_prompt, _humanize_elapsed


def test_humanize_elapsed_calendario_hoje_ontem_dias():
    base = datetime(2026, 6, 26, 14, 0, tzinfo=timezone.utc)  # 11h BRT, quinta
    assert "hoje" in _humanize_elapsed(base, base - timedelta(hours=2)).lower()
    assert "hora" in _humanize_elapsed(base, base - timedelta(hours=2))
    assert "ontem" in _humanize_elapsed(base, base - timedelta(days=1)).lower()
    assert "dia" in _humanize_elapsed(base, base - timedelta(days=3))
    # poucos minutos no mesmo dia → bucket "hoje"
    assert "hoje" in _humanize_elapsed(base, base - timedelta(minutes=5)).lower()


def test_system_prompt_injeta_ancora_e_proibe_inventar_periodo():
    low = _build_followup_system_prompt(2, objetivo="reforco_valor", last_msg_age="hoje, há ~2 horas").lower()
    assert "hoje, há ~2 horas" in low
    # grounding: proíbe inventar período de tempo
    assert "outro dia" in low  # citado como exemplo do que NÃO dizer
    assert "invent" in low or "nao diga" in low or "não diga" in low


def test_system_prompt_sem_ancora_nao_quebra():
    # compat: sem last_msg_age, não injeta a linha de âncora
    low = _build_followup_system_prompt(2, objetivo="reforco_valor").lower()
    assert "última mensagem desta conversa foi enviada" not in low


@pytest.mark.asyncio
async def test_generate_computa_e_repassa_last_msg_age(monkeypatch):
    seen = {}

    def fake_build(sequence, objetivo=None, last_msg_age=None):
        seen["age"] = last_msg_age
        return "SYSTEM"

    monkeypatch.setattr(scheduler, "_build_followup_system_prompt", fake_build)
    monkeypatch.setattr(scheduler, "track_token_usage", lambda **k: None)

    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "oi"
    resp.choices[0].finish_reason = "stop"
    resp.usage = None
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    monkeypatch.setattr(scheduler, "get_gemini_client", lambda *a, **k: client)

    now = datetime(2026, 6, 26, 14, 47, tzinfo=timezone.utc)
    history = [{"role": "user", "content": "oi", "created_at": "2026-06-26T12:47:00+00:00"}]
    await scheduler._generate_followup_message(history, 2, objetivo="reforco_valor", now=now)
    assert seen["age"] is not None and "hora" in seen["age"]
