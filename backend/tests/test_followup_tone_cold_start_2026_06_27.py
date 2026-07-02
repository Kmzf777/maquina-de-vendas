"""Blocker (Erro 3, follow-up #2): o tom do follow-up deve seguir o OBJETIVO do toque,
não o número da sequência.

Antes, `_build_followup_system_prompt` keyava o tom em `sequence == 1`. Como o lead frio
(warm=False) pula o T1 e seu primeiro toque agendado é a sequence=2, ele caía no ramo de
"última tentativa" logo no PRIMEIRO contato — exatamente a cobrança prematura que o Erro 3
queria eliminar. Agora o tom segue o objetivo: só `ultima_chamada` usa o tom de última
tentativa; todos os outros usam reengajamento leve.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.follow_up.scheduler import _build_followup_system_prompt


def _low(sequence, objetivo):
    return _build_followup_system_prompt(sequence, objetivo=objetivo).lower()


def test_cold_first_touch_reforco_valor_not_last_attempt():
    """Lead frio: primeiro toque é sequence=2 (objetivo reforco_valor) — sem tom agressivo."""
    low = _low(2, "reforco_valor")
    assert "última tentativa" not in low and "ultima tentativa" not in low, (
        "lead frio recebeu tom de última tentativa no primeiro toque"
    )
    assert "reengajamento" in low or "sem pressionar" in low


def test_reengajar_touch_not_last_attempt():
    low = _low(1, "reengajar")
    assert "última tentativa" not in low and "ultima tentativa" not in low


def test_prova_social_touch_not_last_attempt():
    low = _low(3, "prova_social")
    assert "última tentativa" not in low and "ultima tentativa" not in low


def test_ultima_chamada_touch_uses_last_attempt_tone():
    """Só o toque que de fato é o último da cadência usa o tom de última tentativa."""
    low = _low(4, "ultima_chamada")
    assert "última tentativa" in low or "ultima tentativa" in low


@pytest.mark.asyncio
async def test_generate_forwards_objetivo_to_system_prompt(monkeypatch):
    """Wiring: _generate_followup_message repassa o objetivo do toque ao system prompt."""
    from app.follow_up import scheduler

    seen = {}

    def _fake_build(sequence, objetivo=None, last_msg_age=None):
        seen["seq"] = sequence
        seen["obj"] = objetivo
        return "SYSTEM"

    monkeypatch.setattr(scheduler, "_build_followup_system_prompt", _fake_build)
    monkeypatch.setattr(scheduler, "track_token_usage", lambda **k: None)

    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "oi"
    resp.choices[0].finish_reason = "stop"
    resp.usage = None
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)
    monkeypatch.setattr(scheduler, "get_gemini_client", lambda *a, **k: mock_client)

    msg, finish_reason = await scheduler._generate_followup_message(
        [{"role": "user", "content": "oi"}],
        2,
        lead_id="lead-1",
        stage="atacado",
        objective_prompt="reforce o valor",
        objetivo="reforco_valor",
    )

    assert seen["seq"] == 2
    assert seen["obj"] == "reforco_valor"
    assert msg == "oi"
