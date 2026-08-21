import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.bling.webhook_router as wr

SECRET = "csec-super-secreto"


def _assinar(corpo: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), corpo, hashlib.sha256).hexdigest()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("BLING_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("BLING_ENABLED", "true")
    app = FastAPI()
    app.include_router(wr.router)
    return TestClient(app)


@pytest.fixture
def gravados(monkeypatch):
    linhas = []

    def fake_insert(row):
        # ON CONFLICT DO NOTHING: event_id repetido nao grava de novo
        if any(l["event_id"] == row["event_id"] for l in linhas):
            return False
        linhas.append(row)
        return True

    monkeypatch.setattr(wr, "_insert_event", fake_insert)

    async def noop_publish():
        return None

    monkeypatch.setattr(wr, "_notify_worker", noop_publish)
    return linhas


EVENTO = {
    "eventId": "01945027-150e-72b4-e7cf-4943a042cd9c",
    "date": "2026-08-18T12:18:46Z",
    "version": "v1",
    "event": "order.created",
    "companyId": "d4475854366a36c86a37e792f9634a51",
    "data": {"id": 34215992, "numero": 1234, "total": 267.0,
             "contato": {"id": 5845664414}, "situacao": {"id": 6, "valor": 6}},
}


def test_assinatura_valida_e_aceita(client, gravados):
    corpo = json.dumps(EVENTO).encode()
    resp = client.post("/webhook/bling", content=corpo,
                       headers={"X-Bling-Signature-256": _assinar(corpo),
                                "Content-Type": "application/json"})
    assert resp.status_code == 200
    assert gravados[0]["event"] == "order.created"
    assert gravados[0]["status"] == "pending"


def test_assinatura_invalida_e_rejeitada(client, gravados):
    corpo = json.dumps(EVENTO).encode()
    resp = client.post("/webhook/bling", content=corpo,
                       headers={"X-Bling-Signature-256": "sha256=" + "0" * 64,
                                "Content-Type": "application/json"})
    assert resp.status_code == 401
    assert gravados == []


def test_assinatura_ausente_e_rejeitada(client, gravados):
    corpo = json.dumps(EVENTO).encode()
    resp = client.post("/webhook/bling", content=corpo,
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 401


def test_hmac_e_sobre_os_BYTES_CRUS(client, gravados):
    """Reserializar o JSON muda os bytes e quebraria a assinatura. O receiver
    tem que hashear o corpo exatamente como chegou."""
    corpo = b'{"eventId":"e1","date":"2026-08-18T12:00:00Z","event":"order.created","data":{"id":1}}'
    resp = client.post("/webhook/bling", content=corpo,
                       headers={"X-Bling-Signature-256": _assinar(corpo),
                                "Content-Type": "application/json"})
    assert resp.status_code == 200


def test_evento_repetido_devolve_200_e_nao_duplica(client, gravados):
    """Idempotencia: o Bling pode reenviar; ambas as chamadas tem que dar 2xx."""
    corpo = json.dumps(EVENTO).encode()
    headers = {"X-Bling-Signature-256": _assinar(corpo),
               "Content-Type": "application/json"}
    assert client.post("/webhook/bling", content=corpo, headers=headers).status_code == 200
    assert client.post("/webhook/bling", content=corpo, headers=headers).status_code == 200
    assert len(gravados) == 1


def test_nao_faz_io_com_o_bling_dentro_do_request(client, gravados, monkeypatch):
    """O Bling exige 2xx em ate 5s, senao retenta por 3 dias e DESABILITA o
    webhook. Buscar o pedido completo aqui arriscaria estourar o prazo."""
    chamou = []

    class Explode:
        def __init__(self, *a, **k):
            chamou.append(True)
            raise AssertionError("o receiver nao pode instanciar BlingClient")

    monkeypatch.setattr("app.bling.client.BlingClient", Explode)
    corpo = json.dumps(EVENTO).encode()
    resp = client.post("/webhook/bling", content=corpo,
                       headers={"X-Bling-Signature-256": _assinar(corpo),
                                "Content-Type": "application/json"})
    assert resp.status_code == 200
    assert chamou == []


def test_router_registrado_no_app():
    """Guarda em NIVEL DE FONTE — ver a mesma nota em test_bling_router.py."""
    import inspect
    import app.main as main_module

    src = inspect.getsource(main_module)
    assert "from app.bling.webhook_router import router as bling_webhook_router" in src
    assert "app.include_router(bling_webhook_router)" in src


def test_webhook_router_expoe_a_rota():
    from app.bling.webhook_router import router as bling_webhook_router

    assert "/webhook/bling" in {r.path for r in bling_webhook_router.routes}


async def test_notify_worker_emite_no_dominio_bling_webhook(monkeypatch):
    """`_notify_worker` tem que chamar a API real do bus (emit_event), nao a
    `publish` inexistente — foi esse o bug que passou pelos testes originais
    porque eles monkeypatcham `_notify_worker` inteiro."""
    chamadas = []

    def fake_emit_event(domain, payload=None):
        chamadas.append(domain)
        return True

    monkeypatch.setattr("app.events.bus.emit_event", fake_emit_event)

    await wr._notify_worker()

    assert chamadas == ["bling-webhook"]


def test_bling_webhook_esta_registrado_em_domains():
    """Sem isso, `emit_event` recusa o dominio e devolve False sem emitir nada
    (ver `app/events/bus.py`). Trava a regressao de alguem reordenar/reescrever
    DOMAINS no futuro."""
    from app.events.bus import DOMAINS
    assert "bling-webhook" in DOMAINS
