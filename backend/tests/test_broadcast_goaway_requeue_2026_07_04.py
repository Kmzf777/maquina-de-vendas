"""Resiliência de rede no envio de broadcast: GOAWAY/queda transitória NÃO queima o lead.

Auditoria 04/07: o send_template do broadcast já retenta erros de transporte na camada
HTTP (_request_with_retry), mas quando uma rajada de GOAWAY esgota esses retries a
exceção httpx.TransportError (RemoteProtocolError/ConnectError) escapava para o
`except Exception` genérico do worker → mark_broadcast_lead_failed → o lead virava
FALHA PERMANENTE, sem nova tentativa. Correção: um ramo `except httpx.TransportError`
devolve o lead para 'pending' (requeue), deixando o próximo tick retentar.
"""
import httpx
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ─── service.requeue_broadcast_lead (unidade) ────────────────────────────────

def test_requeue_broadcast_lead_volta_para_pending_guardado_por_processing():
    """Requeue devolve status→pending e limpa claimed_at, guardado por status=processing
    (não reverte um lead já sent/failed)."""
    mock_sb = MagicMock()
    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import requeue_broadcast_lead
        requeue_broadcast_lead("bl-uuid")

    upd = mock_sb.table.return_value.update
    upd.assert_called_once()
    payload = upd.call_args[0][0]
    assert payload["status"] == "pending"
    assert payload["claimed_at"] is None
    # guarda por status=processing
    upd.return_value.eq.return_value.eq.assert_called_with("status", "processing")


# ─── worker: transporte transitório → requeue, não failed ────────────────────

def _make_send_sb():
    mock_bl = MagicMock()
    mock_bc = MagicMock()
    recovery_chain = MagicMock()
    recovery_chain.eq.return_value = recovery_chain
    recovery_chain.lt.return_value = recovery_chain
    recovery_chain.filter.return_value = recovery_chain
    recovery_chain.execute.return_value = MagicMock(data=[])
    mock_bl.update.return_value = recovery_chain
    mock_bl.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": "bl-uuid"}]
    mock_bc.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "running"}
    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: mock_bl if name == "broadcast_leads" else mock_bc
    return mock_sb


@pytest.mark.asyncio
async def test_transporte_goaway_faz_requeue_e_nao_marca_failed():
    """send_template estoura httpx.RemoteProtocolError (GOAWAY após retries): o lead é
    requeueado (não falha permanente) e o contador de falhas NÃO é incrementado."""
    mock_provider = AsyncMock()
    mock_provider.send_template = AsyncMock(side_effect=httpx.RemoteProtocolError("server disconnected (GOAWAY)"))

    lead = {"id": "lead-uuid", "phone": "5511999998888", "wa_id": None, "name": "Teste"}
    bl = {"id": "bl-uuid", "leads": lead}
    broadcast = {
        "id": "bc-uuid", "status": "running", "channel_id": "ch-uuid",
        "template_name": "utilidade_teste", "template_language_code": "pt_BR",
        "template_variables": {}, "send_interval_min": 0, "send_interval_max": 0,
    }

    with patch("app.broadcast.worker.get_supabase", return_value=_make_send_sb()), \
         patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=[bl]), \
         patch("app.broadcast.worker.get_channel_by_id", return_value={"id": "ch-uuid", "mode": "ai"}), \
         patch("app.broadcast.worker.get_provider", return_value=mock_provider), \
         patch("app.broadcast.worker.is_lead_blacklisted", return_value=False), \
         patch("app.broadcast.worker.requeue_broadcast_lead") as mock_requeue, \
         patch("app.broadcast.worker.mark_broadcast_lead_failed") as mock_failed, \
         patch("app.broadcast.worker.increment_broadcast_failed") as mock_inc_failed, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        from app.broadcast.worker import process_single_broadcast
        await process_single_broadcast(broadcast)

    mock_requeue.assert_called_once_with("bl-uuid")
    mock_failed.assert_not_called()
    mock_inc_failed.assert_not_called()


@pytest.mark.asyncio
async def test_erro_permanente_meta_ainda_marca_failed():
    """Contraste: um HTTPStatusError permanente (ex.: 400) CONTINUA marcando failed —
    a mudança não afeta o tratamento de rejeições permanentes."""
    resp = httpx.Response(400, json={"error": {"message": "bad", "code": 131009}}, request=httpx.Request("POST", "https://x"))
    mock_provider = AsyncMock()
    mock_provider.send_template = AsyncMock(side_effect=httpx.HTTPStatusError("400", request=resp.request, response=resp))

    lead = {"id": "lead-uuid", "phone": "5511999998888", "wa_id": None, "name": "Teste"}
    bl = {"id": "bl-uuid", "leads": lead}
    broadcast = {
        "id": "bc-uuid", "status": "running", "channel_id": "ch-uuid",
        "template_name": "utilidade_teste", "template_language_code": "pt_BR",
        "template_variables": {}, "send_interval_min": 0, "send_interval_max": 0,
    }

    with patch("app.broadcast.worker.get_supabase", return_value=_make_send_sb()), \
         patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=[bl]), \
         patch("app.broadcast.worker.get_channel_by_id", return_value={"id": "ch-uuid", "mode": "ai"}), \
         patch("app.broadcast.worker.get_provider", return_value=mock_provider), \
         patch("app.broadcast.worker.is_lead_blacklisted", return_value=False), \
         patch("app.broadcast.worker.requeue_broadcast_lead") as mock_requeue, \
         patch("app.broadcast.worker.mark_broadcast_lead_failed") as mock_failed, \
         patch("app.broadcast.worker.increment_broadcast_failed") as mock_inc_failed, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        from app.broadcast.worker import process_single_broadcast
        await process_single_broadcast(broadcast)

    mock_failed.assert_called_once()
    mock_requeue.assert_not_called()
