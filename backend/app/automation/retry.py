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
