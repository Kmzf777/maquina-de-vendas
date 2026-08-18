import asyncio
import base64
from datetime import datetime, timedelta, timezone

import pytest

import app.bling.auth as auth
from app.bling.errors import BlingNotConfigured, TRANSIENT


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
    assert capturado["url"] == auth.config.TOKEN_URL


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
    # _stored_row (nao mais _stored_refresh_token): get_access_token agora rele o
    # Postgres inteiro para poder achar um access_token ja valido; sem
    # "access_token" na linha, ele cai direto no caminho de refresh de qualquer
    # forma, entao esse teste continua exercitando so a serializacao do lock.
    monkeypatch.setattr(auth, "_stored_row", lambda: {"refresh_token": "ref-x"})
    monkeypatch.setattr(auth, "_refresh_lock", fake_lock)
    monkeypatch.setattr(auth, "_cache_get", fake_cache_get)
    monkeypatch.setattr(auth, "_cache_set", fake_cache_set)

    async def run():
        return await asyncio.gather(auth.get_access_token(), auth.get_access_token())

    asyncio.run(run())
    assert len(chamadas) == 1, "o refresh tinha que acontecer uma unica vez"


def test_get_access_token_rele_o_access_token_do_postgres_antes_de_renovar(creds, monkeypatch):
    """Um FLUSHALL no Redis (incidente 07/06/2026) zera o cache, mas NAO o
    Postgres. Com um access_token ainda valido por horas persistido, get_access_
    token() tem que devolver ELE, sem bater no /oauth/token — senao toda chamada
    sequencial vira uma chamada real ao Bling (e 20 em 60s bloqueiam o IP por
    60 minutos, o mesmo risco que o lock existe para evitar em concorrencia)."""
    chamadas_token_endpoint = []
    cache = {"token": None}

    async def fake_refresh_now(token):  # nao deveria ser chamado neste teste
        chamadas_token_endpoint.append(token)
        return "nao-deveria-acontecer"

    async def fake_lock():
        class _Ctx:
            async def __aenter__(self):
                return True

            async def __aexit__(self, *a):
                return False
        return _Ctx()

    async def fake_cache_get():
        return cache["token"]

    async def fake_cache_set(token, ttl):
        cache["token"] = token

    expira_em_3h = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()

    monkeypatch.setattr(auth, "_refresh_now", fake_refresh_now)
    monkeypatch.setattr(auth, "_refresh_lock", fake_lock)
    monkeypatch.setattr(auth, "_cache_get", fake_cache_get)
    monkeypatch.setattr(auth, "_cache_set", fake_cache_set)
    monkeypatch.setattr(auth, "_stored_row", lambda: {
        "access_token": "jwt-do-postgres",
        "access_expires_at": expira_em_3h,
        "refresh_token": "ref-x",
    })

    out = asyncio.run(auth.get_access_token())

    assert out == "jwt-do-postgres"
    assert chamadas_token_endpoint == [], "nao pode chamar /oauth/token com token do Postgres ainda valido"
    assert cache["token"] == "jwt-do-postgres", "tinha que recachear o token relido"


def test_lock_indisponivel_e_erro_transiente_nao_auth(creds, monkeypatch):
    """Timeout de lock e contencao momentanea (outro processo renovando agora),
    NAO credencial morta. Se isso virasse um erro fora de TRANSIENT, o modal de
    venda mandaria o vendedor refazer o OAuth em /config em vez de so enfileirar
    e tentar de novo."""
    async def fake_lock():
        class _Ctx:
            async def __aenter__(self):
                return False  # nao conseguiu o lock

            async def __aexit__(self, *a):
                return False
        return _Ctx()

    async def fake_cache_get():
        return None

    monkeypatch.setattr(auth, "_refresh_lock", fake_lock)
    monkeypatch.setattr(auth, "_cache_get", fake_cache_get)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(auth.get_access_token())

    assert isinstance(exc_info.value, TRANSIENT), (
        f"{type(exc_info.value).__name__} nao esta em TRANSIENT — "
        "contencao de lock nao pode virar 'refaca o OAuth'"
    )


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


def test_persist_falha_no_postgres_loga_critical_sem_token_e_relevanta(creds, caplog, monkeypatch):
    """Se o Bling ja rotacionou o refresh_token do lado dele e o upsert falha, o
    token novo se perde e o antigo ja foi invalidado la — a integracao para ate
    alguem refazer o OAuth na mao. Isso tem que gritar (CRITICAL) com uma
    mensagem inequivoca, sem citar nenhum token, e continuar propagando o erro
    (nao pode morrer em silencio nem engolir a excecao)."""
    tentativas = {"n": 0}

    class FakeTableQuebrado:
        def upsert(self, *_a, **_k):
            return self

        def execute(self):
            tentativas["n"] += 1
            raise RuntimeError("conexao com o Postgres recusada")

    class FakeSupabaseQuebrado:
        def table(self, _name):
            return FakeTableQuebrado()

    monkeypatch.setattr(auth, "get_supabase", lambda: FakeSupabaseQuebrado())

    with caplog.at_level("DEBUG"):
        with pytest.raises(RuntimeError):
            asyncio.run(auth._persist({
                "access_token": "SEGREDO-CCC", "refresh_token": "SEGREDO-DDD",
                "expires_in": 21600, "scope": "",
            }))

    assert tentativas["n"] >= 2, "tinha que ter tentado de novo antes de desistir"
    criticals = [r for r in caplog.records if r.levelname == "CRITICAL"]
    assert len(criticals) == 1
    assert "SEGREDO-CCC" not in caplog.text
    assert "SEGREDO-DDD" not in caplog.text


class FakeRedis:
    """Redis fake em memoria para os testes de state (setex/delete).

    Instancia UNICA injetada fora do lambda (`fake = FakeRedis(); monkeypatch.setattr(
    auth, "_get_redis", lambda: fake)`). Um `lambda: FakeRedis()` construiria um Redis
    novo a cada chamada — o `delete` de `consume_state` nunca acharia a chave gravada
    pelo `setex` de `new_state`, e o teste de "queima" passaria pelo motivo errado
    (mesmo erro de fake-sem-instancia-unica ja visto nesta feature).
    """

    def __init__(self):
        self.store = {}  # key -> (value, ttl)
        self.delete_calls = 0

    async def setex(self, key, ttl, value):
        self.store[key] = (value, ttl)

    async def delete(self, key):
        self.delete_calls += 1
        if key in self.store:
            del self.store[key]
            return 1
        return 0

    async def get(self, key):
        item = self.store.get(key)
        return item[0] if item else None


def test_new_state_gera_valores_unicos_e_grava_no_redis_com_ttl(monkeypatch):
    """O state anti-CSRF precisa expirar. `setex`, nunca `set` sem TTL — um state
    que nunca expira derruba a janela de 10 min que existe para limitar a superficie
    de ataque (alguem induzindo o admin a autorizar um app Bling que nao e o nosso)."""
    fake = FakeRedis()
    monkeypatch.setattr(auth, "_get_redis", lambda: fake)

    s1 = asyncio.run(auth.new_state())
    s2 = asyncio.run(auth.new_state())

    assert s1 and s2
    assert s1 != s2
    assert (auth._STATE_PREFIX + s1) in fake.store
    _, ttl1 = fake.store[auth._STATE_PREFIX + s1]
    assert ttl1 == auth._STATE_TTL
    assert ttl1 > 0


def test_consume_state_true_para_state_existente(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(auth, "_get_redis", lambda: fake)
    state = asyncio.run(auth.new_state())

    assert asyncio.run(auth.consume_state(state)) is True


def test_consume_state_false_para_state_inexistente(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(auth, "_get_redis", lambda: fake)

    assert asyncio.run(auth.consume_state("nunca-existiu")) is False


def test_consume_state_queima_o_valor_impedindo_replay(monkeypatch):
    """Ponto central da defesa anti-CSRF: um state reutilizavel nao protege contra
    replay. Mesma chamada duas vezes com o MESMO state: True na primeira, False na
    segunda — senao um state capturado uma vez poderia ser reaproveitado."""
    fake = FakeRedis()
    monkeypatch.setattr(auth, "_get_redis", lambda: fake)
    state = asyncio.run(auth.new_state())

    primeira = asyncio.run(auth.consume_state(state))
    segunda = asyncio.run(auth.consume_state(state))

    assert primeira is True
    assert segunda is False


def test_consume_state_vazio_retorna_false_sem_tocar_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(auth, "_get_redis", lambda: fake)

    assert asyncio.run(auth.consume_state("")) is False
    assert fake.delete_calls == 0
