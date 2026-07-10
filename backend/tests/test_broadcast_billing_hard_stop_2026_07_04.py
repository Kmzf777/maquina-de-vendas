"""Erro de billing 131042 deve PAUSAR o broadcast automaticamente — não só alertar.

Contexto forense (DSP - FRIOS - 04/07, prod): o envio de template é aceito pela Meta
com HTTP 200 + wamid; a falha de billing (131042 "Business eligibility payment issue")
chega DEPOIS, de forma assíncrona, via webhook de delivery-status. Por isso o pause
síncrono no worker (`except httpx.HTTPStatusError`) é código morto para esse cenário: o
send nunca levanta exceção. O handler assíncrono `_handle_delivery_status` detectava o
131042 mas só disparava o alerta — deixava o broadcast `running`, e o worker seguia
disparando os leads restantes até o operador pausar na mão.

Estes testes fixam as duas camadas da correção:
  1. o webhook de delivery-status pausa o broadcast dono do wamid ao ver 131042;
  2. o worker se auto-aborta ao iniciar um lote se já existe alerta de billing aberto
     (fecha a janela de corrida entre o 1º 131042 e o próximo tick do worker).
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ─── camada 1: helper de pause idempotente ───────────────────────────────────

def test_pause_broadcast_for_billing_updates_only_active():
    """pause_broadcast_for_billing deve marcar status=paused filtrando por running/scheduled."""
    mock_sb = MagicMock()
    update_chain = mock_sb.table.return_value.update.return_value
    update_chain.eq.return_value.in_.return_value.execute.return_value.data = [{"id": "bc"}]

    # _get_redis patchado: o marcador de billing (wartime T4) é best-effort e não
    # deve tocar um Redis real na suíte.
    with patch("app.broadcast.service.get_supabase", return_value=mock_sb), \
         patch("app.broadcast.service._get_redis", return_value=MagicMock()):
        from app.broadcast.service import pause_broadcast_for_billing
        paused = pause_broadcast_for_billing("bc")

    payload = mock_sb.table.return_value.update.call_args[0][0]
    assert payload.get("status") == "paused", f"deveria pausar; payload={payload!r}"
    # não pode clobberar completed/failed — filtra pelos estados ativos
    in_call = mock_sb.table.return_value.update.return_value.eq.return_value.in_.call_args
    assert in_call[0][0] == "status"
    assert set(in_call[0][1]) == {"running", "scheduled"}
    assert paused is True


# ─── camada 1: webhook de delivery-status pausa no 131042 ────────────────────

@pytest.mark.asyncio
async def test_delivery_status_131042_pauses_broadcast():
    """Webhook status=failed com erro 131042 deve pausar o broadcast dono do wamid."""
    mock_sb = MagicMock()
    errors = [{"code": 131042, "title": "Business eligibility payment issue"}]

    with patch("app.webhook.meta_router.get_supabase", return_value=mock_sb), \
         patch("app.broadcast.service.find_broadcast_lead_by_wamid",
               return_value={"id": "bl-uuid", "broadcast_id": "bc-uuid"}), \
         patch("app.broadcast.service.mark_broadcast_lead_failed"), \
         patch("app.broadcast.service.increment_broadcast_failed"), \
         patch("app.broadcast.service.pause_broadcast_for_billing") as mock_pause, \
         patch("app.alerts.service.fire_billing_alert", new_callable=AsyncMock) as mock_alert:
        from app.webhook.meta_router import _handle_delivery_status
        await _handle_delivery_status("wamid.abc", "failed", errors=errors)

    mock_pause.assert_called_once_with("bc-uuid")
    mock_alert.assert_awaited_once()


@pytest.mark.asyncio
async def test_delivery_status_non_billing_failure_does_not_pause():
    """Falha comum (ex.: 131026 undeliverable) NÃO deve pausar o broadcast inteiro."""
    mock_sb = MagicMock()
    errors = [{"code": 131026, "title": "Message undeliverable"}]

    with patch("app.webhook.meta_router.get_supabase", return_value=mock_sb), \
         patch("app.broadcast.service.find_broadcast_lead_by_wamid",
               return_value={"id": "bl-uuid", "broadcast_id": "bc-uuid"}), \
         patch("app.broadcast.service.mark_broadcast_lead_failed"), \
         patch("app.broadcast.service.increment_broadcast_failed"), \
         patch("app.broadcast.service.pause_broadcast_for_billing") as mock_pause, \
         patch("app.alerts.service.fire_billing_alert", new_callable=AsyncMock):
        from app.webhook.meta_router import _handle_delivery_status
        await _handle_delivery_status("wamid.abc", "failed", errors=errors)

    mock_pause.assert_not_called()


# ─── camada 2: worker se auto-aborta com alerta de billing aberto ────────────

def _billing_open_sb():
    """Mock: system_alerts tem um billing_payment_issue aberto; broadcasts para assert."""
    mock_alerts = MagicMock()
    (
        mock_alerts.select.return_value
        .eq.return_value.eq.return_value.limit.return_value.execute.return_value.data
    ) = [{"id": "alert-uuid"}]

    mock_bc = MagicMock()

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: mock_alerts if name == "system_alerts" else mock_bc
    return mock_sb, mock_bc


@pytest.mark.asyncio
async def test_worker_aborts_batch_when_billing_alert_open():
    """process_single_broadcast deve pausar e sair SEM enviar se há billing alert aberto."""
    mock_sb, mock_bc = _billing_open_sb()
    mock_provider = AsyncMock()
    broadcast = {"id": "bc-uuid", "status": "running", "channel_id": "ch-uuid",
                 "template_name": "utilidade_teste", "template_language_code": "pt_BR",
                 "template_variables": {}}

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb), \
         patch("app.broadcast.worker.get_provider", return_value=mock_provider), \
         patch("app.broadcast.worker.get_pending_broadcast_leads") as mock_pending:
        from app.broadcast.worker import process_single_broadcast
        await process_single_broadcast(broadcast)

    mock_provider.send_template.assert_not_called()
    mock_pending.assert_not_called()  # aborta antes de buscar/enviar leads
    update_payload = mock_bc.update.call_args[0][0]
    assert update_payload.get("status") == "paused"
