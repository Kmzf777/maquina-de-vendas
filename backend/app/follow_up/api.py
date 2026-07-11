"""API somente-leitura da DEFINIÇÃO da cadência de follow-up (painel do CRM).

O painel visual de Follow-up (aba em /campanhas) renderiza a esteira de toques a
partir deste endpoint, mantendo `follow_up/cadence.py` como única fonte de verdade —
uma cópia hardcoded no frontend divergiria em silêncio a cada ajuste do motor.

Os JOBS vivos (follow_up_jobs) não passam por aqui: o CRM os lê direto do Supabase
(mesmo padrão de broadcasts/campaigns), com RLS/service key do lado Next.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.follow_up.cadence import CADENCE, MIN_GAP, OUTBOUND_NUDGE, Touch

router = APIRouter(prefix="/api/cadence", tags=["cadence"])

# Visibilidade do ESPELHO do motor no CRM (decisão executiva 10/07: oculto até a
# análise interna concluir; religável pela própria interface, sem deploy). Mesmo
# padrão Redis do /api/buffer (config:buffer_enabled). SÓ APRESENTAÇÃO: não toca o
# status da campanha nem as guardas 409 — impossível causar execução dupla por aqui.
_MIRROR_VISIBILITY_KEY = "config:cadence_mirror_visible"


@router.get("/mirror-visibility")
async def get_mirror_visibility(request: Request) -> dict:
    """Default OCULTO: só é visível com opt-in explícito ('1') gravado no Redis."""
    val = await request.app.state.redis.get(_MIRROR_VISIBILITY_KEY)
    return {"visible": val == "1"}


@router.post("/mirror-visibility")
async def set_mirror_visibility(request: Request) -> dict:
    body = await request.json()
    visible = bool(body.get("visible", False))
    await request.app.state.redis.set(_MIRROR_VISIBILITY_KEY, "1" if visible else "0")
    return {"visible": visible}


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
