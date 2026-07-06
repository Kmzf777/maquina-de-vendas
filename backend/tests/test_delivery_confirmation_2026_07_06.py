"""Desacoplamento aceite-vs-entrega e varredura de mensagens em limbo.

Contexto (06/07/2026): o disparo "atualizacao_cadastro_informacoes — 15:39" ficou como
enviado/realizado enquanto a entrega física falhou. A Meta responde ao send com HTTP 200
+ wamid e message_status="accepted" — só ACEITE na fila. O sistema gravava
messages.delivery_status="sent" nesse instante, criando o falso positivo, e nunca revisava
o estado quando o webhook de status não chegava (canal "NUMERO ARTHUR" silencioso).

Estes testes fixam:
1. save_message grava "accepted" (não "sent") quando há wamid — o estado real só avança
   via webhook (_handle_delivery_status).
2. reconcile_delivery_timeouts marca como "undelivered" as mensagens presas em "accepted"
   além do timeout e alerta sobre o canal silencioso.
"""

from unittest.mock import MagicMock, patch


# ─── 1. save_message: aceite não é entrega ───────────────────────────────────

def _capture_insert_sb():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "m1"}])
    return sb


def test_save_message_marks_accepted_when_wamid_present():
    """Com wamid, delivery_status inicial deve ser 'accepted' — nunca 'sent'."""
    sb = _capture_insert_sb()
    with patch("app.conversations.service.get_supabase", return_value=sb):
        from app.conversations.service import save_message
        save_message("conv1", "lead1", "assistant", "oi", wamid="wamid.abc")

    payload = sb.table.return_value.insert.call_args[0][0]
    assert payload["delivery_status"] == "accepted", (
        f"aceite da Meta não é entrega; esperado 'accepted', veio {payload.get('delivery_status')!r}"
    )


def test_save_message_no_delivery_status_without_wamid():
    """Sem wamid não há status de entrega para carimbar."""
    sb = _capture_insert_sb()
    with patch("app.conversations.service.get_supabase", return_value=sb):
        from app.conversations.service import save_message
        save_message("conv1", "lead1", "assistant", "oi")

    payload = sb.table.return_value.insert.call_args[0][0]
    assert "delivery_status" not in payload


# ─── 2. reconcile_delivery_timeouts: fecha o limbo + alerta canal silencioso ──

def _reconcile_sb(stuck_rows, conv_rows, existing_alerts=None):
    mock_msgs = MagicMock()
    (mock_msgs.select.return_value
        .eq.return_value
        .filter.return_value
        .gte.return_value
        .lt.return_value
        .limit.return_value
        .execute.return_value) = MagicMock(data=stuck_rows)
    mock_msgs.update.return_value.in_.return_value.execute.return_value = MagicMock(data=stuck_rows)

    mock_conv = MagicMock()
    mock_conv.select.return_value.in_.return_value.execute.return_value = MagicMock(data=conv_rows)

    mock_alerts = MagicMock()
    (mock_alerts.select.return_value
        .eq.return_value
        .eq.return_value
        .gte.return_value
        .contains.return_value
        .limit.return_value
        .execute.return_value) = MagicMock(data=existing_alerts or [])

    sb = MagicMock()
    sb.table.side_effect = lambda name: {
        "messages": mock_msgs,
        "conversations": mock_conv,
        "system_alerts": mock_alerts,
    }[name]
    return sb, mock_msgs


def test_reconcile_flips_accepted_to_undelivered_and_alerts_silent_channel():
    """3 mensagens presas do mesmo canal → undelivered + alerta de canal silencioso."""
    stuck = [
        {"id": "m1", "wamid": "w1", "conversation_id": "c1", "created_at": "2026-07-06T18:00:00+00:00"},
        {"id": "m2", "wamid": "w2", "conversation_id": "c1", "created_at": "2026-07-06T18:01:00+00:00"},
        {"id": "m3", "wamid": "w3", "conversation_id": "c2", "created_at": "2026-07-06T18:02:00+00:00"},
    ]
    convs = [
        {"id": "c1", "channel_id": "ch-arthur"},
        {"id": "c2", "channel_id": "ch-arthur"},
    ]
    sb, mock_msgs = _reconcile_sb(stuck, convs)
    fake_alert = MagicMock()

    with patch("app.broadcast.worker.get_supabase", return_value=sb), \
         patch("app.broadcast.worker.get_channel_by_id", return_value={"name": "NUMERO ARTHUR"}), \
         patch("app.alerts.service.create_system_alert", fake_alert):
        from app.broadcast.worker import reconcile_delivery_timeouts
        reconcile_delivery_timeouts()

    update_arg = mock_msgs.update.call_args[0][0]
    assert update_arg == {"delivery_status": "undelivered"}
    ids_marked = mock_msgs.update.return_value.in_.call_args[0][1]
    assert set(ids_marked) == {"m1", "m2", "m3"}

    assert fake_alert.called, "canal com 3 não-entregas deve gerar alerta de canal silencioso"
    alert_type = fake_alert.call_args[0][0]
    assert alert_type == "channel_delivery_silent"
    assert fake_alert.call_args.kwargs["metadata"]["channel_id"] == "ch-arthur"


def test_reconcile_below_threshold_does_not_alert():
    """Menos que o limiar por canal → marca undelivered mas não alerta (ruído evitado)."""
    stuck = [
        {"id": "m1", "wamid": "w1", "conversation_id": "c1", "created_at": "2026-07-06T18:00:00+00:00"},
    ]
    convs = [{"id": "c1", "channel_id": "ch-arthur"}]
    sb, mock_msgs = _reconcile_sb(stuck, convs)
    fake_alert = MagicMock()

    with patch("app.broadcast.worker.get_supabase", return_value=sb), \
         patch("app.broadcast.worker.get_channel_by_id", return_value={"name": "NUMERO ARTHUR"}), \
         patch("app.alerts.service.create_system_alert", fake_alert):
        from app.broadcast.worker import reconcile_delivery_timeouts
        reconcile_delivery_timeouts()

    assert mock_msgs.update.called
    assert not fake_alert.called


def test_reconcile_noop_when_no_limbo():
    """Sem mensagens presas → early return, sem update."""
    sb, mock_msgs = _reconcile_sb([], [])
    with patch("app.broadcast.worker.get_supabase", return_value=sb):
        from app.broadcast.worker import reconcile_delivery_timeouts
        reconcile_delivery_timeouts()
    assert not mock_msgs.update.called
