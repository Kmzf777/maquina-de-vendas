"""Retry de transporte nos hot writes de broadcast (wartime T6b, 10/07).

Sob rajada de disparo, a Meta/Supabase derrubam a conexão HTTP/2 (GOAWAY →
httpx.RemoteProtocolError) no meio do request. Sem retry, um mark/increment de
broadcast se perdia silenciosamente (lead preso em 'processing', contador furado).
Os marks/increments/requeue/save_wamid de broadcast/service.py agora rodam via
`run_with_retry` (app/db/supabase.py): repete SOMENTE httpx.TransportError; erro
HTTP de aplicação (4xx/5xx) NUNCA é retentado nem mascarado.

Parte broadcast do critério de aceite 5 da spec.
"""
import httpx
import pytest
from unittest.mock import MagicMock, patch

import app.broadcast.service as svc


def _http_status_error():
    resp = httpx.Response(
        409, json={"message": "conflict"},
        request=httpx.Request("POST", "https://db.supabase.co"),
    )
    return httpx.HTTPStatusError("409", request=resp.request, response=resp)


def _sb_flaky_then_ok(chain_data=None):
    """Supabase fake cujo execute() derruba a conexão na 1ª tentativa e responde na 2ª.

    Qualquer encadeamento (table/update/eq/is_/in_/rpc/...) devolve o mesmo objeto,
    então o fake serve para todas as funções sob teste sem montar chain por chain.
    """
    chain = MagicMock()
    for attr in ("table", "update", "eq", "is_", "in_", "rpc", "select", "limit"):
        getattr(chain, attr).return_value = chain
    ok = MagicMock()
    ok.data = chain_data if chain_data is not None else [{"id": "x"}]
    chain.execute.side_effect = [httpx.RemoteProtocolError("GOAWAY"), ok]
    return chain


def _sb_app_error():
    chain = MagicMock()
    for attr in ("table", "update", "eq", "is_", "in_", "rpc", "select", "limit"):
        getattr(chain, attr).return_value = chain
    chain.execute.side_effect = _http_status_error()
    return chain


_HOT_WRITES = [
    ("mark_broadcast_lead_sent", ("bl-1",)),
    ("mark_broadcast_lead_failed", ("bl-1", "erro")),
    ("requeue_broadcast_lead", ("bl-1",)),
    ("save_broadcast_lead_wamid", ("bl-1", "wamid.x")),
    ("increment_broadcast_sent", ("bc-1",)),
    ("increment_broadcast_failed", ("bc-1",)),
    ("increment_broadcast_delivered", ("bc-1",)),
    ("mark_broadcast_lead_delivered", ("bl-1",)),
]


@pytest.mark.parametrize("fn_name,args", _HOT_WRITES)
def test_goaway_transitorio_e_retentado_e_completa(fn_name, args):
    """RemoteProtocolError na 1ª tentativa → retry refaz o request e a escrita vence."""
    sb = _sb_flaky_then_ok()
    with patch.object(svc, "get_supabase", return_value=sb), \
         patch("app.db.supabase.time.sleep"):  # sem backoff real na suíte
        result = getattr(svc, fn_name)(*args)

    assert sb.execute.call_count == 2  # 1 falha de transporte + 1 sucesso
    if fn_name == "mark_broadcast_lead_delivered":
        assert result is True  # contrato de retorno preservado através do retry


@pytest.mark.parametrize("fn_name,args", _HOT_WRITES)
def test_erro_http_de_aplicacao_nao_e_retentado(fn_name, args):
    """HTTPStatusError propaga na hora — retry jamais mascara erro de aplicação."""
    sb = _sb_app_error()
    with patch.object(svc, "get_supabase", return_value=sb), \
         patch("app.db.supabase.time.sleep"):
        with pytest.raises(httpx.HTTPStatusError):
            getattr(svc, fn_name)(*args)

    assert sb.execute.call_count == 1  # uma única tentativa


def test_transporte_persistente_esgota_e_propaga():
    """3 quedas seguidas (todas as tentativas) → a última exceção sobe ao caller."""
    chain = MagicMock()
    for attr in ("table", "update", "eq"):
        getattr(chain, attr).return_value = chain
    chain.execute.side_effect = httpx.RemoteProtocolError("GOAWAY")

    with patch.object(svc, "get_supabase", return_value=chain), \
         patch("app.db.supabase.time.sleep"):
        with pytest.raises(httpx.RemoteProtocolError):
            svc.mark_broadcast_lead_sent("bl-1")

    assert chain.execute.call_count == 3  # _DB_RETRY_ATTEMPTS
