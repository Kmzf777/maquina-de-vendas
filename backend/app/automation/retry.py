from datetime import datetime, timedelta

_BACKOFF = [timedelta(hours=1), timedelta(hours=4), timedelta(hours=24)]
_MAX_RETRIES = len(_BACKOFF)


def calculate_next_retry(retry_count: int, now: datetime) -> tuple[datetime, int, bool]:
    """
    Returns (next_retry_at, new_retry_count, is_final_failure).
    is_final_failure=True when retry_count >= MAX_RETRIES.
    """
    if retry_count >= _MAX_RETRIES:
        return now, retry_count, True
    return now + _BACKOFF[retry_count], retry_count + 1, False


# ── Shared failure logic (moved from campaigns/worker.py in Task 4) ──────────
# campaigns/worker.py re-exports these for back-compat.

# Status HTTP da Meta que não adianta retentar (template/locale/param errados):
# o disparo nunca vai ser aceito — cancelar a enrollment em vez de re-armar.
_PERMANENT_STATUS = {400, 403, 404}


def _is_permanent_error(exc: Exception) -> bool:
    """True para rejeições da Meta que não mudam com retry (4xx de template/param).

    Cobre dois formatos: httpx.HTTPStatusError (raise_for_status em 4xx) e o
    RuntimeError que send_template/send_text levantam quando a Meta devolve HTTP 200
    com erro embutido ('... rejected (missing messages ...)').
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in _PERMANENT_STATUS:
        return True
    if isinstance(exc, RuntimeError) and "rejected" in str(exc):
        return True
    return False


def decide_failure_update(exc: Exception, retry_count: int, now: datetime) -> dict:
    """Pure: kwargs para update_enrollment que SEMPRE tiram a enrollment do estado
    imediatamente-due — raiz do loop que inflou meta_webhook_logs.

    - Erro permanente (4xx / rejeição embutida): status='cancelled'.
    - Erro transitório: backoff via calculate_next_retry (1h/4h/24h, teto 3);
      ao estourar o teto, cancela.
    """
    err = str(exc)[:500]
    if _is_permanent_error(exc):
        return {"status": "cancelled", "last_error": err}
    next_at, new_count, final = calculate_next_retry(retry_count, now)
    if final:
        return {"status": "cancelled", "last_error": err}
    iso = next_at.isoformat()
    return {
        "retry_count": new_count,
        "next_retry_at": iso,
        "next_execute_at": iso,
        "last_error": err,
    }
