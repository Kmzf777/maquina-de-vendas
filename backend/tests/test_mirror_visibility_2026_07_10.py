"""Toggle de visibilidade do espelho do motor no CRM (decisão executiva 10/07).

Contratos:
1. DEFAULT OCULTO — sem opt-in explícito no Redis, o espelho não aparece na interface
   (a análise interna decide quando religar, pela própria UI, sem deploy).
2. O toggle é SÓ apresentação: nunca escreve em campaigns nem relaxa as guardas 409 —
   impossível causar execução dupla por este caminho.
"""

from types import SimpleNamespace

import pytest

from app.follow_up.api import get_mirror_visibility, set_mirror_visibility


class _FakeRedis:
    def __init__(self, initial=None):
        self.store = dict(initial or {})

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value


class _FakeRequest:
    def __init__(self, redis, body=None):
        self.app = SimpleNamespace(state=SimpleNamespace(redis=redis))
        self._body = body or {}

    async def json(self):
        return self._body


@pytest.mark.asyncio
async def test_default_is_hidden_without_explicit_opt_in():
    r = _FakeRedis()  # chave ausente
    assert await get_mirror_visibility(_FakeRequest(r)) == {"visible": False}
    r.store["config:cadence_mirror_visible"] = "0"
    assert await get_mirror_visibility(_FakeRequest(r)) == {"visible": False}


@pytest.mark.asyncio
async def test_visible_only_with_explicit_one():
    r = _FakeRedis({"config:cadence_mirror_visible": "1"})
    assert await get_mirror_visibility(_FakeRequest(r)) == {"visible": True}


@pytest.mark.asyncio
async def test_toggle_roundtrip():
    r = _FakeRedis()
    assert await set_mirror_visibility(_FakeRequest(r, {"visible": True})) == {"visible": True}
    assert r.store["config:cadence_mirror_visible"] == "1"
    assert await set_mirror_visibility(_FakeRequest(r, {"visible": False})) == {"visible": False}
    assert r.store["config:cadence_mirror_visible"] == "0"
    # body vazio = esconder (default conservador)
    assert await set_mirror_visibility(_FakeRequest(r, {})) == {"visible": False}


def test_toggle_module_never_touches_campaigns():
    """Guarda de fonte: o módulo do toggle não escreve em campaigns — a visibilidade
    é apresentação pura; ativação continua bloqueada pelas guardas 409 do router."""
    import inspect
    import app.follow_up.api as api_module

    src = inspect.getsource(api_module)
    assert 'table("campaigns")' not in src
    assert "update_campaign" not in src
