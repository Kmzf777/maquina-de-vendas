"""GET /api/cadence/definition — a esteira do motor de follow-up para o CRM.

O painel visual de Follow-up (aba em /campanhas) renderiza a definição da cadência a
partir DESTE endpoint — nunca de uma cópia hardcoded no frontend — para que
follow_up/cadence.py continue sendo a única fonte de verdade. Estes testes fixam o
shape do payload e a fidelidade aos valores de cadence.py.
"""

from app.follow_up.api import build_cadence_definition
from app.follow_up.cadence import CADENCE, OUTBOUND_NUDGE, MIN_GAP


def test_definition_contains_all_cadence_touches_in_order():
    payload = build_cadence_definition()
    touches = payload["touches"]
    assert [t["sequence"] for t in touches] == [t.sequence for t in CADENCE]
    assert [t["objective"] for t in touches] == [t.objective for t in CADENCE]


def test_definition_touch_shape_and_offsets():
    payload = build_cadence_definition()
    t1 = payload["touches"][0]
    assert set(t1) >= {"sequence", "offset_hours", "jitter_minutes", "objective", "objective_prompt"}
    assert t1["offset_hours"] == 0.0
    assert t1["jitter_minutes"] == [90, 210]
    t2 = payload["touches"][1]
    assert t2["offset_hours"] == 24.0
    assert t2["jitter_minutes"] is None


def test_definition_includes_nudge_min_gap_and_business_window():
    payload = build_cadence_definition()
    nudge = payload["outbound_nudge"]
    assert nudge["offset_hours"] == 18.0
    assert nudge["objective"] == OUTBOUND_NUDGE.objective
    assert payload["min_gap_hours"] == MIN_GAP.total_seconds() / 3600
    window = payload["business_window"]
    assert window == {"start": "09:00", "end": "16:00", "days": "seg-sex", "timezone": "America/Sao_Paulo"}


def test_router_is_registered_in_main_app():
    """O router precisa estar montado no app.

    Guarda em NÍVEL DE FONTE (mesmo idioma de test_lifespan_does_not_force_buffer_off):
    inspecionar `app.main.app.routes` em runtime é frágil a poluição de módulos entre
    testes (falhou só no runner do CI, com o app parcialmente montado por outro teste).
    """
    import inspect
    import app.main as main_module

    src = inspect.getsource(main_module)
    assert "from app.follow_up.api import router as cadence_api_router" in src
    assert "app.include_router(cadence_api_router)" in src
