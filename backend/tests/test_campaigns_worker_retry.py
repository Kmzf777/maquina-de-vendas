# backend/tests/test_campaigns_worker_retry.py
import httpx
import pytest
from datetime import datetime, timezone, timedelta

from app.campaigns.worker import _is_permanent_error, decide_failure_update

NOW = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://graph.facebook.com/v21.0/x/messages")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError(f"HTTP {status}", request=req, response=resp)


class TestIsPermanentError:
    def test_404_is_permanent(self):
        assert _is_permanent_error(_http_error(404)) is True

    def test_400_is_permanent(self):
        assert _is_permanent_error(_http_error(400)) is True

    def test_embedded_rejection_runtimeerror_is_permanent(self):
        exc = RuntimeError("Meta send_template rejected (missing messages in response): {}")
        assert _is_permanent_error(exc) is True

    def test_500_is_not_permanent(self):
        assert _is_permanent_error(_http_error(500)) is False

    def test_generic_exception_is_not_permanent(self):
        assert _is_permanent_error(ValueError("boom")) is False


class TestDecideFailureUpdate:
    def test_permanent_error_cancels(self):
        upd = decide_failure_update(_http_error(404), retry_count=0, now=NOW)
        assert upd["status"] == "cancelled"
        assert "last_error" in upd

    def test_first_transient_failure_schedules_retry_1h(self):
        upd = decide_failure_update(_http_error(500), retry_count=0, now=NOW)
        assert "status" not in upd  # permanece ativa, mas adiada
        assert upd["retry_count"] == 1
        expected = (NOW + timedelta(hours=1)).isoformat()
        assert upd["next_retry_at"] == expected
        assert upd["next_execute_at"] == expected  # tira do estado due

    def test_transient_failure_at_cap_cancels(self):
        upd = decide_failure_update(_http_error(500), retry_count=3, now=NOW)
        assert upd["status"] == "cancelled"
