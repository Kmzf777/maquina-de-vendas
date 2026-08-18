import asyncio
import base64
from datetime import datetime, timezone

import pytest

import app.bling.auth as auth
from app.bling.errors import BlingNotConfigured


class FakeTable:
    def __init__(self, store):
        self.store = store

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def upsert(self, payload, on_conflict=None):
        self.store["upserted"] = payload
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row")
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, _name):
        return FakeTable(self.store)


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    monkeypatch.setenv("BLING_REDIRECT_URI", "https://api.exemplo.com/api/bling/oauth/callback")


def test_authorize_url_tem_response_type_client_id_e_state(creds):
    url = auth.authorize_url("abc123")
    assert url.startswith("https://bling.com.br/Api/v3/oauth/authorize?")
    assert "response_type=code" in url
    assert "client_id=cid" in url
    assert "state=abc123" in url


def test_authorize_url_exige_credenciais(monkeypatch):
    monkeypatch.delenv("BLING_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLING_CLIENT_SECRET", raising=False)
    with pytest.raises(BlingNotConfigured):
        auth.authorize_url("abc")


def test_basic_header_e_base64_de_id_dois_pontos_secret(creds):
    header = auth._basic_auth_header()
    esperado = base64.b64encode(b"cid:csec").decode()
    assert header == f"Basic {esperado}"


def test_troca_de_code_manda_enable_jwt_e_persiste(creds, monkeypatch):
    """enable-jwt: 1 e OBRIGATORIO — o token opaco esta descontinuado no Bling."""
    capturado = {}
    store = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "access_token": "jwt-aaa", "refresh_token": "ref-bbb",
                "expires_in": 21600, "token_type": "Bearer", "scope": "1 2 3",
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, data=None):
            capturado["url"] = url
            capturado["headers"] = headers
            capturado["data"] = data
            return FakeResponse()

    async def noop_cache(*_a, **_k):
        return None

    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr(auth, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(auth, "_cache_set", noop_cache)

    out = asyncio.run(auth.exchange_code("code-xyz"))

    assert capturado["headers"]["enable-jwt"] == "1"
    assert capturado["headers"]["Authorization"].startswith("Basic ")
    assert capturado["data"]["grant_type"] == "authorization_code"
    assert capturado["data"]["code"] == "code-xyz"
    assert out["access_token"] == "jwt-aaa"
    assert store["upserted"]["refresh_token"] == "ref-bbb"
    assert store["upserted"]["access_expires_at"] > datetime.now(timezone.utc).isoformat()


def test_refresh_usa_grant_type_refresh_token(creds, monkeypatch):
    capturado = {}
    store = {"row": {"refresh_token": "ref-antigo"}}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "jwt-novo", "refresh_token": "ref-novo",
                    "expires_in": 21600, "scope": ""}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, data=None):
            capturado["data"] = data
            capturado["headers"] = headers
            return FakeResponse()

    async def noop_cache(*_a, **_k):
        return None

    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr(auth, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(auth, "_cache_set", noop_cache)

    asyncio.run(auth._refresh_now("ref-antigo"))

    assert capturado["data"]["grant_type"] == "refresh_token"
    assert capturado["data"]["refresh_token"] == "ref-antigo"
    assert capturado["headers"]["enable-jwt"] == "1"


def test_refresh_e_serializado_por_lock(creds, monkeypatch):
    """20 chamadas a /oauth/token em 60s bloqueiam o IP por 60 MINUTOS.
    Duas corrotinas renovando ao mesmo tempo nao podem virar duas chamadas."""
    chamadas = []
    estado = {"token": None}
    # Lock real compartilhado: simula a exclusao mutua do lock Redis de producao,
    # onde quem chega depois FICA ESPERANDO (poll) ate quem esta dentro liberar.
    # Um `_Ctx()` novo por chamada (sem estado compartilhado) devolveria True para
    # as duas corrotinas ao mesmo tempo e faria o teste passar mesmo com o refresh
    # duplicado — o mesmo erro de fake-sem-instancia-unica ja visto nesta feature.
    lock_real = asyncio.Lock()

    async def fake_refresh_now(token):
        chamadas.append(token)
        await fake_cache_set("jwt-novo", 60)
        return "jwt-novo"

    async def fake_lock():
        class _Ctx:
            async def __aenter__(self):
                await lock_real.acquire()
                return True

            async def __aexit__(self, *a):
                lock_real.release()
                return False
        return _Ctx()

    async def fake_cache_get():
        return estado["token"]

    async def fake_cache_set(token, ttl):
        estado["token"] = token

    monkeypatch.setattr(auth, "_refresh_now", fake_refresh_now)
    monkeypatch.setattr(auth, "_stored_refresh_token", lambda: "ref-x")
    monkeypatch.setattr(auth, "_refresh_lock", fake_lock)
    monkeypatch.setattr(auth, "_cache_get", fake_cache_get)
    monkeypatch.setattr(auth, "_cache_set", fake_cache_set)

    async def run():
        return await asyncio.gather(auth.get_access_token(), auth.get_access_token())

    asyncio.run(run())
    assert len(chamadas) == 1, "o refresh tinha que acontecer uma unica vez"


def test_tokens_nunca_aparecem_no_log(creds, caplog, monkeypatch):
    store = {}

    async def noop_cache(*_a, **_k):
        return None

    monkeypatch.setattr(auth, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(auth, "_cache_set", noop_cache)
    with caplog.at_level("DEBUG"):
        asyncio.run(auth._persist({
            "access_token": "SEGREDO-AAA", "refresh_token": "SEGREDO-BBB",
            "expires_in": 21600, "scope": "",
        }))
    assert "SEGREDO-AAA" not in caplog.text
    assert "SEGREDO-BBB" not in caplog.text
