# backend/tests/test_conversions_meta.py
import hashlib
from datetime import datetime, timezone

import httpx
import pytest

from app.conversions import meta

ROW = {
    "stage": "qualified", "event_at": "2026-10-07T15:00:00+00:00", "event_id": "qualified:L1:abc",
    "click_id": "CTWA1", "value": 120.0, "currency": "BRL",
}
LEAD = {"id": "L1", "wa_id": "5534992009777", "phone": None, "email": " Joao@X.com "}


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def test_build_event_business_messaging():
    ev = meta.build_event(ROW, LEAD, waba_id="WABA9")
    assert ev["event_name"] == "LeadSubmitted"
    assert ev["event_time"] == int(datetime(2026, 10, 7, 15, tzinfo=timezone.utc).timestamp())
    assert ev["action_source"] == "business_messaging"
    assert ev["messaging_channel"] == "whatsapp"
    assert ev["event_id"] == "qualified:L1:abc"
    ud = ev["user_data"]
    assert ud["whatsapp_business_account_id"] == "WABA9"
    assert ud["ctwa_clid"] == "CTWA1"
    assert ud["ph"] == [_h("5534992009777")]
    assert ud["em"] == [_h("joao@x.com")]
    assert ev["custom_data"] == {"value": 120.0, "currency": "BRL"}


@pytest.mark.parametrize("stage,name", [
    ("qualified", "LeadSubmitted"),
    ("opportunity", "InitiateCheckout"), ("purchase", "Purchase"),
])
def test_nomes_padrao(stage, name):
    assert meta.build_event({**ROW, "stage": stage}, LEAD, waba_id="W")["event_name"] == name


def test_lead_nao_tem_evento_na_meta():
    # O clique (conversa iniciada) a Meta já conta; mandar LeadSubmitted nele viraria "maximizar conversas".
    assert "lead" not in meta.EVENT_NAMES


def test_sem_valor_nao_manda_custom_data():
    ev = meta.build_event({**ROW, "value": None}, LEAD, waba_id="W")
    assert "custom_data" not in ev


def test_payload_em_modo_teste(monkeypatch):
    monkeypatch.setenv("CONVERSIONS_TEST_MODE", "true")
    monkeypatch.setenv("META_CAPI_TEST_EVENT_CODE", "TEST123")
    assert meta.build_payload({"x": 1}) == {"data": [{"x": 1}], "test_event_code": "TEST123"}
    monkeypatch.setenv("CONVERSIONS_TEST_MODE", "false")
    assert meta.build_payload({"x": 1}) == {"data": [{"x": 1}]}


def _env(monkeypatch):
    monkeypatch.setenv("META_CAPI_DATASET_ID", "DS1")
    monkeypatch.setenv("META_CAPI_ACCESS_TOKEN", "TOK")
    monkeypatch.setenv("META_WABA_ID", "WABA9")
    monkeypatch.setenv("CONVERSIONS_TEST_MODE", "false")


def test_send_ok(monkeypatch):
    _env(monkeypatch)
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"events_received": 1, "fbtrace_id": "T"})

    r = meta.send(ROW, LEAD, transport=httpx.MockTransport(handler))
    assert r.ok and not r.permanent
    assert "/DS1/events" in seen["url"] and "access_token=TOK" in seen["url"]


def test_send_400_e_permanente(monkeypatch):
    _env(monkeypatch)
    t = httpx.MockTransport(lambda req: httpx.Response(400, json={"error": {"message": "Invalid parameter", "code": 100}}))
    r = meta.send(ROW, LEAD, transport=t)
    assert not r.ok and r.permanent and "Invalid parameter" in r.error


def test_send_500_e_429_sao_transitorios(monkeypatch):
    _env(monkeypatch)
    for code in (500, 429):
        t = httpx.MockTransport(lambda req, c=code: httpx.Response(c, json={"error": {"message": "x"}}))
        r = meta.send(ROW, LEAD, transport=t)
        assert not r.ok and not r.permanent


def test_send_auth_e_permissao_sao_transitorios(monkeypatch):
    """Token vencido/sem permissão se resolve gerando token novo — não pode matar a fila."""
    _env(monkeypatch)
    for status in (401, 403):
        t = httpx.MockTransport(lambda req, s=status: httpx.Response(s, json={"error": {"message": "x", "code": 1}}))
        r = meta.send(ROW, LEAD, transport=t)
        assert not r.ok and not r.permanent, status
    for code in (190, 102, 10, 200, 299, 4, 17, 32, 341, 613):
        t = httpx.MockTransport(lambda req, c=code: httpx.Response(400, json={"error": {"message": "x", "type": "OAuthException", "code": c}}))
        r = meta.send(ROW, LEAD, transport=t)
        assert not r.ok and not r.permanent, code


def test_send_is_transient_da_meta_e_respeitado(monkeypatch):
    _env(monkeypatch)
    t = httpx.MockTransport(lambda req: httpx.Response(400, json={"error": {"message": "x", "code": 100, "is_transient": True}}))
    r = meta.send(ROW, LEAD, transport=t)
    assert not r.ok and not r.permanent


def test_send_sem_config_e_permanente(monkeypatch):
    monkeypatch.delenv("META_CAPI_DATASET_ID", raising=False)
    r = meta.send(ROW, LEAD)
    assert not r.ok and r.permanent and "META_CAPI_DATASET_ID" in r.error


def test_enabled(monkeypatch):
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "true")
    assert meta.enabled()
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "false")
    assert not meta.enabled()
