from unittest.mock import MagicMock, patch


def test_get_channel_for_lead_returns_channel():
    mock_channel = {"id": "chan-001", "provider": "evolution", "provider_config": {}}
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .order.return_value.limit.return_value.execute.return_value.data = [
        {"channel_id": "chan-001", "channels": mock_channel}
    ]

    with patch("app.channels.service.get_supabase", return_value=mock_sb):
        from app.channels.service import get_channel_for_lead
        result = get_channel_for_lead("lead-001")

    assert result == mock_channel


def test_get_channel_for_lead_returns_none_when_no_conversation():
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .order.return_value.limit.return_value.execute.return_value.data = []

    with patch("app.channels.service.get_supabase", return_value=mock_sb):
        from app.channels.service import get_channel_for_lead
        result = get_channel_for_lead("lead-no-conv")

    assert result is None
