"""Retry do 9º dígito também para falha EXPLÍCITA da Meta (131026 via webhook).

Contexto (10/07/2026, run "DSP 10-07-26 10-57"): retry_undelivered_cold_sends só
selecionava mensagens em delivery_status='undelivered' — o estado que o reconciler de
timeout aplica ao limbo 'accepted'. Quando a Meta reporta a falha EXPLICITAMENTE pelo
webhook de status (131026 "Message undeliverable"), _handle_delivery_status grava
delivery_status='failed' e marca o broadcast_lead como failed — e esses leads nunca
entravam no retry estruturado do 9º dígito, exatamente o cenário para o qual ele foi
construído. 4 de 22 envios da run ao vivo caíram nesse buraco.

Estes testes fixam:
1. broadcast_leads failed com error_message='Message undeliverable' (não retentados,
   sem delivered_at) entram no retry.
2. O caminho clássico (undelivered por timeout) continua funcionando no mesmo tick.
3. Outras falhas (ex.: billing 131042) NÃO entram — o filtro é estrito por
   'Message undeliverable'. (Garantido pelo .eq no error_message; aqui validamos que
   sem linhas failed-undeliverable nada é retentado.)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _worker_sb(undelivered_msgs, wamid_bls, failed_bls):
    mock_msgs = MagicMock()
    (mock_msgs.select.return_value
        .eq.return_value
        .filter.return_value
        .gte.return_value
        .limit.return_value
        .execute.return_value) = MagicMock(data=undelivered_msgs)

    mock_bls = MagicMock()
    # Caminho 1 (timeout): select().in_().eq().is_().execute()
    (mock_bls.select.return_value
        .in_.return_value
        .eq.return_value
        .is_.return_value
        .execute.return_value) = MagicMock(data=wamid_bls)
    # Caminho 2 (webhook failed 131026): select().eq().eq().eq().is_().gte().limit().execute()
    (mock_bls.select.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
        .gte.return_value
        .limit.return_value
        .execute.return_value) = MagicMock(data=failed_bls)

    sb = MagicMock()
    sb.table.side_effect = lambda name: {
        "messages": mock_msgs,
        "broadcast_leads": mock_bls,
    }[name]
    return sb


_BL_FAILED = {
    "id": "bl-failed-1",
    "broadcast_id": "b1",
    "lead_id": "lead-1",
    "wamid": "wamid.failed",
    "leads": {"id": "lead-1", "phone": "5534996755500", "wa_id": None},
    "broadcasts": {
        "channel_id": "ch1",
        "template_name": "tpl",
        "template_language_code": "pt_BR",
        "template_variables": {},
    },
}

_BL_TIMEOUT = dict(_BL_FAILED, id="bl-timeout-1", lead_id="lead-2", wamid="wamid.limbo")


@pytest.mark.asyncio
async def test_webhook_failed_undeliverable_enters_ninth_digit_retry():
    """131026 explícito (broadcast_lead failed + 'Message undeliverable') deve ser retentado."""
    sb = _worker_sb(undelivered_msgs=[], wamid_bls=[], failed_bls=[_BL_FAILED])
    retry_one = AsyncMock()
    with patch("app.broadcast.worker.get_supabase", return_value=sb), \
         patch("app.broadcast.worker._retry_single_undelivered", retry_one):
        from app.broadcast.worker import retry_undelivered_cold_sends
        await retry_undelivered_cold_sends()

    assert retry_one.await_count == 1, (
        "falha explícita 131026 não entrou no retry do 9º dígito — "
        "lead perdido sem a dupla tentativa estruturada"
    )
    assert retry_one.await_args[0][1] == _BL_FAILED


@pytest.mark.asyncio
async def test_timeout_and_webhook_failed_both_retried_same_tick():
    """O caminho clássico (undelivered por timeout) segue vivo junto com o novo."""
    sb = _worker_sb(
        undelivered_msgs=[{"wamid": "wamid.limbo"}],
        wamid_bls=[_BL_TIMEOUT],
        failed_bls=[_BL_FAILED],
    )
    retry_one = AsyncMock()
    with patch("app.broadcast.worker.get_supabase", return_value=sb), \
         patch("app.broadcast.worker._retry_single_undelivered", retry_one):
        from app.broadcast.worker import retry_undelivered_cold_sends
        await retry_undelivered_cold_sends()

    retried_ids = {call.args[1]["id"] for call in retry_one.await_args_list}
    assert retried_ids == {"bl-timeout-1", "bl-failed-1"}


@pytest.mark.asyncio
async def test_nothing_to_retry_is_noop():
    """Sem limbo e sem failed-undeliverable → nenhuma retentativa."""
    sb = _worker_sb(undelivered_msgs=[], wamid_bls=[], failed_bls=[])
    retry_one = AsyncMock()
    with patch("app.broadcast.worker.get_supabase", return_value=sb), \
         patch("app.broadcast.worker._retry_single_undelivered", retry_one):
        from app.broadcast.worker import retry_undelivered_cold_sends
        await retry_undelivered_cold_sends()

    assert retry_one.await_count == 0
