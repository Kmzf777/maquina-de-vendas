"""API somente-leitura da DEFINIÇÃO da cadência de follow-up (painel do CRM).

O painel visual de Follow-up (aba em /campanhas) renderiza a esteira de toques a
partir deste endpoint, mantendo `follow_up/cadence.py` como única fonte de verdade —
uma cópia hardcoded no frontend divergiria em silêncio a cada ajuste do motor.

Os JOBS vivos (follow_up_jobs) não passam por aqui: o CRM os lê direto do Supabase
(mesmo padrão de broadcasts/campaigns), com RLS/service key do lado Next.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.follow_up.cadence import CADENCE, MIN_GAP, OUTBOUND_NUDGE, Touch

router = APIRouter(prefix="/api/cadence", tags=["cadence"])


def _touch_payload(touch: Touch) -> dict:
    return {
        "sequence": touch.sequence,
        "offset_hours": touch.offset.total_seconds() / 3600,
        "jitter_minutes": list(touch.jitter_minutes) if touch.jitter_minutes else None,
        "objective": touch.objective,
        "objective_prompt": touch.objective_prompt,
    }


def build_cadence_definition() -> dict:
    """Payload puro da definição — separado do handler para teste isolado."""
    return {
        "touches": [_touch_payload(t) for t in CADENCE],
        "outbound_nudge": _touch_payload(OUTBOUND_NUDGE),
        "min_gap_hours": MIN_GAP.total_seconds() / 3600,
        # Espelha _BUSINESS_START/_BUSINESS_END/seg-sex de follow_up/service.py —
        # valores estáveis do clamp comercial (mudá-los lá exige atualizar aqui e o teste).
        "business_window": {
            "start": "09:00",
            "end": "16:00",
            "days": "seg-sex",
            "timezone": "America/Sao_Paulo",
        },
    }


@router.get("/definition")
async def get_cadence_definition() -> dict:
    return build_cadence_definition()
