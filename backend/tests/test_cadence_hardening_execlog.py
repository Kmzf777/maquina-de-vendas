from unittest.mock import MagicMock, patch


def test_log_execution_inserts_row():
    from app.campaigns import execution_log
    sb = MagicMock()
    with patch.object(execution_log, "get_supabase", return_value=sb):
        execution_log.log_execution(
            enrollment_id="e1", campaign_id="c1", lead_id="l1",
            node_id="n1", node_type="send", status="done", log="Template enviado",
        )
    sb.table.assert_called_with("campaign_execution_log")
    sb.table.return_value.insert.assert_called_once()


def test_log_execution_never_raises_on_db_error():
    from app.campaigns import execution_log
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError("DB down")
    # Must not raise even when Supabase is unavailable.
    with patch.object(execution_log, "get_supabase", return_value=sb):
        execution_log.log_execution(
            enrollment_id="e1", campaign_id="c1", status="failed", log="erro simulado"
        )


def test_list_execution_log_returns_data():
    from app.campaigns import execution_log
    sb = MagicMock()
    rows = [{"id": "r1", "campaign_id": "c1", "status": "done"}]
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = rows
    with patch.object(execution_log, "get_supabase", return_value=sb):
        result = execution_log.list_execution_log("c1", limit=10)
    assert result == rows


def test_list_execution_log_returns_empty_on_error():
    from app.campaigns import execution_log
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.side_effect = RuntimeError("DB down")
    with patch.object(execution_log, "get_supabase", return_value=sb):
        result = execution_log.list_execution_log("c1")
    assert result == []
