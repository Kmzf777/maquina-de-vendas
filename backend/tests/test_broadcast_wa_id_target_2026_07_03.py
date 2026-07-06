"""Broadcast em massa deve enviar para o endereço ENTREGÁVEL (wa_id), não o phone cru.

Contexto: até 03/07/2026 o worker de broadcast enviava para `lead["phone"]`
(normalizado, que injeta o 9º dígito BR) e a query `get_pending_broadcast_leads`
nem buscava `wa_id`. Para leads que já interagiram, o `wa_id` é o `from` real que a
Meta entrega — enviar para o phone normalizado falha com Meta 131026 "Message
Undeliverable". Follow-up/LP já usavam `resolve_send_target`; o disparo frio não.
Estes testes fixam a paridade: o broadcast também prioriza wa_id sobre phone.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ─── service: a query precisa trazer wa_id (e bsuid) ─────────────────────────

def test_get_pending_broadcast_leads_selects_wa_id():
    """O SELECT de leads pendentes deve embed wa_id — senão o worker nunca o vê."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import get_pending_broadcast_leads
        get_pending_broadcast_leads("bc-uuid")

    select_arg = mock_sb.table.return_value.select.call_args[0][0]
    assert "wa_id" in select_arg, f"select deve trazer wa_id; veio: {select_arg!r}"


# ─── worker: prioriza wa_id sobre phone no envio ─────────────────────────────

def _make_send_sb():
    """Supabase mock para o happy-path de envio do broadcast worker."""
    mock_bl = MagicMock()
    mock_bc = MagicMock()

    recovery_chain = MagicMock()
    recovery_chain.eq.return_value = recovery_chain
    recovery_chain.lt.return_value = recovery_chain
    recovery_chain.filter.return_value = recovery_chain
    recovery_chain.execute.return_value = MagicMock(data=[])
    mock_bl.update.return_value = recovery_chain
    # Claim atômico: .eq("id").eq("status","pending").execute().data
    mock_bl.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": "bl-uuid"}
    ]
    mock_bc.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "status": "running"
    }

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: mock_bl if name == "broadcast_leads" else mock_bc
    return mock_sb


async def _run_single_send(lead: dict):
    """Dirige process_single_broadcast para um único lead e devolve o mock do provider."""
    mock_provider = AsyncMock()
    mock_provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.abc"}]})

    bl = {"id": "bl-uuid", "leads": lead}
    broadcast = {
        "id": "bc-uuid",
        "status": "running",
        "channel_id": "ch-uuid",
        "template_name": "utilidade_teste",
        "template_language_code": "pt_BR",
        "template_variables": {},
        "send_interval_min": 0,
        "send_interval_max": 0,
    }

    with patch("app.broadcast.worker.get_supabase", return_value=_make_send_sb()), \
         patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=[bl]), \
         patch("app.broadcast.worker.get_channel_by_id", return_value={"id": "ch-uuid", "mode": "ai"}), \
         patch("app.broadcast.worker.get_provider", return_value=mock_provider), \
         patch("app.broadcast.worker.save_broadcast_lead_wamid"), \
         patch("app.broadcast.worker.mark_broadcast_lead_sent"), \
         patch("app.broadcast.worker.increment_broadcast_sent"), \
         patch("app.broadcast.worker.record_dispatch_note"), \
         patch("app.broadcast.worker.is_lead_blacklisted", return_value=False), \
         patch("app.broadcast.worker.get_or_create_conversation",
               return_value={"id": "conv-uuid", "status": "active", "stage": "secretaria"}), \
         patch("app.broadcast.worker.update_conversation"), \
         patch("app.broadcast.worker.update_lead"), \
         patch("app.broadcast.worker.save_message"), \
         patch("app.broadcast.worker._render_template_body",
               new_callable=AsyncMock, return_value="Olá"), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        from app.broadcast.worker import process_single_broadcast
        await process_single_broadcast(broadcast)

    return mock_provider


@pytest.mark.asyncio
async def test_worker_sends_to_wa_id_when_confirmed():
    """Lead com wa_id CONFIRMADO (procedência) ≠ phone: envia para o wa_id entregável."""
    lead = {
        "id": "lead-uuid",
        "phone": "5511999998888",   # normalizado (com 9º dígito)
        "wa_id": "551188887777",    # from real do inbound — endereço entregável
        "last_customer_message_at": "2026-07-01T10:00:00+00:00",  # procedência de inbound
        "name": "Teste",
    }
    provider = await _run_single_send(lead)

    to_arg = provider.send_template.call_args.kwargs["to"]
    assert to_arg == "551188887777", f"deveria enviar para o wa_id confirmado; enviou para {to_arg!r}"


@pytest.mark.asyncio
async def test_worker_ignores_unconfirmed_wa_id_cold():
    """Lead FRIO com wa_id SEM procedência (poluído): ignora o wa_id e envia ao phone de 13 díg.

    É o caso do descarte silencioso — um wa_id de 12 dígitos plantado por harness/obsoleto,
    sem inbound que o confirme. O disparo frio (estrito) não pode confiar nele."""
    lead = {
        "id": "lead-uuid",
        "phone": "5534996652412",   # 13 díg. com o 9º dígito (E.164 canônico)
        "wa_id": "553496652412",    # 12 díg. sem procedência — não confiável
        "wa_id_confirmed_at": None,
        "last_customer_message_at": None,
        "name": "K",
    }
    provider = await _run_single_send(lead)

    to_arg = provider.send_template.call_args.kwargs["to"]
    assert to_arg == "5534996652412", f"wa_id sem procedência deveria cair para phone; enviou para {to_arg!r}"


@pytest.mark.asyncio
async def test_worker_falls_back_to_phone_without_wa_id():
    """Lead frio sem wa_id: mantém compatibilidade e envia para o phone."""
    lead = {
        "id": "lead-uuid",
        "phone": "5511999998888",
        "wa_id": None,
        "name": "Teste",
    }
    provider = await _run_single_send(lead)

    to_arg = provider.send_template.call_args.kwargs["to"]
    assert to_arg == "5511999998888", f"sem wa_id deveria cair para phone; enviou para {to_arg!r}"
