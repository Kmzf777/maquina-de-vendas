"""Testes do recibo de leitura sob demanda (tique azul) no atendimento humano.

Regra de negócio: quando um vendedor HUMANO responde uma conversa pela plataforma, o
recibo de leitura da Meta deve ser enviado para a ÚLTIMA mensagem inbound do cliente
naquele exato momento — garantindo "nunca lido sem resposta". Cobre o helper
``get_latest_inbound_wamid`` e o endpoint ``POST /api/conversations/{id}/read-receipt``.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.conversations.service import get_latest_inbound_wamid


def _messages_chain(execute_data):
    """MagicMock da cadeia supabase para a query de ``messages``.

    Qualquer método encadeado (table/select/eq/order/limit) devolve o próprio mock;
    o ramo null-safe ``.not_.is_(...)`` também. ``.execute()`` retorna um objeto com
    ``.data = execute_data``.
    """
    chain = MagicMock()
    for attr in ("table", "select", "eq", "order", "limit"):
        getattr(chain, attr).return_value = chain
    chain.not_.is_.return_value = chain
    chain.execute.return_value = MagicMock(data=execute_data)
    return chain


def _conversations_chain(conv_data):
    """MagicMock da cadeia supabase para o lookup de ``conversations`` (com ``.single()``)."""
    chain = MagicMock()
    for attr in ("table", "select", "eq", "single"):
        getattr(chain, attr).return_value = chain
    chain.execute.return_value = MagicMock(data=conv_data)
    return chain


FAKE_CHANNEL = {
    "id": "ch-meta-1",
    "provider": "meta_cloud",
    "provider_config": {"phone_number_id": "PHONE_ID"},
}


# --- helper get_latest_inbound_wamid -----------------------------------------

def test_get_latest_inbound_wamid_returns_most_recent():
    """Retorna o wamid da inbound mais recente e aplica os filtros corretos."""
    chain = _messages_chain([{"wamid": "wamid.mais_recente"}])
    with patch("app.conversations.service.get_supabase", return_value=chain):
        result = get_latest_inbound_wamid("conv-1")

    assert result == "wamid.mais_recente"
    chain.table.assert_called_once_with("messages")
    chain.eq.assert_any_call("conversation_id", "conv-1")
    chain.eq.assert_any_call("role", "user")
    chain.not_.is_.assert_called_once_with("wamid", "null")
    chain.order.assert_called_once_with("created_at", desc=True)
    chain.limit.assert_called_once_with(1)


def test_get_latest_inbound_wamid_none_when_no_inbound():
    """Sem inbound (query devolve lista vazia) → None."""
    chain = _messages_chain([])
    with patch("app.conversations.service.get_supabase", return_value=chain):
        assert get_latest_inbound_wamid("conv-sem-inbound") is None


def test_get_latest_inbound_wamid_none_on_exception():
    """Fail-open: qualquer erro na query → None (não propaga)."""
    with patch("app.conversations.service.get_supabase", side_effect=Exception("DB down")):
        assert get_latest_inbound_wamid("conv-erro") is None


# --- endpoint POST /api/conversations/{id}/read-receipt ----------------------

@pytest.fixture
def client():
    """FastAPI mínimo com o router de conversations.

    ``raise_server_exceptions=False`` para que uma exceção não-tratada vire HTTP 500 —
    assim os testes de fail-soft provam de fato que o endpoint responde 200, nunca 500.
    """
    from app.conversations.router import router as conversations_router

    app = FastAPI()
    app.include_router(conversations_router)
    return TestClient(app, raise_server_exceptions=False)


def test_read_receipt_calls_mark_read_with_latest_wamid(client):
    """Fluxo feliz: marca a última inbound como lida via ``provider.mark_read(wamid)``."""
    sb = _conversations_chain({"channel_id": "ch-meta-1"})
    provider = MagicMock()
    provider.mark_read = AsyncMock(return_value={"success": True})
    with (
        patch("app.conversations.router.get_supabase", return_value=sb),
        patch("app.conversations.router.get_latest_inbound_wamid", return_value="wamid.latest"),
        patch("app.conversations.router.get_channel_by_id", return_value=FAKE_CHANNEL),
        patch("app.conversations.router.get_provider", return_value=provider),
    ):
        resp = client.post("/api/conversations/conv-1/read-receipt")

    assert resp.status_code == 200
    assert resp.json() == {"marked": True, "wamid": "wamid.latest"}
    provider.mark_read.assert_awaited_once_with("wamid.latest")


def test_read_receipt_noop_when_no_inbound(client):
    """No-op: sem inbound pendente NÃO chama get_provider/mark_read; responde marked=False."""
    sb = _conversations_chain({"channel_id": "ch-meta-1"})
    with (
        patch("app.conversations.router.get_supabase", return_value=sb),
        patch("app.conversations.router.get_latest_inbound_wamid", return_value=None),
        patch("app.conversations.router.get_channel_by_id") as mock_get_channel,
        patch("app.conversations.router.get_provider") as mock_get_provider,
    ):
        resp = client.post("/api/conversations/conv-sem-inbound/read-receipt")

    assert resp.status_code == 200
    assert resp.json() == {"marked": False, "wamid": None}
    mock_get_channel.assert_not_called()
    mock_get_provider.assert_not_called()


def test_read_receipt_fail_soft_when_mark_read_raises(client):
    """Fail-soft: erro no ``provider.mark_read`` responde 200 com marked=False (nunca 500)."""
    sb = _conversations_chain({"channel_id": "ch-meta-1"})
    provider = MagicMock()
    provider.mark_read = AsyncMock(side_effect=RuntimeError("Meta indisponível"))
    with (
        patch("app.conversations.router.get_supabase", return_value=sb),
        patch("app.conversations.router.get_latest_inbound_wamid", return_value="wamid.latest"),
        patch("app.conversations.router.get_channel_by_id", return_value=FAKE_CHANNEL),
        patch("app.conversations.router.get_provider", return_value=provider),
    ):
        resp = client.post("/api/conversations/conv-1/read-receipt")

    assert resp.status_code == 200
    assert resp.json() == {"marked": False, "wamid": "wamid.latest"}
    provider.mark_read.assert_awaited_once_with("wamid.latest")


def test_read_receipt_404_when_conversation_missing(client):
    """Conversa inexistente → 404 (contrato do passo 1); não tenta resolver wamid."""
    sb = _conversations_chain(None)
    with (
        patch("app.conversations.router.get_supabase", return_value=sb),
        patch("app.conversations.router.get_latest_inbound_wamid") as mock_wamid,
    ):
        resp = client.post("/api/conversations/conv-inexistente/read-receipt")

    assert resp.status_code == 404
    mock_wamid.assert_not_called()
