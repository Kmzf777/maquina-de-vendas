# backend/tests/test_conversions_google.py
import hashlib
import json

import httpx
import pytest

from app.conversions import google

ROW = {
    "stage": "purchase", "event_at": "2026-10-07T15:00:00+00:00", "event_id": "purchase:S1",
    "click_id": "GCLID1", "click_id_type": "gclid", "value": 2570.0, "currency": "BRL",
}
LEAD = {"id": "L1", "wa_id": "5534992009777", "email": "Jo.Ao@gmail.com"}


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def _env(monkeypatch, test_mode="false"):
    monkeypatch.setenv("GOOGLE_ADS_CUSTOMER_ID", "186-141-6291")
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "999-000-1111")
    monkeypatch.setenv("GOOGLE_ADS_CONVERSION_ACTION_PURCHASE", "777")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "sec")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "rt")
    monkeypatch.setenv("CONVERSIONS_TEST_MODE", test_mode)


def test_build_event():
    ev = google.build_event(ROW, LEAD)
    assert ev["adIdentifiers"] == {"gclid": "GCLID1"}
    assert ev["transactionId"] == "purchase:S1"
    assert ev["eventTimestamp"] == "2026-10-07T12:00:00-03:00"  # fuso da conta (São Paulo)
    assert ev["conversionValue"] == 2570.0 and ev["currency"] == "BRL"
    ids = ev["userData"]["userIdentifiers"]
    assert {"emailAddress": _h("joao@gmail.com")} in ids
    assert {"phoneNumber": _h("+5534992009777")} in ids


def test_gbraid_vai_no_campo_certo():
    ev = google.build_event({**ROW, "click_id_type": "gbraid", "click_id": "B1"}, LEAD)
    assert ev["adIdentifiers"] == {"gbraid": "B1"}


def test_build_request(monkeypatch):
    _env(monkeypatch, test_mode="true")
    req = google.build_request(ROW, LEAD)
    d = req["destinations"][0]
    assert d["operatingAccount"]["accountId"] == "1861416291"
    assert d["loginAccount"]["accountId"] == "9990001111"
    assert d["productDestinationId"] == "777"
    assert req["validateOnly"] is True
    assert req["encoding"] == "HEX"
    assert req["consent"] == {"adUserData": "CONSENT_GRANTED", "adPersonalization": "CONSENT_GRANTED"}
    assert len(req["events"]) == 1


def test_sem_action_id_da_etapa_e_transitorio(monkeypatch):
    """Falta de configuração se resolve no servidor: backoff, não `erro` direto."""
    _env(monkeypatch)
    monkeypatch.delenv("GOOGLE_ADS_CONVERSION_ACTION_LEAD", raising=False)
    r = google.send({**ROW, "stage": "lead"}, LEAD)
    assert not r.ok and not r.permanent and "GOOGLE_ADS_CONVERSION_ACTION_LEAD" in r.error


def test_sem_credencial_e_transitorio(monkeypatch):
    _env(monkeypatch)
    monkeypatch.delenv("GOOGLE_ADS_REFRESH_TOKEN")
    r = google.send(ROW, LEAD)
    assert not r.ok and not r.permanent and "GOOGLE_ADS_REFRESH_TOKEN" in r.error


def test_configured_checa_so_as_credenciais_da_conta(monkeypatch):
    # O ID da ação é por etapa: falta dele é tratada linha a linha no send, não aqui.
    _env(monkeypatch)
    monkeypatch.delenv("GOOGLE_ADS_CONVERSION_ACTION_LEAD", raising=False)
    assert google.configured() and google.missing_config() == []
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_SECRET")
    assert not google.configured() and google.missing_config() == ["GOOGLE_ADS_CLIENT_SECRET"]


def _transport(status, body):
    def handler(req: httpx.Request):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "AT"})
        assert req.headers["Authorization"] == "Bearer AT"
        assert req.url.path.endswith("/v1/events:ingest")
        json.loads(req.content)
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def test_send_ok(monkeypatch):
    _env(monkeypatch)
    r = google.send(ROW, LEAD, transport=_transport(200, {"requestId": "R1"}))
    assert r.ok and r.response == {"requestId": "R1"}


def test_send_400_permanente_500_transitorio(monkeypatch):
    _env(monkeypatch)
    r = google.send(ROW, LEAD, transport=_transport(400, {"error": {"message": "INVALID_ARGUMENT x"}}))
    assert not r.ok and r.permanent and "INVALID_ARGUMENT" in r.error
    r = google.send(ROW, LEAD, transport=_transport(503, {"error": {"message": "x"}}))
    assert not r.ok and not r.permanent


def test_send_401_403_sao_transitorios(monkeypatch):
    """Credencial revogada/sem acesso se resolve trocando o token — a fila espera."""
    _env(monkeypatch)
    for status in (401, 403):
        r = google.send(ROW, LEAD, transport=_transport(status, {"error": {"message": "PERMISSION_DENIED"}}))
        assert not r.ok and not r.permanent, status


def test_token_falhou_e_transitorio(monkeypatch):
    _env(monkeypatch)
    t = httpx.MockTransport(lambda req: httpx.Response(500, json={}))
    r = google.send(ROW, LEAD, transport=t)
    assert not r.ok and not r.permanent and "token" in r.error.lower()
