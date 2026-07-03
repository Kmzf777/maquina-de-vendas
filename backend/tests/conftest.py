import os
import pytest

# Set required env vars before any app imports trigger Settings validation
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret-32-chars-minimum!")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

# Hermeticidade: neutraliza toggles locais de .env.local (app/config.py carrega
# .env.local em os.environ no import, com `if k not in os.environ`). Definindo um
# baseline limpo AQUI — antes de qualquer import de app — impede que o
# REHEARSAL_MODE/AI_PHONE_NUMBER_ID do desenvolvedor contamine a suíte. Testes que
# precisam desses valores os definem explicitamente via monkeypatch/mock.
os.environ.setdefault("REHEARSAL_MODE", "false")
os.environ.setdefault("AI_PHONE_NUMBER_ID", "")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _stub_catalog(monkeypatch):
    """Neutraliza a leitura do catálogo (Supabase) por padrão em todos os testes.

    run_agent passou a injetar o catálogo dinâmico via get_products_by_funnel, que
    bate no Supabase. Sem este stub, cada teste de orchestrator faria uma chamada de
    rede real (URL fake → lentidão/flakiness). Retorna "" por padrão; o teste
    dedicado de catálogo (test_catalog.py) mocka o cliente Supabase diretamente e
    não importa este símbolo do orchestrator, então não é afetado.
    """
    monkeypatch.setattr(
        "app.agent.orchestrator.get_products_by_funnel",
        lambda *_a, **_k: "",
        raising=False,
    )


class FakeRedis:
    """Minimal in-memory async Redis stub for tests."""

    def __init__(self):
        self._lists: dict = {}
        self._sorted: dict = {}
        self._strings: dict = {}
        self._sets: dict = {}
        self._hashes: dict = {}

    async def rpush(self, key, *values):
        self._lists.setdefault(key, []).extend(values)
        return len(self._lists[key])

    async def lrange(self, key, start, end):
        items = self._lists.get(key, [])
        if end == -1:
            return list(items[start:])
        return list(items[start:end + 1])

    async def zadd(self, key, mapping):
        self._sorted.setdefault(key, {}).update(mapping)

    async def zscore(self, key, member):
        return self._sorted.get(key, {}).get(member)

    async def zrangebyscore(self, key, min_score, max_score):
        items = self._sorted.get(key, {})
        return [m for m, s in items.items() if float(min_score if min_score != "-inf" else "-inf") <= s <= float(max_score if max_score != "+inf" else "inf")]

    async def set(self, key, value, ex=None, px=None, nx=False):
        if nx and key in self._strings:
            return None  # key already exists — SETNX returns None (not set)
        self._strings[key] = value
        return True

    async def get(self, key):
        return self._strings.get(key)

    async def delete(self, *keys):
        for k in keys:
            self._lists.pop(k, None)
            self._sorted.pop(k, None)
            self._strings.pop(k, None)
            self._sets.pop(k, None)
            self._hashes.pop(k, None)

    async def exists(self, *keys):
        return sum(1 for k in keys if k in self._strings or k in self._lists or k in self._sorted)

    async def sadd(self, key, *values):
        self._sets.setdefault(key, set()).update(values)
        return len(values)

    async def sismember(self, key, value):
        return value in self._sets.get(key, set())

    async def smembers(self, key):
        return set(self._sets.get(key, set()))

    async def srem(self, key, *values):
        s = self._sets.get(key, set())
        removed = sum(1 for v in values if v in s)
        s -= set(values)
        if s:
            self._sets[key] = s
        else:
            self._sets.pop(key, None)
        return removed

    async def expire(self, key, seconds):
        pass  # No-op in tests; TTL not tracked

    async def ttl(self, key):
        return -1  # No TTL tracking in stub

    async def hset(self, key, field, value):
        self._hashes.setdefault(key, {})[field] = value

    async def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)

    async def hdel(self, key, *fields):
        h = self._hashes.get(key, {})
        removed = sum(1 for f in fields if f in h)
        for f in fields:
            h.pop(f, None)
        return removed

    async def hexists(self, key, field):
        return field in self._hashes.get(key, {})

    async def hgetall(self, key):
        return dict(self._hashes.get(key, {}))

    async def hkeys(self, key):
        return list(self._hashes.get(key, {}).keys())


@pytest.fixture
def fake_redis():
    return FakeRedis()
