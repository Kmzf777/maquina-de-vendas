import hashlib
import json

import httpx
import pytest

from app.audiences import google
from app.audiences.types import Pessoa
from app.conversions import google as conv_google


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def _pessoa(**kw):
    base = dict(lead_id="L1", pl=True, atacado=False, celulares=["5534991234567"],
                emails=["jo.ao@gmail.com"], nome="joao", sobrenome="silva", cidade="uberlandia",
                uf="mg", cep="38400123", valor=100.0)
    base.update(kw)
    return Pessoa(**base)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    conv_google._reset_token_cache()
    monkeypatch.setenv("GOOGLE_ADS_CUSTOMER_ID", "186-141-6291")
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "999-000-1111")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "sec")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "rt")
    yield
    conv_google._reset_token_cache()


class _Gravador:
    def __init__(self, status=200, body=None):
        self.requests: list[httpx.Request] = []
        self.status = status
        self.body = body

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "TOK"})
        body = self.body if self.body is not None else {"requestId": f"r{len(self.api())}"}
        return httpx.Response(self.status, json=body)

    def api(self):
        return [r for r in self.requests if r.url.host == "datamanager.googleapis.com"]

    def transport(self):
        return httpx.MockTransport(self)


def test_identificadores_email_gmail_sem_ponto_e_telefone_com_mais():
    ids = google.identificadores(_pessoa())
    assert ids[0] == {"emailAddress": _h("joao@gmail.com")}
    assert ids[1] == {"phoneNumber": _h("+5534991234567")}
    assert ids[2] == {"address": {"givenName": _h("joao"), "familyName": _h("silva"),
                                  "regionCode": "BR", "postalCode": "38400123"}}
    assert all(len(i) == 1 for i in ids)


@pytest.mark.parametrize("falta", ["nome", "sobrenome", "cep"])
def test_endereco_so_com_nome_sobrenome_e_cep(falta):
    ids = google.identificadores(_pessoa(**{falta: None}))
    assert not any("address" in i for i in ids)


def test_no_maximo_10_identificadores():
    p = _pessoa(emails=[f"e{i}@x.com" for i in range(8)],
                celulares=[f"553499123456{i}" for i in range(5)])
    ids = google.identificadores(p)
    assert len(ids) == 10
    assert all("emailAddress" in i for i in ids[:8])


def test_build_member():
    m = google.build_member(_pessoa())
    assert m == {"userData": {"userIdentifiers": google.identificadores(_pessoa())}}


def test_remove_member_um_identificador():
    ident = {"emailAddress": "abc"}
    assert google.remove_member(ident) == {"userData": {"userIdentifiers": [ident]}}


def test_build_body_destino_com_login_account():
    b = google.build_body("9496018532", [{"x": 1}], validate_only=True)
    d = b["destinations"][0]
    assert d["operatingAccount"] == {"accountType": "GOOGLE_ADS", "accountId": "1861416291"}
    assert d["loginAccount"] == {"accountType": "GOOGLE_ADS", "accountId": "9990001111"}
    assert d["productDestinationId"] == "9496018532"
    assert b["audienceMembers"] == [{"x": 1}]
    assert b["consent"] == {"adUserData": "CONSENT_GRANTED", "adPersonalization": "CONSENT_GRANTED"}
    assert b["encoding"] == "HEX"
    assert b["termsOfService"] == {"customerMatchTermsOfServiceStatus": "ACCEPTED"}
    assert b["validateOnly"] is True


def test_build_body_sem_login_quando_igual(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "1861416291")
    b = google.build_body("1", [], validate_only=False)
    assert "loginAccount" not in b["destinations"][0]
    assert b["validateOnly"] is False


def test_build_body_remove_sem_terms_nem_consent():
    b = google.build_body("1", [], validate_only=False, operacao="remove")
    assert "termsOfService" not in b and "consent" not in b
    assert b["encoding"] == "HEX"


def test_ingest_repassa_validate_only_e_token():
    g = _Gravador()
    resp = google.ingest("9496018532", [google.build_member(_pessoa())], validate_only=True,
                         transport=g.transport())
    api = g.api()
    assert len(api) == 1
    assert str(api[0].url) == google.INGEST_URL
    assert api[0].headers["Authorization"] == "Bearer TOK"
    body = json.loads(api[0].content)
    assert body["validateOnly"] is True
    assert resp == [{"requestId": "r1"}]


def test_remove_usa_url_de_remove():
    g = _Gravador()
    google.remove("9496018532", [google.remove_member({"emailAddress": "a"})], validate_only=False,
                  transport=g.transport())
    api = g.api()
    assert str(api[0].url) == google.REMOVE_URL
    body = json.loads(api[0].content)
    assert "termsOfService" not in body and "consent" not in body


def test_10001_membros_geram_2_requests():
    g = _Gravador()
    membros = [google.remove_member({"emailAddress": str(i)}) for i in range(10_001)]
    resp = google.ingest("1", membros, validate_only=False, transport=g.transport())
    api = g.api()
    assert len(api) == 2
    assert len(json.loads(api[0].content)["audienceMembers"]) == 10_000
    assert len(json.loads(api[1].content)["audienceMembers"]) == 1
    assert len(resp) == 2


def test_400_vira_runtime_error_com_mensagem():
    g = _Gravador(status=400, body={"error": {"message": "INVALID_ARGUMENT x"}})
    with pytest.raises(RuntimeError, match="HTTP 400: INVALID_ARGUMENT x"):
        google.ingest("1", [{"a": 1}], validate_only=False, transport=g.transport())


def test_lista_vazia_nao_faz_request():
    g = _Gravador()
    assert google.ingest("1", [], validate_only=False, transport=g.transport()) == []
    assert google.remove("1", [], validate_only=False, transport=g.transport()) == []
    assert g.requests == []


def test_falha_no_token_vira_runtime_error():
    def handler(req):
        return httpx.Response(400, json={"error": "invalid_grant"})
    with pytest.raises(RuntimeError, match="access token"):
        google.ingest("1", [{"a": 1}], validate_only=False, transport=httpx.MockTransport(handler))
