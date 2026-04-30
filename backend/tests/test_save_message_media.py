from unittest.mock import MagicMock, patch


def test_save_message_includes_media_fields():
    """save_message passes media_url and message_type to the DB insert."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "abc-123"}
    ]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        from app.conversations.service import save_message

        save_message(
            "conv-id",
            "lead-id",
            "user",
            "[audio transcrito: oi tudo bem]",
            media_url="1234567890",
            message_type="audio",
        )

    insert_payload = mock_sb.table.return_value.insert.call_args[0][0]
    assert insert_payload["media_url"] == "1234567890"
    assert insert_payload["message_type"] == "audio"


def test_save_message_without_media_fields():
    """save_message omits media keys when not provided (no None pollution)."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "abc-123"}
    ]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        from app.conversations.service import save_message

        save_message("conv-id", "lead-id", "user", "olá")

    insert_payload = mock_sb.table.return_value.insert.call_args[0][0]
    assert "media_url" not in insert_payload
    assert "message_type" not in insert_payload
