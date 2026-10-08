# backend/app/conversions/sender.py
"""Envia as linhas pendentes de `ad_conversions`.

Claim atômico por `claimed_at` (mesmo padrão de follow_up/scheduler._claim_followup_job):
duas réplicas do worker nunca enviam a mesma linha. Claim com mais de 10 min é considerado
abandonado (worker morreu no meio) e pode ser retomado.

Modo teste (`CONVERSIONS_TEST_MODE=true`): a Meta só mostra o evento em Test Events e o Google
só valida (`validateOnly`) — nada é registrado de verdade. Por isso um envio de teste bem-sucedido
NÃO consome a linha: ela continua `pendente` (sem gastar tentativa) e sai de verdade quando o modo
teste for desligado.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.conversions import google, meta
from app.conversions.eligibility import WINDOW, parse_ts
from app.conversions.types import SendResult
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

BACKOFF = (60, 300, 1800, 7200, 43200)  # 1 min, 5 min, 30 min, 2 h, 12 h; a 6ª falha vira erro
_STALE_CLAIM = timedelta(minutes=10)
# Em modo teste a mesma linha volta a ser testada só depois de 6 h (senão o tick de 5 min
# reenviaria a amostra inteira sem parar) e cada tick testa no máximo 10 — amostra basta.
TEST_MODE_PAUSE = timedelta(hours=6)
TEST_MODE_LIMIT = 10
_CLIENTS = {"meta": meta, "google": google}


def _test_mode() -> bool:
    return (os.getenv("CONVERSIONS_TEST_MODE") or "").strip().lower() in ("1", "true", "yes", "on")


def outside_window(row: dict[str, Any], now: datetime) -> bool:
    """Meta recusa event_time > 7 dias antes do envio; Google recusa clique > 90 dias."""
    if row["platform"] == "meta":
        return now - parse_ts(row["event_at"]) > WINDOW["meta"]
    return now - parse_ts(row["click_at"]) > WINDOW["google"]


def next_state(row: dict[str, Any], result: SendResult, now: datetime, *, test_mode: bool = False) -> dict[str, Any]:
    """Colunas a gravar na linha depois de um envio. Puro (sem I/O) para ser testável."""
    if result.ok and test_mode:
        # Sucesso de teste não é envio real: a linha fica na fila, sem gastar tentativa.
        return {"status": "pendente", "claimed_at": None, "last_error": None,
                "last_response": {"modo_teste": True, "resposta": result.response},
                "next_attempt_at": (now + TEST_MODE_PAUSE).isoformat()}
    attempts = int(row.get("attempts") or 0) + 1
    upd: dict[str, Any] = {"attempts": attempts, "claimed_at": None, "last_response": result.response}
    if result.ok:
        upd.update(status="enviado", sent_at=now.isoformat(), last_error=None)
    elif result.permanent or attempts > len(BACKOFF):
        upd.update(status="erro", last_error=result.error)
    else:
        upd.update(status="pendente", last_error=result.error,
                   next_attempt_at=(now + timedelta(seconds=BACKOFF[attempts - 1])).isoformat())
    return upd


def _claim(sb, row_id: str, now: datetime) -> bool:
    """UPDATE guardado por status + claim livre/abandonado: só um processo vence a corrida.
    Erro na query → False (não envia; o próximo tick tenta de novo) — nunca arrisca envio
    duplicado."""
    stale = (now - _STALE_CLAIM).isoformat()
    try:
        res = sb.table("ad_conversions").update({"claimed_at": now.isoformat()}) \
            .eq("id", row_id).eq("status", "pendente") \
            .or_(f"claimed_at.is.null,claimed_at.lt.{stale}").execute()
        return bool(res.data)
    except Exception as exc:
        logger.warning("[CONVERSOES] falha ao reivindicar %s: %s", row_id, exc)
        return False


def _send(row: dict[str, Any], lead: dict[str, Any]) -> SendResult:
    """Exceção inesperada do cliente (linha malformada, bug) vira falha transitória: entra no
    backoff e acaba em `erro`, em vez de deixar a linha presa no claim e reenviada a cada 10 min."""
    try:
        return _CLIENTS[row["platform"]].send(row, lead)
    except Exception as exc:
        logger.exception("[CONVERSOES] exceção ao enviar %s", row.get("id"))
        return SendResult(ok=False, permanent=False, error=f"exceção: {exc!r}"[:500])


def run_sender(now: datetime | None = None, limit: int = 100) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    platforms = [p for p, c in _CLIENTS.items() if c.enabled()]
    counts = {"enviado": 0, "pendente": 0, "erro": 0, "fora_da_janela": 0, "ignorado": 0}
    if not platforms:
        return counts
    test_mode = _test_mode()
    if test_mode:
        limit = min(limit, TEST_MODE_LIMIT)
    sb = get_supabase()
    due = sb.table("ad_conversions").select("*").eq("status", "pendente") \
        .in_("platform", platforms).lte("next_attempt_at", now.isoformat()) \
        .order("next_attempt_at").limit(limit).execute().data or []
    if not due:
        return counts
    lead_ids = sorted({r["lead_id"] for r in due})
    leads = {l["id"]: l for l in (sb.table("leads").select("id,email,phone,wa_id")
                                  .in_("id", lead_ids).execute().data or [])}
    sale_ids = sorted({r["sale_id"] for r in due if r.get("sale_id")})
    canceladas = set()
    if sale_ids:
        canceladas = {s["id"] for s in (sb.table("sales").select("id,status").in_("id", sale_ids)
                                        .execute().data or []) if s.get("status") == "cancelada"}

    for row in due:
        if not _claim(sb, row["id"], now):
            continue
        if outside_window(row, now):
            upd = {"status": "fora_da_janela", "claimed_at": None}
        elif row.get("sale_id") in canceladas:
            upd = {"status": "ignorado", "claimed_at": None, "last_error": "venda cancelada antes do envio"}
        else:
            result = _send(row, leads.get(row["lead_id"]) or {})
            upd = next_state(row, result, now, test_mode=test_mode)
            if not result.ok:
                logger.warning("[CONVERSOES] %s %s %s falhou: %s", row["platform"], row["stage"], row["id"], result.error)
        sb.table("ad_conversions").update(upd).eq("id", row["id"]).execute()
        counts[upd["status"]] += 1
    logger.info("[CONVERSOES] envio%s: %s", " (modo teste)" if test_mode else "", counts)
    return counts
