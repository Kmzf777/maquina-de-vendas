"""Camada de Memória de Longo Prazo (Dossiê do Lead) — resumo rolante.

Ver docs/superpowers/specs/2026-06-26-lead-memory-layer-design.md
"""
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── render_dossier (saída determinística, sem preâmbulo — D6) ────────────────
def test_render_dossier_produces_fixed_markdown_template():
    from app.agent.memory_manager import render_dossier

    out = render_dossier({
        "perfil_empresa": "Cafeteria em BH",
        "interesse_preferencias": "Grãos especiais 1kg",
        "objecoes": "Achou o frete caro",
        "estagio_negocio": "Negociando volume",
        "proximo_passo": "Enviar proposta com desconto por volume",
    })

    assert out.startswith("## DOSSIÊ DO LEAD")
    assert "* **Perfil / Empresa:** Cafeteria em BH" in out
    assert "* **Interesse e preferências de produto:** Grãos especiais 1kg" in out
    assert "* **Objeções levantadas:** Achou o frete caro" in out
    assert "* **Estágio do negócio:** Negociando volume" in out
    assert "* **Próximo passo sugerido:** Enviar proposta com desconto por volume" in out


def test_render_dossier_fills_missing_fields_with_placeholder():
    from app.agent.memory_manager import render_dossier

    out = render_dossier({"perfil_empresa": "Padaria"})

    assert "* **Perfil / Empresa:** Padaria" in out
    # Campos ausentes não somem — viram "Não informado".
    assert "* **Interesse e preferências de produto:** Não informado" in out
    assert "* **Próximo passo sugerido:** Não informado" in out


# ── build_memory_messages (delta-only — D4) ─────────────────────────────────
def test_build_memory_messages_includes_prior_summary_and_only_delta():
    from app.agent.memory_manager import build_memory_messages

    prior = "## DOSSIÊ DO LEAD\n* **Perfil / Empresa:** Cafeteria em BH"
    delta = [
        {"role": "user", "content": "achei o frete caro"},
        {"role": "assistant", "content": "consigo melhorar pra volume maior"},
    ]
    messages = build_memory_messages(prior, delta)

    assert messages[0]["role"] == "system"
    user_msg = next(m for m in messages if m["role"] == "user")
    # o dossiê anterior tem que ir no contexto
    assert "Cafeteria em BH" in user_msg["content"]
    # o delta tem que ir no contexto
    assert "achei o frete caro" in user_msg["content"]
    assert "consigo melhorar pra volume maior" in user_msg["content"]


# ── generate_rolling_summary (structured output + fail-soft) ─────────────────
@pytest.mark.asyncio
async def test_generate_rolling_summary_renders_json_into_dossier():
    from app.agent.memory_manager import generate_rolling_summary

    payload = {
        "perfil_empresa": "Cafeteria em BH",
        "interesse_preferencias": "Grãos 1kg",
        "objecoes": "Frete",
        "estagio_negocio": "Negociando",
        "proximo_passo": "Proposta",
    }
    choice = MagicMock()
    choice.message.content = json.dumps(payload)
    resp = MagicMock()
    resp.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)

    out = await generate_rolling_summary(
        "prior", [{"role": "user", "content": "oi"}], client, "gemini-2.5-flash"
    )

    assert out.startswith("## DOSSIÊ DO LEAD")
    assert "Cafeteria em BH" in out
    # structured output: pediu JSON ao modelo
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_generate_rolling_summary_empty_delta_skips_llm_and_keeps_prior():
    from app.agent.memory_manager import generate_rolling_summary

    client = MagicMock()
    client.chat.completions.create = AsyncMock()

    out = await generate_rolling_summary("PRIOR", [], client, "gemini-2.5-flash")

    assert out == "PRIOR"
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_generate_rolling_summary_invalid_json_failsoft_to_prior():
    from app.agent.memory_manager import generate_rolling_summary

    choice = MagicMock()
    choice.message.content = "Aqui está o dossiê: blá blá (não é JSON)"
    resp = MagicMock()
    resp.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)

    out = await generate_rolling_summary(
        "PRIOR", [{"role": "user", "content": "oi"}], client, "gemini-2.5-flash"
    )

    assert out == "PRIOR"


@pytest.mark.asyncio
async def test_generate_rolling_summary_llm_exception_failsoft_to_prior():
    from app.agent.memory_manager import generate_rolling_summary

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("timeout"))

    out = await generate_rolling_summary(
        "PRIOR", [{"role": "user", "content": "oi"}], client, "gemini-2.5-flash"
    )

    assert out == "PRIOR"


# ── refresh_lead_memory: lock + delta no-op (D5) ─────────────────────────────
class _LockResp:
    def __init__(self, data):
        self.data = data


class _LockQuery:
    def __init__(self, store):
        self.store = store
        self.payload = None
        self.has_or = False

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def or_(self, *a, **k):
        self.has_or = True
        return self

    def execute(self):
        kind = "claim" if self.has_or else "release"
        self.store["calls"].append(kind)
        if kind == "claim":
            return _LockResp([{"id": "x"}] if self.store["claimable"] else [])
        return _LockResp([])


class _FakeLockSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _LockQuery(self.store)


@pytest.mark.asyncio
async def test_refresh_lead_memory_claims_and_releases_lock_on_success():
    from app.agent import memory_manager as mm

    store = {"claimable": True, "calls": []}
    with patch.object(mm, "get_supabase", return_value=_FakeLockSupabase(store)), \
         patch.object(mm, "get_lead", return_value={"id": "l1", "rolling_summary": "P", "rolling_summary_updated_at": "2026-06-26T10:00:00+00:00"}), \
         patch.object(mm, "get_history", return_value=[{"role": "user", "content": "nova msg"}]), \
         patch.object(mm, "generate_rolling_summary", new=AsyncMock(return_value="NOVO DOSSIÊ")), \
         patch.object(mm, "update_lead") as upd:
        ok = await mm.refresh_lead_memory("l1", client=MagicMock(), model="gemini-2.5-flash")

    assert ok is True
    assert store["calls"] == ["claim", "release"]  # claim primeiro, release no finally
    upd.assert_called_once()
    _, kwargs = upd.call_args
    assert kwargs["rolling_summary"] == "NOVO DOSSIÊ"
    assert "rolling_summary_updated_at" in kwargs


@pytest.mark.asyncio
async def test_refresh_lead_memory_lock_held_skips_llm_and_does_not_release():
    from app.agent import memory_manager as mm

    store = {"claimable": False, "calls": []}
    gen = AsyncMock()
    with patch.object(mm, "get_supabase", return_value=_FakeLockSupabase(store)), \
         patch.object(mm, "get_history") as hist, \
         patch.object(mm, "generate_rolling_summary", new=gen):
        ok = await mm.refresh_lead_memory("l1", client=MagicMock(), model="gemini-2.5-flash")

    assert ok is False
    assert store["calls"] == ["claim"]  # não conseguiu o lock → não libera o que não pegou
    gen.assert_not_called()
    hist.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_lead_memory_releases_lock_even_on_exception():
    from app.agent import memory_manager as mm

    store = {"claimable": True, "calls": []}
    with patch.object(mm, "get_supabase", return_value=_FakeLockSupabase(store)), \
         patch.object(mm, "get_lead", side_effect=RuntimeError("db down")):
        ok = await mm.refresh_lead_memory("l1", client=MagicMock(), model="gemini-2.5-flash")

    assert ok is False
    assert store["calls"] == ["claim", "release"]  # release no finally apesar da exceção


@pytest.mark.asyncio
async def test_refresh_lead_memory_noop_when_no_delta():
    from app.agent import memory_manager as mm

    store = {"claimable": True, "calls": []}
    gen = AsyncMock()
    with patch.object(mm, "get_supabase", return_value=_FakeLockSupabase(store)), \
         patch.object(mm, "get_lead", return_value={"id": "l1", "rolling_summary": "P", "rolling_summary_updated_at": "2026-06-26T10:00:00+00:00"}), \
         patch.object(mm, "get_history", return_value=[]), \
         patch.object(mm, "generate_rolling_summary", new=gen), \
         patch.object(mm, "update_lead") as upd:
        ok = await mm.refresh_lead_memory("l1", client=MagicMock(), model="gemini-2.5-flash")

    assert ok is False
    gen.assert_not_called()
    upd.assert_not_called()
    assert store["calls"] == ["claim", "release"]


@pytest.mark.asyncio
async def test_refresh_lead_memory_passes_updated_at_as_since():
    """O delta tem que ser buscado com since=rolling_summary_updated_at (D4)."""
    from app.agent import memory_manager as mm

    store = {"claimable": True, "calls": []}
    with patch.object(mm, "get_supabase", return_value=_FakeLockSupabase(store)), \
         patch.object(mm, "get_lead", return_value={"id": "l1", "rolling_summary": "P", "rolling_summary_updated_at": "2026-06-26T10:00:00+00:00"}), \
         patch.object(mm, "get_history", return_value=[{"role": "user", "content": "x"}]) as hist, \
         patch.object(mm, "generate_rolling_summary", new=AsyncMock(return_value="N")), \
         patch.object(mm, "update_lead"):
        await mm.refresh_lead_memory("l1", client=MagicMock(), model="gemini-2.5-flash")

    _, kwargs = hist.call_args
    assert kwargs.get("since") == "2026-06-26T10:00:00+00:00"


# ── process_stale_lead_memories: seleção com janela de recência ──────────────
class _SelResp:
    def __init__(self, data):
        self.data = data


class _SelQuery:
    def __init__(self, store):
        self.store = store

    def select(self, *a, **k):
        return self

    def gte(self, key, value):
        self.store["filters"].append(("gte", key, value))
        return self

    def lt(self, key, value):
        self.store["filters"].append(("lt", key, value))
        return self

    def or_(self, expr):
        self.store["filters"].append(("or", expr))
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self.store["limit"] = n
        return self

    def execute(self):
        return _SelResp(self.store["rows"])


class _FakeSelSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _SelQuery(self.store)


@pytest.mark.asyncio
async def test_process_stale_lead_memories_refreshes_each_candidate():
    from app.agent import memory_manager as mm

    store = {"rows": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "filters": [], "limit": None}
    refreshed = []

    async def fake_refresh(lead_id, **k):
        refreshed.append(lead_id)
        return lead_id != "b"  # b retorna False (sem delta)

    with patch.object(mm, "get_supabase", return_value=_FakeSelSupabase(store)), \
         patch.object(mm, "refresh_lead_memory", new=fake_refresh):
        count = await mm.process_stale_lead_memories()

    assert refreshed == ["a", "b", "c"]
    assert count == 2  # a e c
    # janela de recência aplicada (gte + lt em last_customer_message_at) e LIMIT defensivo
    assert any(f[0] == "gte" and f[1] == "last_customer_message_at" for f in store["filters"])
    assert any(f[0] == "lt" and f[1] == "last_customer_message_at" for f in store["filters"])
    assert store["limit"] == mm.BATCH_LIMIT
