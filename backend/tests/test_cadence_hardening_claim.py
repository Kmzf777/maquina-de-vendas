from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


def test_get_due_enrollments_orders_by_next_execute_at():
    from app.campaigns import service
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.lte.return_value
    chain.order.return_value.limit.return_value.execute.return_value.data = []
    with patch.object(service, "get_supabase", return_value=sb):
        service.get_due_enrollments(datetime.now(timezone.utc), limit=20)
    chain.order.assert_called_once_with("next_execute_at", desc=False)


def test_claim_enrollment_true_when_row_updated():
    from app.campaigns import service
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.eq.return_value.or_.return_value.execute.return_value.data = [{"id": "e1"}]
    with patch.object(service, "get_supabase", return_value=sb):
        assert service.claim_enrollment("e1", datetime.now(timezone.utc)) is True


def test_claim_enrollment_false_when_no_row():
    from app.campaigns import service
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.eq.return_value.or_.return_value.execute.return_value.data = []
    with patch.object(service, "get_supabase", return_value=sb):
        assert service.claim_enrollment("e1", datetime.now(timezone.utc)) is False
