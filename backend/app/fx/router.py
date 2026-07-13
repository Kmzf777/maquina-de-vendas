from fastapi import APIRouter

from app.fx.service import get_usd_brl

router = APIRouter(prefix="/api/fx", tags=["fx"])


@router.get("/rate")
async def read_rate():
    """Cotação USD→BRL do painel. Sempre 200: degrada em vez de falhar."""
    fx = await get_usd_brl()
    return {
        "rate": fx.rate,
        "date": fx.date,
        "stale": fx.stale,
        "source": fx.source,
    }
