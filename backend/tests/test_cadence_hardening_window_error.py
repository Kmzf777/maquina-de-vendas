# backend/tests/test_cadence_hardening_window_error.py
from datetime import datetime, timezone
from app.automation.retry import decide_failure_update, _is_permanent_error


class _Resp:
    def __init__(self, status): self.status_code = status

class _HTTP(Exception):
    def __init__(self, status): self.response = _Resp(status); super().__init__(f"http {status}")


def test_permanent_meta_error_cancels_immediately():
    upd = decide_failure_update(_HTTP(400), retry_count=0, now=datetime.now(timezone.utc))
    assert upd["status"] == "cancelled"


def test_transient_error_backs_off():
    upd = decide_failure_update(RuntimeError("network blip"), 0, datetime.now(timezone.utc))
    assert "next_execute_at" in upd and upd.get("status") != "cancelled"


def test_embedded_rejected_is_permanent():
    assert _is_permanent_error(RuntimeError("template rejected (missing ...)")) is True
