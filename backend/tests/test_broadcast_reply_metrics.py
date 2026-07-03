"""Tests for broadcast reply tracking."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


# ─── Helpers ────────────────────────────────────────────────────────────────

def _reply_sb_with_match():
    """Mock: SELECT retorna um broadcast_lead pendente."""
    mock = MagicMock()
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .in_.return_value
        .is_.return_value
        .gte.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
        .data
    ) = [{"id": "bl-uuid-123"}]
    return mock


def _reply_sb_no_match():
    """Mock: SELECT não encontra broadcast_lead na janela."""
    mock = MagicMock()
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .in_.return_value
        .is_.return_value
        .gte.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
        .data
    ) = []
    return mock


# ─── record_broadcast_reply ──────────────────────────────────────────────────

def test_record_reply_updates_first_replied_at_when_lead_found():
    """Quando há broadcast_lead dentro da janela de 48h, deve setar first_replied_at."""
    mock_sb = _reply_sb_with_match()

    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply("lead-uuid")

    update_call = mock_sb.table.return_value.update.call_args
    assert update_call is not None, "update() deve ter sido chamado"
    payload = update_call[0][0]
    assert "first_replied_at" in payload, "Payload do update deve ter first_replied_at"


def test_record_reply_no_op_when_no_broadcast_lead_found():
    """Se nenhum broadcast_lead ativo for encontrado, não deve chamar update()."""
    mock_sb = _reply_sb_no_match()

    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply("lead-uuid")

    mock_sb.table.return_value.update.assert_not_called()


def test_record_reply_queries_only_sent_or_delivered_leads():
    """A query deve filtrar status IN ('sent', 'delivered') — não 'pending' ou 'failed'."""
    mock_sb = _reply_sb_no_match()

    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply("lead-uuid")

    # Verificar que .in_() foi chamado com os status corretos
    in_call = mock_sb.table.return_value.select.return_value.eq.return_value.in_.call_args
    assert in_call is not None
    statuses = in_call[0][1]
    assert set(statuses) == {"sent", "delivered"}


def test_record_reply_only_updates_null_first_replied_at():
    """A query deve filtrar first_replied_at IS NULL — não deve sobrescrever resposta já gravada."""
    mock_sb = _reply_sb_no_match()

    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply("lead-uuid")

    is_call = (
        mock_sb.table.return_value
        .select.return_value
        .eq.return_value
        .in_.return_value
        .is_.call_args
    )
    assert is_call is not None
    col, val = is_call[0]
    assert col == "first_replied_at"
    assert val == "null"


# ─── reconcile_broadcast_replies ─────────────────────────────────────────────

def _reconcile_sb(bl_rows, msg_rows):
    """Mock com table side-effect: broadcast_leads vs messages.

    A busca de messages é em LOTE (`in_("lead_id", chunk)`), uma query por
    chunk — as linhas de msg_rows precisam de `lead_id` para o rateio em Python.
    """
    mock_bl = MagicMock()
    mock_msg = MagicMock()

    # SELECT pending broadcast_leads
    (
        mock_bl.select.return_value
        .in_.return_value
        .is_.return_value
        .gte.return_value
        .lte.return_value
        .limit.return_value
        .execute.return_value
        .data
    ) = bl_rows

    # SELECT messages (lote por chunk de lead_ids)
    (
        mock_msg.select.return_value
        .in_.return_value
        .eq.return_value
        .gt.return_value
        .lte.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
        .data
    ) = msg_rows

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: mock_msg if name == "messages" else mock_bl
    return mock_sb, mock_bl, mock_msg


def test_reconcile_updates_first_replied_at_when_message_exists():
    """Leads com mensagem inbound dentro da janela devem ter first_replied_at preenchido."""
    now = datetime.now(timezone.utc)
    sent_at = (now - timedelta(hours=5)).isoformat()
    msg_created_at = (now - timedelta(hours=4)).isoformat()

    bl = {"id": "bl-uuid", "lead_id": "lead-uuid", "sent_at": sent_at}
    message = {"id": "msg-uuid", "lead_id": "lead-uuid", "created_at": msg_created_at}

    mock_sb, mock_bl, _ = _reconcile_sb([bl], [message])

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        from app.broadcast.worker import reconcile_broadcast_replies
        reconcile_broadcast_replies()

    update_call = mock_bl.update.call_args
    assert update_call is not None, "update() deve ter sido chamado para o lead com mensagem"
    payload = update_call[0][0]
    assert payload["first_replied_at"] == msg_created_at


def test_reconcile_skips_leads_without_message():
    """Leads sem mensagem inbound na janela não devem ser atualizados."""
    now = datetime.now(timezone.utc)
    sent_at = (now - timedelta(hours=5)).isoformat()
    bl = {"id": "bl-uuid", "lead_id": "lead-uuid", "sent_at": sent_at}

    mock_sb, mock_bl, _ = _reconcile_sb([bl], [])

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        from app.broadcast.worker import reconcile_broadcast_replies
        reconcile_broadcast_replies()

    mock_bl.update.assert_not_called()


def test_reconcile_no_op_when_no_pending_leads():
    """Quando não há leads pendentes de reconciliação, não deve fazer queries de messages."""
    mock_sb, _, mock_msg = _reconcile_sb([], [])

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        from app.broadcast.worker import reconcile_broadcast_replies
        reconcile_broadcast_replies()

    mock_msg.select.assert_not_called()


def test_reconcile_batches_leads_in_single_query():
    """N leads pendentes → 1 query de messages (lote), não 1 por lead (padrão N+1)."""
    now = datetime.now(timezone.utc)
    bls = [
        {"id": f"bl-{i}", "lead_id": f"lead-{i}", "sent_at": (now - timedelta(hours=5)).isoformat()}
        for i in range(50)
    ]
    mock_sb, _, mock_msg = _reconcile_sb(bls, [])

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        from app.broadcast.worker import reconcile_broadcast_replies
        reconcile_broadcast_replies()

    assert mock_msg.select.call_count == 1, "50 leads cabem em 1 chunk → exatamente 1 query"
    in_call = mock_msg.select.return_value.in_.call_args
    assert in_call[0][0] == "lead_id"
    assert len(in_call[0][1]) == 50


def test_reconcile_respects_individual_reply_window():
    """No lote, uma resposta só conta para o lead cuja janela (sent_at→+48h) a contém.

    A query em lote usa piso/teto GLOBAIS; o corte por lead é em Python — este
    teste pina que uma mensagem anterior ao sent_at de um lead não vira
    first_replied_at dele.
    """
    now = datetime.now(timezone.utc)
    reply_at = (now - timedelta(hours=10)).isoformat()
    bl_early = {"id": "bl-early", "lead_id": "lead-early", "sent_at": (now - timedelta(hours=20)).isoformat()}
    bl_late = {"id": "bl-late", "lead_id": "lead-late", "sent_at": (now - timedelta(hours=5)).isoformat()}
    messages = [
        {"id": "m1", "lead_id": "lead-early", "created_at": reply_at},  # dentro da janela do early
        {"id": "m2", "lead_id": "lead-late", "created_at": reply_at},   # ANTES do sent_at do late → fora
    ]
    mock_sb, mock_bl, _ = _reconcile_sb([bl_early, bl_late], messages)

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        from app.broadcast.worker import reconcile_broadcast_replies
        reconcile_broadcast_replies()

    assert mock_bl.update.call_count == 1, "só o lead com resposta dentro da própria janela atualiza"
    payload = mock_bl.update.call_args[0][0]
    assert payload["first_replied_at"] == reply_at
    eq_call = mock_bl.update.return_value.eq.call_args
    assert eq_call[0] == ("id", "bl-early")
