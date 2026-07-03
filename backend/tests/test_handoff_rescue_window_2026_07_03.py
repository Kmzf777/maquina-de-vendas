"""Janela PROPRIA do rescue de handoff (`_clamp_to_rescue_window`) — 2026-07-03
(Frente B, Task 2 / B2).

Contexto forense: `schedule_handoff_rescue` clampava o `fire_at` do aviso ao Joao
usando `_clamp_to_business_window` (09h-16h, seg-sex) — a MESMA janela da cadencia
automatica de follow-up. Dois casos reais mostraram que isso e cedo demais pra um
aviso pontual ao vendedor (nao uma cadencia de mensagens ao lead):

  - Edgar mandou mensagem as 17:22 local -> o aviso ao Joao foi empurrado pro dia
    seguinte as 09h, mesmo com o vendedor tipicamente ainda ativo essa hora.
  - Davi mandou as 15:47 -> mesma historia (so 13min dentro da janela comercial, e
    ja bastava pra sobrar folga nenhuma).

O rescue passa a ter janela PROPRIA (09h-20h, seg-sex, `_clamp_to_rescue_window`),
usada exclusivamente por `schedule_handoff_rescue`. `_clamp_to_business_window`
continua INTOCADA — schedule_followup/build_touch_jobs (cadencia standard) e a
decisao de "disparar AGORA" de `retomar_contato_vendedor` (via
`is_within_business_window`) continuam usando a janela comercial de sempre.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

SP_TZ = ZoneInfo("America/Sao_Paulo")


# ─── _clamp_to_rescue_window (unidade) ──────────────────────────────────────

def test_clamp_to_rescue_window_keeps_target_inside_window():
    """Quinta-feira 12:00 local (dentro de [09:00,20:00)) -> inalterado."""
    from app.follow_up.service import _clamp_to_rescue_window

    target = datetime(2026, 7, 2, 12, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)
    assert _clamp_to_rescue_window(target) == target


def test_clamp_to_rescue_window_moves_to_same_day_09h_when_before_window():
    """Quinta-feira 07:00 local (antes de 09:00) -> mesmo dia 09:00 local."""
    from app.follow_up.service import _clamp_to_rescue_window

    target = datetime(2026, 7, 2, 7, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)
    expected = datetime(2026, 7, 2, 9, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)

    assert _clamp_to_rescue_window(target) == expected


def test_clamp_to_rescue_window_moves_to_next_business_day_09h_when_after_20h():
    """Quinta-feira 20:30 local (>= 20:00) -> sexta-feira 09:00 local."""
    from app.follow_up.service import _clamp_to_rescue_window

    target = datetime(2026, 7, 2, 20, 30, 0, tzinfo=SP_TZ).astimezone(timezone.utc)
    expected = datetime(2026, 7, 3, 9, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)

    result = _clamp_to_rescue_window(target)

    assert result == expected
    assert result.astimezone(SP_TZ).weekday() == 4  # sexta-feira


def test_clamp_to_rescue_window_saturday_moves_to_monday_09h():
    """Sabado 10:00 local (fim de semana) -> segunda-feira seguinte 09:00 local."""
    from app.follow_up.service import _clamp_to_rescue_window

    target = datetime(2026, 7, 4, 10, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)
    expected = datetime(2026, 7, 6, 9, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)

    result = _clamp_to_rescue_window(target)

    assert result == expected
    assert result.astimezone(SP_TZ).weekday() == 0  # segunda-feira


# ─── schedule_handoff_rescue (integracao — casos reais Edgar/Davi) ──────────

def _run_schedule(now_local: datetime, delay_minutes: int = 15) -> datetime:
    """Chama `schedule_handoff_rescue` com `now` mockado (a partir de um horario
    LOCAL) e devolve o `fire_at` efetivamente inserido no job. Mesmo padrao de
    mock de `test_schedule_handoff_rescue_inserts_job_with_correct_fields`
    (test_handoff_rescue.py) — patcheia `datetime` inteiro no modulo, mas
    `_clamp_to_rescue_window` so usa metodos de instancia (`.astimezone`/
    `.replace`/`.weekday`/`.time`) sobre um datetime JA real, entao o mock nao
    interfere na logica do clamp.
    """
    from app.follow_up.service import schedule_handoff_rescue

    inserted = []
    mock_insert = MagicMock()
    mock_insert.return_value.execute.side_effect = lambda: inserted.append(
        mock_insert.call_args[0][0]
    ) or MagicMock()
    mock_sb = MagicMock()
    mock_sb.table.return_value.insert = mock_insert

    now_utc = now_local.astimezone(timezone.utc)
    with patch("app.follow_up.service.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.service.datetime") as mock_dt:
        mock_dt.now.return_value = now_utc
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        schedule_handoff_rescue(
            lead_id="lead-1",
            lead_phone="5511999999999",
            conversation_id="conv-1",
            channel_id="ch-1",
            delay_minutes=delay_minutes,
        )

    assert len(inserted) == 1
    return datetime.fromisoformat(inserted[0]["fire_at"])


def test_edgar_1722_fires_same_day_1737():
    """Caso Edgar: now=17:22 local -> fire_at 17:37 MESMO dia (antes ia p/ 09h do
    dia seguinte, porque 17:22 ja estava fora da janela comercial de 16h)."""
    now_local = datetime(2026, 7, 2, 17, 22, 0, tzinfo=SP_TZ)  # quinta-feira

    fire_at_local = _run_schedule(now_local).astimezone(SP_TZ)

    assert fire_at_local.date() == now_local.date()
    assert (fire_at_local.hour, fire_at_local.minute) == (17, 37)


def test_davi_1547_fires_same_day_1602():
    """Caso Davi: now=15:47 local -> fire_at 16:02 MESMO dia (antes ia p/ 09h do
    dia seguinte, porque 16:02 ja passava do teto comercial de 16h)."""
    now_local = datetime(2026, 7, 2, 15, 47, 0, tzinfo=SP_TZ)  # quinta-feira

    fire_at_local = _run_schedule(now_local).astimezone(SP_TZ)

    assert fire_at_local.date() == now_local.date()
    assert (fire_at_local.hour, fire_at_local.minute) == (16, 2)


def test_now_1950_fires_next_business_day_09h():
    """now=19:50 local + 15min = 20:05 (>= 20:00, fora ate da janela AMPLIADA do
    rescue) -> proximo dia util as 09h."""
    now_local = datetime(2026, 7, 2, 19, 50, 0, tzinfo=SP_TZ)  # quinta-feira
    expected_local = datetime(2026, 7, 3, 9, 0, 0, tzinfo=SP_TZ)  # sexta-feira

    fire_at_local = _run_schedule(now_local).astimezone(SP_TZ)

    assert fire_at_local == expected_local


def test_saturday_fires_next_monday_09h():
    """now em sabado -> proximo dia util (segunda-feira) as 09h."""
    now_local = datetime(2026, 7, 4, 10, 0, 0, tzinfo=SP_TZ)  # sabado
    expected_local = datetime(2026, 7, 6, 9, 0, 0, tzinfo=SP_TZ)  # segunda-feira

    fire_at_local = _run_schedule(now_local).astimezone(SP_TZ)

    assert fire_at_local == expected_local


# ─── Nao-regressao: _clamp_to_business_window continua 09h-16h ─────────────

def test_business_window_clamp_unchanged_still_ends_at_16h():
    """`_clamp_to_business_window` NAO foi tocada — continua terminando as 16h.
    17:00 local esta DENTRO da nova janela do rescue (09h-20h) mas FORA da
    comercial (09h-16h): se algum refactor tivesse feito a comercial delegar pra
    janela do rescue (ou alterado `_BUSINESS_END`), este caso pegaria a
    divergencia na hora (o rescue manteria 17:00 no mesmo dia; a comercial tem
    que continuar empurrando pro dia seguinte). Cobre a cadencia standard
    (`build_touch_jobs`, via `cadence.py`) e a decisao "disparar AGORA" de
    `retomar_contato_vendedor` (via `is_within_business_window`), que dependem
    exatamente deste contrato.
    """
    from app.follow_up.service import _clamp_to_business_window

    target = datetime(2026, 7, 2, 17, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)  # quinta-feira
    expected = datetime(2026, 7, 3, 9, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)  # sexta-feira

    assert _clamp_to_business_window(target) == expected


def test_business_window_clamp_still_active_inside_16h():
    """Sanidade complementar: 12:00 local (dentro de 09h-16h) continua inalterado
    por `_clamp_to_business_window` — a introducao de `_clamp_to_rescue_window`
    nao alterou o caminho feliz da janela comercial."""
    from app.follow_up.service import _clamp_to_business_window

    target = datetime(2026, 7, 2, 12, 0, 0, tzinfo=SP_TZ).astimezone(timezone.utc)
    assert _clamp_to_business_window(target) == target
