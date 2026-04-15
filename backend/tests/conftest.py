import os
import pytest

# Set required env vars before any app imports trigger Settings validation
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeRedis:
    """Minimal in-memory async Redis stub for tests."""

    def __init__(self):
        self._lists: dict = {}
        self._sorted: dict = {}
        self._strings: dict = {}

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

    async def set(self, key, value, ex=None, px=None):
        self._strings[key] = value

    async def get(self, key):
        return self._strings.get(key)

    async def delete(self, *keys):
        for k in keys:
            self._lists.pop(k, None)
            self._sorted.pop(k, None)
            self._strings.pop(k, None)

    async def exists(self, *keys):
        return sum(1 for k in keys if k in self._strings or k in self._lists or k in self._sorted)

    async def expire(self, key, seconds):
        pass  # No-op in tests; TTL not tracked

    async def ttl(self, key):
        return -1  # No TTL tracking in stub


@pytest.fixture
def fake_redis():
    return FakeRedis()
