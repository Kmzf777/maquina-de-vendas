"""Falsos 'undelivered' e alertas CRITICAL de canal silencioso (QA 10/07).

Dois defeitos compostos, provados em produção na run "DSP 10-07-26 10-57":

A) INBOUND CARIMBADO: save_message (conversations.service) gravava
   delivery_status='accepted' para QUALQUER mensagem com wamid — inclusive
   role='user'. A Meta só envia webhook de status para mensagens que NÓS
   enviamos, então todo inbound virava 'undelivered' fantasma no
   reconcile_delivery_timeouts e inflava o detector de canal silencioso
   (o alerta CRITICAL do canal do João às 14:23 era 100% áudios INBOUND).

B) CORRIDA WEBHOOK × PERSISTÊNCIA: o buffer processor envia as bolhas e só
   persiste DEPOIS de todas enviadas (jitter incluso). O status da Meta chegou
   às 14:06:14 e o insert só às 14:06:20 — o UPDATE por wamid casou 0 linhas
   em silêncio, a bolha nasceu 'accepted' para sempre e virou 'undelivered'
   fantasma (bolhas da Marisete, comprovadamente entregues — ela respondeu).
   Fix: aplicação de status com guarda de rank (nunca rebaixa delivered→sent
   em webhook fora de ordem) + retentativas em background (~2min) quando a
   linha ainda não existe; o reconciler de 30min segue como backstop.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


# ─── A. save_message: inbound nunca tem ciclo de entrega ─────────────────────

def _capture_insert_sb():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "m1"}])
    return sb


def test_save_message_user_with_wamid_gets_no_delivery_status():
    """Mensagem do LEAD (role=user) tem wamid mas NÃO tem ciclo de status da Meta."""
    sb = _capture_insert_sb()
    with patch("app.conversations.service.get_supabase", return_value=sb):
        from app.conversations.service import save_message
        save_message("conv1", "lead1", "user", "Sim", sent_by="user", wamid="wamid.inbound")

    payload = sb.table.return_value.insert.call_args[0][0]
    assert "delivery_status" not in payload, (
        "inbound carimbado com 'accepted' vira 'undelivered' fantasma no reconciler "
        "e dispara alerta CRITICAL falso de canal silencioso"
    )


def test_save_message_assistant_with_wamid_still_accepted():
    """Regressão: mensagem NOSSA continua nascendo 'accepted' (aceite ≠ entrega)."""
    sb = _capture_insert_sb()
    with patch("app.conversations.service.get_supabase", return_value=sb):
        from app.conversations.service import save_message
        save_message("conv1", "lead1", "assistant", "oi", wamid="wamid.out")

    payload = sb.table.return_value.insert.call_args[0][0]
    assert payload["delivery_status"] == "accepted"


# ─── B. aplicação de status com rank + retry contra a corrida ────────────────

def _status_sb(update_rows, existing_row):
    """Mock: update().eq().in_().execute() e select().eq().limit().execute()."""
    sb = MagicMock()
    msgs = sb.table.return_value
    msgs.update.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(data=update_rows)
    msgs.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[existing_row] if existing_row else []
    )
    return sb


def test_apply_status_upgrades_from_lower_ranks():
    from app.webhook.meta_router import _apply_message_status
    sb = _status_sb(update_rows=[{"id": "m1"}], existing_row=None)
    assert _apply_message_status(sb, "wamid.x", "delivered") is True
    allowed = sb.table.return_value.update.return_value.eq.return_value.in_.call_args[0][1]
    assert "accepted" in allowed and "sent" in allowed and "undelivered" in allowed
    assert "read" not in allowed and "delivered" not in allowed and "failed" not in allowed


def test_apply_status_never_downgrades_delivered_to_sent():
    """Webhook 'sent' chegando DEPOIS do 'delivered' não rebaixa o estado."""
    from app.webhook.meta_router import _apply_message_status
    sb = _status_sb(update_rows=[], existing_row={"id": "m1", "delivery_status": "delivered"})
    assert _apply_message_status(sb, "wamid.x", "sent") is True  # linha existe: nada a fazer
    allowed = sb.table.return_value.update.return_value.eq.return_value.in_.call_args[0][1]
    assert "delivered" not in allowed and "read" not in allowed


def test_apply_status_returns_false_when_row_missing():
    """Linha ainda não inserida (corrida) → False, para o chamador retentar."""
    from app.webhook.meta_router import _apply_message_status
    sb = _status_sb(update_rows=[], existing_row=None)
    assert _apply_message_status(sb, "wamid.x", "delivered") is False


@pytest.mark.asyncio
async def test_retry_applies_status_after_late_insert():
    """A linha aparece entre as retentativas → status aplicado, retry encerra."""
    from app.webhook import meta_router as mr
    sb_hit = _status_sb(update_rows=[{"id": "m1"}], existing_row=None)
    calls = {"n": 0}

    def _fake_apply(sb, wamid, status):
        calls["n"] += 1
        return calls["n"] >= 2  # 1ª retentativa falha, 2ª acha a linha

    async def _no_sleep(_):
        return None

    with patch.object(mr, "get_supabase", return_value=sb_hit), \
         patch.object(mr, "_apply_message_status", side_effect=_fake_apply), \
         patch.object(mr.asyncio, "sleep", _no_sleep):
        await mr._retry_message_status("wamid.x", "delivered")

    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_handle_delivery_status_spawns_retry_on_race():
    """update casa 0 linhas e a linha não existe → retentativa em background agendada."""
    from app.webhook import meta_router as mr
    sb = _status_sb(update_rows=[], existing_row=None)
    spawned = []

    def _fake_create_task(coro):
        spawned.append(coro)
        coro.close()  # não executa — só registra o agendamento
        return MagicMock()

    with patch.object(mr, "get_supabase", return_value=sb), \
         patch("app.broadcast.service.find_broadcast_lead_by_wamid", return_value=None), \
         patch.object(mr.asyncio, "create_task", _fake_create_task):
        await mr._handle_delivery_status("wamid.race", "delivered", [], "5511999999999")

    assert len(spawned) == 1, "corrida detectada deve agendar retentativa em background"


@pytest.mark.asyncio
async def test_handle_delivery_status_no_retry_when_update_hits():
    """Caminho feliz: update casa na hora → nenhuma retentativa agendada."""
    from app.webhook import meta_router as mr
    sb = _status_sb(update_rows=[{"id": "m1"}], existing_row={"id": "m1"})
    # delivered também consulta lead_id p/ procedência — devolve vazio (sem lead)
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    spawned = []

    def _fake_create_task(coro):
        spawned.append(coro)
        coro.close()
        return MagicMock()

    with patch.object(mr, "get_supabase", return_value=sb), \
         patch("app.broadcast.service.find_broadcast_lead_by_wamid", return_value=None), \
         patch.object(mr.asyncio, "create_task", _fake_create_task):
        await mr._handle_delivery_status("wamid.ok", "delivered", [], "5511999999999")

    assert not spawned
