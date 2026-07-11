"""Nó `wait` com granularidade de HORAS além de dias (11/07).

A unidade exclusiva 'dias' era ampla demais para o controle do operador. O cálculo
foi extraído para a função PURA `_wait_target` (engine), que soma days+hours e
aplica o clamp de janela comercial — retrocompatível com nós antigos (só `days`).
"""

from datetime import datetime, timezone

from app.automation.engine import _wait_target

# 12:00 UTC = 09:00 BRT (dentro da janela default 7–18 BRT)
_NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def test_days_plus_hours_exact():
    target = _wait_target({"days": 3, "hours": 20, "send_start_hour": 0, "send_end_hour": 24}, _NOW)
    assert target == datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)  # +3d20h exato


def test_hours_only_sub_daily_wait():
    target = _wait_target({"days": 0, "hours": 2, "send_start_hour": 7, "send_end_hour": 18}, _NOW)
    assert target == datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)  # 11:00 BRT, na janela


def test_legacy_days_only_unchanged():
    """Nós antigos (sem `hours`) mantêm o comportamento: days default 1, hours 0."""
    assert _wait_target({"days": 2, "send_start_hour": 0, "send_end_hour": 24}, _NOW) == datetime(
        2026, 7, 15, 12, 0, tzinfo=timezone.utc
    )
    assert _wait_target({"send_start_hour": 0, "send_end_hour": 24}, _NOW) == datetime(
        2026, 7, 14, 12, 0, tzinfo=timezone.utc
    )


def test_window_clamp_still_applies_to_hour_waits():
    """+9h cai às 18:00 BRT (fora da janela 7–18) → empurra para 07:00 BRT do dia seguinte."""
    target = _wait_target({"days": 0, "hours": 9, "send_start_hour": 7, "send_end_hour": 18}, _NOW)
    assert target == datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)  # 07:00 BRT de 14/07


def test_zero_zero_means_next_tick_and_garbage_is_sanitized():
    assert _wait_target({"days": 0, "hours": 0, "send_start_hour": 0, "send_end_hour": 24}, _NOW) == _NOW
    assert _wait_target({"days": -5, "hours": -3, "send_start_hour": 0, "send_end_hour": 24}, _NOW) == _NOW
    assert _wait_target({"days": None, "hours": None, "send_start_hour": 0, "send_end_hour": 24}, _NOW) == _NOW
