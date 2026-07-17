from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class _UniqueViolation(Exception):
    """Stand-in for postgrest unique-violation error (code 23505)."""
    def __init__(self):
        super().__init__("duplicate key value violates unique constraint "
                         "\"uq_campaign_enrollments_active\"")


def test_create_enrollment_duplicate_is_noop_returns_existing():
    from app.campaigns import service

    existing = {"id": "enr-existing", "campaign_id": "c1", "lead_id": "l1", "status": "active"}
    sb = MagicMock()
    # INSERT raises unique violation; fallback SELECT returns the existing row.
    sb.table.return_value.insert.return_value.execute.side_effect = _UniqueViolation()
    (sb.table.return_value.select.return_value.eq.return_value
       .eq.return_value.in_.return_value.limit.return_value.execute
       .return_value.data) = [existing]

    with patch.object(service, "get_supabase", return_value=sb):
        out = service.create_enrollment("c1", "l1", "node1", datetime.now(timezone.utc))

    assert out == existing
