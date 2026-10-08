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


@pytest.fixture(autouse=True)
def _sem_token_em_cache():
    google._reset_token_cache()
    yield
    google._reset_token_cache()


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
        assert not r.ok and not r.permanent and r.auth_error, status
    for status in (400, 429, 500):
        r = google.send(ROW, LEAD, transport=_transport(status, {"error": {"message": "x"}}))
        assert not r.auth_error, status


def test_token_falhou_e_transitorio(monkeypatch):
    _env(monkeypatch)
    t = httpx.MockTransport(lambda req: httpx.Response(500, json={}))
    r = google.send(ROW, LEAD, transport=t)
    assert not r.ok and not r.permanent and "token" in r.error.lower()


def test_send_200_sem_json_ainda_e_sucesso(monkeypatch):
    _env(monkeypatch)

    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3599})
        return httpx.Response(200, text="ok")

    r = google.send(ROW, LEAD, transport=httpx.MockTransport(handler))
    assert r.ok and r.response == {"raw": "ok"}


def test_access_token_fica_em_cache(monkeypatch):
    """Um refresh por envio estoura a cota do OAuth à toa: o token vale ~1 h."""
    _env(monkeypatch)
    chamadas = []

    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            chamadas.append(1)
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3599})
        return httpx.Response(200, json={"requestId": "R"})

    t = httpx.MockTransport(handler)
    for _ in range(3):
        assert google.send(ROW, LEAD, transport=t).ok
    assert len(chamadas) == 1
    # trocou a credencial (novo refresh token) → não reaproveita o token antigo
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "rt2")
    assert google.send(ROW, LEAD, transport=t).ok
    assert len(chamadas) == 2


def test_cache_do_token_expira(monkeypatch):
    _env(monkeypatch)
    relogio = [1000.0]
    monkeypatch.setattr(google, "_monotonic", lambda: relogio[0])
    chamadas = []

    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            chamadas.append(1)
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3599})
        return httpx.Response(200, json={})

    t = httpx.MockTransport(handler)
    google.send(ROW, LEAD, transport=t)
    relogio[0] += 49 * 60
    google.send(ROW, LEAD, transport=t)
    assert len(chamadas) == 1
    relogio[0] += 2 * 60
    google.send(ROW, LEAD, transport=t)
    assert len(chamadas) == 2


def test_401_no_ingest_descarta_o_token_em_cache(monkeypatch):
    _env(monkeypatch)
    chamadas = []
    respostas = iter([401, 200])

    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            chamadas.append(1)
            return httpx.Response(200, json={"access_token": "AT"})
        return httpx.Response(next(respostas), json={})

    t = httpx.MockTransport(handler)
    assert not google.send(ROW, LEAD, transport=t).ok
    assert google.send(ROW, LEAD, transport=t).ok
    assert len(chamadas) == 2


def test_falha_do_oauth_traz_o_codigo_e_e_auth(monkeypatch):
    """invalid_grant = refresh token revogado/expirado (app OAuth em "Testing" expira em 7 dias):
    a mensagem precisa dizer isso, e o sender para a plataforma no tick (disjuntor)."""
    _env(monkeypatch)
    t = httpx.MockTransport(lambda req: httpx.Response(
        400, json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."}))
    r = google.send(ROW, LEAD, transport=t)
    assert not r.ok and not r.permanent and r.auth_error
    assert "invalid_grant" in r.error and "token" in r.error.lower()


def test_oauth_fora_do_ar_nao_e_auth(monkeypatch):
    _env(monkeypatch)
    t = httpx.MockTransport(lambda req: httpx.Response(503, text="x"))
    r = google.send(ROW, LEAD, transport=t)
    assert not r.ok and not r.permanent and not r.auth_error


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("t"), httpx.ConnectError("t"), httpx.RemoteProtocolError("t")])
def test_erro_de_rede_no_google_e_transitorio(monkeypatch, exc):
    """O Google deduplica pelo transactionId: reenviar depois de uma resposta perdida é seguro."""
    _env(monkeypatch)

    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "AT"})
        raise exc

    r = google.send(ROW, LEAD, transport=httpx.MockTransport(handler))
    assert not r.ok and not r.permanent


def test_variaveis_com_espaco_sao_aparadas(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("GOOGLE_ADS_CONVERSION_ACTION_PURCHASE", " 777 \n")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", " cid ")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "rt\n")
    seen = {}

    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            seen["token_body"] = req.content.decode()
            return httpx.Response(200, json={"access_token": "AT"})
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={})

    assert google.send(ROW, LEAD, transport=httpx.MockTransport(handler)).ok
    assert seen["body"]["destinations"][0]["productDestinationId"] == "777"
    assert "client_id=cid&" in seen["token_body"] and "refresh_token=rt&" in seen["token_body"]


def test_action_configurada(monkeypatch):
    _env(monkeypatch)
    monkeypatch.delenv("GOOGLE_ADS_CONVERSION_ACTION_LEAD", raising=False)
    monkeypatch.setenv("GOOGLE_ADS_CONVERSION_ACTION_QUALIFIED", "  ")
    assert google.action_configured("purchase")
    assert not google.action_configured("lead") and not google.action_configured("qualified")
