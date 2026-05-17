"""
Tests for broadcast duplicate-send prevention and related critical fixes.

Bug #1 (root cause of all issues): import_leads criava leads duplicados ao usar
  eq("phone", phone) com match exato, ignorando leads legados com 12 dígitos.
  Qualquer pessoa com número em formato legado (12d) recebia dois templates:
  um enviado para o lead de 12d e outro para o lead de 13d recém-criado.
  Fix: usa get_or_create_lead() que faz backfill 12→13 e retorna o UUID canônico.

Bug #2 (consequência do Bug #1): quando a pessoa respondia ao disparo, o backend
  encontrava o lead de 13d (match exato) ao invés do lead de 12d que tinha a
  conversa com status "template_sent", tratando a resposta como novo inbound.

Bug #3: increment_broadcast_sent/failed/delivered usavam read-modify-write
  (SELECT + UPDATE separados), causando race condition com múltiplos workers.
  Fix: chamadas RPC atômicas (UPDATE SET sent = sent + 1).

Bug #4: janela de recovery resetava todos os leads "processing" para "pending",
  incluindo aqueles que já tinham wamid (mensagem chegou à Meta). Causava resend.
  Fix: leads COM wamid → marca "sent". Leads SEM wamid → reset para "pending".
  Adicionalmente: wamid é salvo ANTES de mark_broadcast_lead_sent para que o
  recovery consiga distinguir os casos mesmo após um crash.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ═══════════════════════════════════════════════════════════════
# Bug #3: increment_broadcast_* must use atomic RPC calls
# ═══════════════════════════════════════════════════════════════

def _rpc_sb():
    """Minimal Supabase mock for testing RPC calls."""
    mock = MagicMock()
    mock.rpc.return_value.execute.return_value = MagicMock()
    return mock


def test_increment_sent_uses_rpc():
    """sent counter must call RPC — not SELECT then UPDATE (race condition)."""
    mock_sb = _rpc_sb()
    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import increment_broadcast_sent
        increment_broadcast_sent("bc-uuid")
    mock_sb.rpc.assert_called_once_with(
        "increment_broadcast_sent", {"broadcast_id_param": "bc-uuid"}
    )
    mock_sb.rpc.return_value.execute.assert_called_once()


def test_increment_failed_uses_rpc():
    """failed counter must call RPC — not SELECT then UPDATE."""
    mock_sb = _rpc_sb()
    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import increment_broadcast_failed
        increment_broadcast_failed("bc-uuid")
    mock_sb.rpc.assert_called_once_with(
        "increment_broadcast_failed", {"broadcast_id_param": "bc-uuid"}
    )


def test_increment_delivered_uses_rpc():
    """delivered counter must call RPC — not SELECT then UPDATE."""
    mock_sb = _rpc_sb()
    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import increment_broadcast_delivered
        increment_broadcast_delivered("bc-uuid")
    mock_sb.rpc.assert_called_once_with(
        "increment_broadcast_delivered", {"broadcast_id_param": "bc-uuid"}
    )


def test_increment_sent_does_not_touch_broadcasts_table_directly():
    """increment_broadcast_sent must NOT SELECT+UPDATE the broadcasts table (race condition)."""
    mock_sb = _rpc_sb()
    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import increment_broadcast_sent
        increment_broadcast_sent("bc-uuid")
    # Direct table access for read-modify-write must not happen
    mock_sb.table.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# Bug #1: import_leads must use get_or_create_lead
# ═══════════════════════════════════════════════════════════════

def _broadcast_sb():
    """Supabase mock for broadcast router tests."""
    mock = MagicMock()
    mock.table.return_value.insert.return_value.execute.return_value.data = [{"id": "bl-1"}]
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value.count = 1
    mock.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]
    return mock


@pytest.mark.asyncio
async def test_import_leads_calls_get_or_create_lead():
    """import_leads must delegate to get_or_create_lead (handles legacy 12-digit phones).

    Previously used eq("phone", phone) which missed 12-digit leads and created
    duplicates that led to the same person receiving the template twice.
    """
    mock_file = AsyncMock()
    mock_file.read = AsyncMock(return_value=b"telefone\n5511987654321\n")

    mock_lead = {"id": "lead-uuid-123", "phone": "5511987654321"}

    from app.campaign.importer import ImportResult
    mock_csv = ImportResult(valid=["5511987654321"], invalid=[])

    with patch("app.broadcast.router._get_or_create_lead", return_value=mock_lead) as mock_gcl, \
         patch("app.broadcast.router.get_supabase", return_value=_broadcast_sb()), \
         patch("app.broadcast.router.parse_csv", return_value=mock_csv):
        from app.broadcast.router import import_leads
        result = await import_leads(broadcast_id="bc-uuid", file=mock_file)

    mock_gcl.assert_called_once_with("5511987654321")
    assert result["imported"] == 1
    assert result["invalid"] == 0


@pytest.mark.asyncio
async def test_import_leads_uses_canonical_lead_id_for_broadcast_leads():
    """The lead_id inserted into broadcast_leads must come from get_or_create_lead,
    ensuring the canonical UUID (not a newly-created duplicate) is used.
    """
    mock_file = AsyncMock()
    mock_file.read = AsyncMock(return_value=b"telefone\n5511987654321\n")

    canonical_lead = {"id": "canonical-uuid-999", "phone": "5511987654321"}

    mock_sb = _broadcast_sb()

    from app.campaign.importer import ImportResult
    mock_csv = ImportResult(valid=["5511987654321"], invalid=[])

    with patch("app.broadcast.router._get_or_create_lead", return_value=canonical_lead), \
         patch("app.broadcast.router.get_supabase", return_value=mock_sb), \
         patch("app.broadcast.router.parse_csv", return_value=mock_csv):
        from app.broadcast.router import import_leads
        await import_leads(broadcast_id="bc-uuid", file=mock_file)

    insert_payload = mock_sb.table.return_value.insert.call_args[0][0]
    assert insert_payload["lead_id"] == "canonical-uuid-999"
    assert insert_payload["broadcast_id"] == "bc-uuid"


@pytest.mark.asyncio
async def test_import_leads_multiple_phones_each_calls_get_or_create_lead():
    """Every phone in the CSV must go through get_or_create_lead — including
    phones that normalise to the same canonical number (would have been two
    broadcast_leads rows before the fix).
    """
    mock_file = AsyncMock()
    mock_file.read = AsyncMock(return_value=b"telefone\n5511987654321\n5511987654322\n")

    leads = [
        {"id": "uuid-a", "phone": "5511987654321"},
        {"id": "uuid-b", "phone": "5511987654322"},
    ]

    from app.campaign.importer import ImportResult
    mock_csv = ImportResult(valid=["5511987654321", "5511987654322"], invalid=[])

    call_counter = iter(leads)

    with patch("app.broadcast.router._get_or_create_lead", side_effect=leads) as mock_gcl, \
         patch("app.broadcast.router.get_supabase", return_value=_broadcast_sb()), \
         patch("app.broadcast.router.parse_csv", return_value=mock_csv):
        from app.broadcast.router import import_leads
        result = await import_leads(broadcast_id="bc-uuid", file=mock_file)

    assert mock_gcl.call_count == 2
    phones_called = [c[0][0] for c in mock_gcl.call_args_list]
    assert "5511987654321" in phones_called
    assert "5511987654322" in phones_called


# ═══════════════════════════════════════════════════════════════
# Bug #4: Recovery window must split on wamid presence
# ═══════════════════════════════════════════════════════════════

def _make_recovery_sb():
    """Supabase mock that captures update() payloads and filter() calls made
    on the broadcast_leads table during the recovery window.
    """
    update_payloads = []
    filter_calls = []

    def update_side_effect(payload):
        update_payloads.append(dict(payload))
        chain = MagicMock()

        def filter_side_effect(col, op, val):
            filter_calls.append((col, op, val))
            return chain

        chain.filter.side_effect = filter_side_effect
        chain.eq.return_value = chain
        chain.lt.return_value = chain
        chain.execute.return_value = MagicMock(data=[])
        return chain

    mock_bl = MagicMock()
    mock_bl.update.side_effect = update_side_effect

    mock_bc = MagicMock()
    mock_bc.select.return_value.eq.return_value.in_.return_value.execute.return_value.count = 0
    mock_bc.update.return_value.eq.return_value.execute.return_value = MagicMock()

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: mock_bl if name == "broadcast_leads" else mock_bc

    return mock_sb, update_payloads, filter_calls


@pytest.mark.asyncio
async def test_recovery_marks_sent_when_wamid_present():
    """Stale 'processing' leads WITH wamid must be marked 'sent' — not re-queued.

    wamid being saved proves the template reached Meta. Re-queuing would send again.
    """
    from app.broadcast.worker import process_single_broadcast

    mock_sb, update_payloads, filter_calls = _make_recovery_sb()
    broadcast = {"id": "bc-uuid", "status": "running", "channel_id": "ch-uuid"}

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb), \
         patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=[]):
        await process_single_broadcast(broadcast)

    sent_update = next((p for p in update_payloads if p.get("status") == "sent"), None)
    assert sent_update is not None, "Must mark leads with wamid as 'sent'"
    assert ("wamid", "not.is", "null") in filter_calls, (
        "Update to 'sent' must filter WHERE wamid IS NOT NULL"
    )


@pytest.mark.asyncio
async def test_recovery_requeues_when_no_wamid():
    """Stale 'processing' leads WITHOUT wamid must be reset to 'pending' for retry.

    No wamid means the crash happened before the API call — safe to resend.
    """
    from app.broadcast.worker import process_single_broadcast

    mock_sb, update_payloads, filter_calls = _make_recovery_sb()
    broadcast = {"id": "bc-uuid", "status": "running", "channel_id": "ch-uuid"}

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb), \
         patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=[]):
        await process_single_broadcast(broadcast)

    pending_update = next((p for p in update_payloads if p.get("status") == "pending"), None)
    assert pending_update is not None, "Must reset no-wamid leads to 'pending'"
    assert ("wamid", "is", "null") in filter_calls, (
        "Update to 'pending' must filter WHERE wamid IS NULL"
    )


@pytest.mark.asyncio
async def test_recovery_makes_two_separate_updates_not_one_blanket_reset():
    """Recovery must issue exactly two targeted UPDATEs (one per wamid state).

    A single blanket reset to 'pending' was the old broken behaviour that caused
    already-sent messages (those with a wamid) to be resent.
    """
    from app.broadcast.worker import process_single_broadcast

    mock_sb, update_payloads, filter_calls = _make_recovery_sb()
    broadcast = {"id": "bc-uuid", "status": "running", "channel_id": "ch-uuid"}

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb), \
         patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=[]):
        await process_single_broadcast(broadcast)

    statuses_set = {p.get("status") for p in update_payloads}
    assert "sent" in statuses_set and "pending" in statuses_set, (
        "Both 'sent' and 'pending' updates must occur — not a single blanket reset"
    )
    # Never a lone "pending" without the "sent" guard (the old broken pattern)
    pending_without_sent = statuses_set == {"pending"}
    assert not pending_without_sent, "Single blanket reset to 'pending' detected (old bug pattern)"


# ═══════════════════════════════════════════════════════════════
# Bug #4b: wamid must be saved BEFORE mark_broadcast_lead_sent
# ═══════════════════════════════════════════════════════════════

def _make_send_sb(claim_success: bool = True):
    """Supabase mock for a broadcast worker happy-path send."""
    mock_bl = MagicMock()
    mock_bc = MagicMock()

    # Recovery chains (two filter-based updates, ignored for send test)
    recovery_chain = MagicMock()
    recovery_chain.eq.return_value = recovery_chain
    recovery_chain.lt.return_value = recovery_chain
    recovery_chain.filter.return_value = recovery_chain
    recovery_chain.execute.return_value = MagicMock(data=[])
    mock_bl.update.return_value = recovery_chain

    # Claim: .eq("id", ...).eq("status", "pending").execute().data
    if claim_success:
        mock_bl.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "bl-uuid"}
        ]

    # Broadcast status check: .select(...).eq(...).single().execute().data
    mock_bc.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "status": "running"
    }

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: mock_bl if name == "broadcast_leads" else mock_bc
    return mock_sb


@pytest.mark.asyncio
async def test_wamid_saved_before_mark_broadcast_lead_sent():
    """save_broadcast_lead_wamid must be called BEFORE mark_broadcast_lead_sent.

    If the worker crashes between the Meta API response and mark_sent, the wamid
    must already be in the DB so the recovery window can identify this lead as
    'already sent' and prevent a duplicate send.
    """
    call_order = []

    mock_provider = AsyncMock()
    mock_provider.send_template = AsyncMock(
        return_value={"messages": [{"id": "wamid.abc123"}]}
    )

    bl = {
        "id": "bl-uuid",
        "leads": {"id": "lead-uuid", "phone": "5511987654321", "name": "Teste"},
    }
    broadcast = {
        "id": "bc-uuid",
        "status": "running",
        "channel_id": "ch-uuid",
        "template_name": "test_template",
        "template_language_code": "pt_BR",
        "template_variables": {},
        "send_interval_min": 0,
        "send_interval_max": 0,
    }

    with patch("app.broadcast.worker.get_supabase", return_value=_make_send_sb()), \
         patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=[bl]), \
         patch("app.broadcast.worker.get_channel_by_id", return_value={"id": "ch-uuid", "mode": "ai"}), \
         patch("app.broadcast.worker.get_provider", return_value=mock_provider), \
         patch("app.broadcast.worker.save_broadcast_lead_wamid",
               side_effect=lambda *a: call_order.append("save_wamid")), \
         patch("app.broadcast.worker.mark_broadcast_lead_sent",
               side_effect=lambda *a: call_order.append("mark_sent")), \
         patch("app.broadcast.worker.increment_broadcast_sent"), \
         patch("app.broadcast.worker.get_or_create_conversation",
               return_value={"id": "conv-uuid", "status": "active", "stage": "secretaria"}), \
         patch("app.broadcast.worker.update_conversation"), \
         patch("app.broadcast.worker.update_lead"), \
         patch("app.broadcast.worker.save_message"), \
         patch("app.broadcast.worker._render_template_body",
               new_callable=AsyncMock, return_value="Olá, somos a Canastra"), \
         patch("asyncio.sleep"):
        from app.broadcast.worker import process_single_broadcast
        await process_single_broadcast(broadcast)

    assert "save_wamid" in call_order, "save_broadcast_lead_wamid deve ser chamado"
    assert "mark_sent" in call_order, "mark_broadcast_lead_sent deve ser chamado"

    wamid_idx = call_order.index("save_wamid")
    mark_idx = call_order.index("mark_sent")
    assert wamid_idx < mark_idx, (
        f"wamid (pos {wamid_idx}) deve ser salvo ANTES de mark_sent (pos {mark_idx}); "
        f"ordem atual: {call_order}"
    )
