"""API da aba "Conversões enviadas" do /trafego.

Só admin: exige o JWT de admin aqui (`exigir_admin`, o mesmo das rotas de atribuição do
/trafego) e a proxy do Next (`frontend/src/app/api/traffic/conversoes`) o repassa pelo
`adminProxy`. O backend é alcançável em api.canastrainteligencia.com, e a lista expõe nome de
lead e valor de venda — a proteção não pode ficar só na proxy.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from app.campaigns.traffic_router import exigir_admin
from app.conversions.sweep import _paged
from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/conversions", tags=["conversions"])
_TZ = ZoneInfo("America/Sao_Paulo")
_PERIODS = {"7d": 7, "30d": 30, "90d": 90}
_LIMIT = 1000  # teto do PostgREST; acima disso a UI avisa que a lista está truncada


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    c = Counter((r["stage"], r["platform"], r["status"]) for r in rows)
    return [{"stage": s, "platform": p, "status": st, "n": n} for (s, p, st), n in sorted(c.items())]


def _range(period: str, date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    # Datas do filtro são dias do calendário de São Paulo; o fim é exclusivo (dia seguinte 00h).
    if date_from or date_to:
        ini = datetime.fromisoformat(date_from).replace(tzinfo=_TZ).isoformat() if date_from else None
        fim = (datetime.fromisoformat(date_to).replace(tzinfo=_TZ) + timedelta(days=1)).isoformat() if date_to else None
        return ini, fim
    days = _PERIODS.get(period)
    if not days:
        return None, None
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(), None


@router.get("/ads")
def conversions_ads(period: str = "30d", date_from: str | None = None, date_to: str | None = None,
                    platform: str | None = None, stage: str | None = None, status: str | None = None,
                    _admin: str = Depends(exigir_admin)):
    ini, fim = _range(period, date_from, date_to)
    sb = get_supabase()

    def filtrar(q):
        if ini:
            q = q.gte("event_at", ini)
        if fim:
            q = q.lt("event_at", fim)
        if platform:
            q = q.eq("platform", platform)
        if stage:
            q = q.eq("stage", stage)
        if status:
            q = q.eq("status", status)
        return q

    rows = filtrar(sb.table("ad_conversions").select(
        "id,lead_id,platform,stage,status,event_at,value,currency,segment,campaign_name,"
        "click_id_type,attempts,last_error,sent_at,lead:leads(name)"
    )).order("event_at", desc=True).limit(_LIMIT).execute().data or []
    # Contadores sobre TODAS as linhas do filtro, não só as 1000 da lista: select leve paginado
    # (ordem estável por id, senão o Postgres pode repetir/pular linhas entre páginas).
    todas = _paged(lambda: filtrar(sb.table("ad_conversions").select("stage,platform,status")).order("id"))
    return {"rows": rows, "counts": summarize(todas), "truncated": len(rows) == _LIMIT}
