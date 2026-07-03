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


def test_save_message_bridge_does_not_reset_unread_count():
    """Item 1 (review final Frente B): a ponte pós-handoff salva como
    role="assistant"/sent_by="bridge" — é sinalização ESTÁTICA de roteamento, não
    atendimento do vendedor. Zerar unread_count aqui apagaria o badge que a própria
    mensagem do lead acabou de incrementar (caso real: Maycon manda 1 áudio
    pós-handoff → ponte responde → vendedor nunca veria nada em "Não lidas")."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "abc-123"}
    ]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        from app.conversations.service import save_message

        save_message(
            "conv-id", "lead-id", "assistant", "seu atendimento tá com o João agora",
            sent_by="bridge",
        )

    update_payload = mock_sb.table.return_value.update.call_args[0][0]
    assert "unread_count" not in update_payload


def test_save_message_seller_still_resets_unread_count():
    """Regressão: sent_by="seller" (vendedor humano respondendo de verdade, mesmo
    valor checado pelo trigger update_conversation_seller_response — ver
    migrations/20260525_sla_seller_columns.sql) continua zerando unread_count. Só a
    ponte (sent_by="bridge") é a exceção introduzida pelo Item 1."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "abc-123"}
    ]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        from app.conversations.service import save_message

        save_message(
            "conv-id", "lead-id", "assistant", "oi, tudo bem?", sent_by="seller",
        )

    update_payload = mock_sb.table.return_value.update.call_args[0][0]
    assert update_payload["unread_count"] == 0
