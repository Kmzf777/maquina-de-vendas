"""Send-side do pre-flight de template (wartime T3): circuit breaker no worker.

O pre-flight do /start pega o template quebrado ANTES do disparo, mas a defesa em
profundidade vive no send: se um erro Meta da classe TEMPLATE (132000/132001/132005/
132007/132012, ou 404 de template) escapa, o lead é marcado failed SEM requeue
(retentar template quebrado é loop infinito) e um contador in-memory de erros
consecutivos por broadcast pausa a campanha no 3º — em vez de queimar a lista
inteira lead a lead (classe dos incidentes reativacao_* e automacao_valeria_to_joao).
Qualquer send OK zera o contador (falha isolada ≠ template quebrado).

Critério de aceite 2 da spec.
"""
import asyncio

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import app.broadcast.worker as worker_mod
from app.broadcast.worker import _is_template_error


@pytest.fixture(autouse=True)
def _clear_streaks():
    """O contador é módulo-level (vive entre lotes); isola cada teste."""
    worker_mod._template_error_streaks.clear()
    yield
    worker_mod._template_error_streaks.clear()


# ─── unidade: classificação do erro ───────────────────────────────────────────

def test_is_template_error_codigos_da_classe_template():
    for code in (132000, 132001, 132005, 132007, 132012):
        assert _is_template_error(400, {"code": code}) is True


def test_is_template_error_404_de_template():
    assert _is_template_error(404, {"message": "Template name does not exist in the translation"}) is True


def test_is_template_error_nao_casa_erro_generico():
    assert _is_template_error(400, {"code": 131009}) is False   # parâmetro inválido genérico
    assert _is_template_error(400, {"code": 131042}) is False   # billing tem tratamento próprio
    assert _is_template_error(404, {"message": "Unknown path components"}) is False
    assert _is_template_error(500, {}) is False


# ─── harness do worker (padrão de test_broadcast_goaway_requeue) ──────────────

def _make_send_sb():
    mock_bl = MagicMock()
    mock_bc = MagicMock()
    recovery_chain = MagicMock()
    recovery_chain.eq.return_value = recovery_chain
    recovery_chain.lt.return_value = recovery_chain
    recovery_chain.filter.return_value = recovery_chain
    recovery_chain.execute.return_value = MagicMock(data=[])
    mock_bl.update.return_value = recovery_chain
    mock_bl.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": "bl-x"}]
    mock_bc.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "running"}
    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: mock_bl if name == "broadcast_leads" else mock_bc
    return mock_sb, mock_bc


def _template_http_error(code=132000, status=400, message="Number of parameters does not match"):
    resp = httpx.Response(
        status, json={"error": {"message": message, "code": code}},
        request=httpx.Request("POST", "https://graph.facebook.com/x"),
    )
    return httpx.HTTPStatusError(str(status), request=resp.request, response=resp)


def _bl(i):
    return {"id": f"bl-{i}", "leads": {"id": f"lead-{i}", "phone": f"551199999000{i}", "wa_id": None, "name": "T"}}


_BROADCAST = {
    "id": "bc-uuid", "name": "DSP teste", "status": "running", "channel_id": "ch-uuid",
    "template_name": "reativacao_teste", "template_language_code": "pt_BR",
    "template_variables": {}, "send_interval_min": 0, "send_interval_max": 0,
}


def _run_batch(provider, leads, mock_sb):
    patches = dict(
        get_supabase=patch("app.broadcast.worker.get_supabase", return_value=mock_sb),
        pending=patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=leads),
        channel=patch("app.broadcast.worker.get_channel_by_id", return_value={"id": "ch-uuid", "mode": "ai"}),
        provider=patch("app.broadcast.worker.get_provider", return_value=provider),
        blacklist=patch("app.broadcast.worker.is_lead_blacklisted", return_value=False),
        cliente=patch("app.broadcast.worker.lead_is_customer", return_value=False),
        contato_vivo=patch("app.broadcast.worker.lead_recently_engaged", return_value=False),
        resolve=patch("app.broadcast.worker.resolve_send_target", side_effect=lambda lead, fallback, **k: fallback),
        render=patch("app.broadcast.worker._render_template_body", new=AsyncMock(return_value="txt")),
        mark_sent=patch("app.broadcast.worker.mark_broadcast_lead_sent"),
        mark_failed=patch("app.broadcast.worker.mark_broadcast_lead_failed"),
        inc_sent=patch("app.broadcast.worker.increment_broadcast_sent"),
        inc_failed=patch("app.broadcast.worker.increment_broadcast_failed"),
        requeue=patch("app.broadcast.worker.requeue_broadcast_lead"),
        wamid=patch("app.broadcast.worker.save_broadcast_lead_wamid"),
        note=patch("app.broadcast.worker.record_dispatch_note"),
        conv=patch("app.broadcast.worker.get_or_create_conversation", return_value={"id": "conv-1"}),
        upd_conv=patch("app.broadcast.worker.update_conversation"),
        upd_lead=patch("app.broadcast.worker.update_lead"),
        save_msg=patch("app.broadcast.worker.save_message"),
        trigger=patch("app.automation.triggers.fire_trigger", new_callable=AsyncMock),
        alert=patch("app.alerts.service.create_system_alert"),
        sleep=patch("asyncio.sleep", new_callable=AsyncMock),
    )
    mocks = {}
    started = []
    try:
        for name, p in patches.items():
            mocks[name] = p.start()
            started.append(p)
        asyncio.run(worker_mod.process_single_broadcast(dict(_BROADCAST)))
    finally:
        for p in started:
            p.stop()
    return mocks


# ─── 3 erros de template consecutivos → pausa + alerta critical ──────────────

def test_tres_erros_de_template_consecutivos_pausam_e_alertam():
    provider = AsyncMock()
    provider.send_template = AsyncMock(side_effect=_template_http_error(132000))
    mock_sb, mock_bc = _make_send_sb()

    mocks = _run_batch(provider, [_bl(1), _bl(2), _bl(3)], mock_sb)

    # cada lead falhou SEM requeue (retentar template quebrado = loop infinito)
    assert mocks["mark_failed"].call_count == 3
    mocks["requeue"].assert_not_called()
    # broadcast pausado no 3º erro
    pause_payloads = [c[0][0] for c in mock_bc.update.call_args_list]
    assert {"status": "paused"} in pause_payloads
    # alerta critical broadcast_template_error com nome do template e código
    mocks["alert"].assert_called_once()
    args, kwargs = mocks["alert"].call_args
    assert args[0] == "broadcast_template_error"
    assert "reativacao_teste" in args[1] + args[2]
    assert kwargs.get("severity") == "critical"
    assert kwargs.get("metadata", {}).get("meta_error_code") == 132000
    # contador consumido (não vaza para o próximo ciclo do broadcast)
    assert worker_mod._template_error_streaks.get("bc-uuid") is None


def test_404_de_template_tambem_conta_para_a_pausa():
    """Classe do incidente automacao_valeria_to_joao: locale inexistente → HTTP 404."""
    provider = AsyncMock()
    provider.send_template = AsyncMock(side_effect=_template_http_error(
        code=None, status=404, message="Template name does not exist in the translation",
    ))
    mock_sb, mock_bc = _make_send_sb()

    mocks = _run_batch(provider, [_bl(1), _bl(2), _bl(3)], mock_sb)

    assert {"status": "paused"} in [c[0][0] for c in mock_bc.update.call_args_list]
    mocks["alert"].assert_called_once()


# ─── send OK zera o contador ──────────────────────────────────────────────────

def test_send_ok_zera_o_contador_e_nao_pausa():
    """err, err, OK, err → nunca chega a 3 consecutivos: sem pausa, sem alerta."""
    ok_response = {"messages": [{"id": "wamid.ok"}]}
    provider = AsyncMock()
    provider.send_template = AsyncMock(side_effect=[
        _template_http_error(132000),
        _template_http_error(132000),
        ok_response,
        _template_http_error(132000),
    ])
    mock_sb, mock_bc = _make_send_sb()

    mocks = _run_batch(provider, [_bl(1), _bl(2), _bl(3), _bl(4)], mock_sb)

    assert mocks["mark_failed"].call_count == 3
    mocks["mark_sent"].assert_called_once()
    assert {"status": "paused"} not in [c[0][0] for c in mock_bc.update.call_args_list]
    mocks["alert"].assert_not_called()
    # o erro pós-sucesso reinicia a contagem em 1
    assert worker_mod._template_error_streaks.get("bc-uuid") == 1


# ─── erro genérico NÃO alimenta o circuit breaker ─────────────────────────────

def test_erro_generico_nao_conta_como_template_e_nao_pausa():
    provider = AsyncMock()
    provider.send_template = AsyncMock(side_effect=_template_http_error(
        code=131009, message="Parameter value is not valid",
    ))
    mock_sb, mock_bc = _make_send_sb()

    mocks = _run_batch(provider, [_bl(1), _bl(2), _bl(3)], mock_sb)

    assert mocks["mark_failed"].call_count == 3  # continua falhando lead a lead
    assert {"status": "paused"} not in [c[0][0] for c in mock_bc.update.call_args_list]
    mocks["alert"].assert_not_called()
    assert worker_mod._template_error_streaks.get("bc-uuid") is None
