"""Camada de Memória de Longo Prazo (Dossiê do Lead) — resumo rolante.

Ver docs/superpowers/specs/2026-06-26-lead-memory-layer-design.md
"""
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.gemini_fakes import fake_text


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
    from app.agent.memory_manager import _SYSTEM_PROMPT, build_memory_messages

    prior = "## DOSSIÊ DO LEAD\n* **Perfil / Empresa:** Cafeteria em BH"
    delta = [
        {"role": "user", "content": "achei o frete caro"},
        {"role": "assistant", "content": "consigo melhorar pra volume maior"},
    ]
    system_instruction, user_msg = build_memory_messages(prior, delta)

    # o prompt do memorialista vai como system_instruction nativo
    assert system_instruction == _SYSTEM_PROMPT
    # o dossiê anterior tem que ir no contexto
    assert "Cafeteria em BH" in user_msg
    # o delta tem que ir no contexto
    assert "achei o frete caro" in user_msg
    assert "consigo melhorar pra volume maior" in user_msg


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
    with patch(
        "app.agent.memory_manager.generate",
        new=AsyncMock(side_effect=[fake_text(json.dumps(payload))]),
    ) as m_gen:
        out = await generate_rolling_summary(
            "prior", [{"role": "user", "content": "oi"}], "gemini-2.5-flash"
        )

    assert out.startswith("## DOSSIÊ DO LEAD")
    assert "Cafeteria em BH" in out
    # structured output: pediu JSON DE VERDADE ao modelo (json_mode nativo →
    # response_mime_type="application/json"; a fachada engolia response_format — burn 08/07)
    kwargs = m_gen.await_args.kwargs
    assert kwargs["json_mode"] is True
    # merge mecânico: thinking desligado no knob nativo
    assert kwargs["thinking_off"] is True


@pytest.mark.asyncio
async def test_generate_rolling_summary_empty_delta_skips_llm_and_keeps_prior():
    from app.agent.memory_manager import generate_rolling_summary

    with patch("app.agent.memory_manager.generate", new=AsyncMock()) as m_gen:
        out = await generate_rolling_summary("PRIOR", [], "gemini-2.5-flash")

    assert out == "PRIOR"
    m_gen.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_rolling_summary_invalid_json_failsoft_to_prior():
    from app.agent.memory_manager import generate_rolling_summary

    with patch(
        "app.agent.memory_manager.generate",
        new=AsyncMock(side_effect=[fake_text("Aqui está o dossiê: blá blá (não é JSON)")]),
    ):
        out = await generate_rolling_summary(
            "PRIOR", [{"role": "user", "content": "oi"}], "gemini-2.5-flash"
        )

    assert out == "PRIOR"


@pytest.mark.asyncio
async def test_generate_rolling_summary_llm_exception_failsoft_to_prior():
    from app.agent.memory_manager import generate_rolling_summary

    with patch(
        "app.agent.memory_manager.generate",
        new=AsyncMock(side_effect=RuntimeError("timeout")),
    ):
        out = await generate_rolling_summary(
            "PRIOR", [{"role": "user", "content": "oi"}], "gemini-2.5-flash"
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
        ok = await mm.refresh_lead_memory("l1", model="gemini-2.5-flash")

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
        ok = await mm.refresh_lead_memory("l1", model="gemini-2.5-flash")

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
        ok = await mm.refresh_lead_memory("l1", model="gemini-2.5-flash")

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
        ok = await mm.refresh_lead_memory("l1", model="gemini-2.5-flash")

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
        await mm.refresh_lead_memory("l1", model="gemini-2.5-flash")

    _, kwargs = hist.call_args
    assert kwargs.get("since") == "2026-06-26T10:00:00+00:00"


@pytest.mark.asyncio
async def test_refresh_lead_memory_advances_watermark_even_when_summary_unchanged():
    """Dossiê estável (== prior) TEM que avançar rolling_summary_updated_at até a última
    mensagem consumida — senão o MESMO delta reprocessa a cada tick (loop que queimou
    1117 chamadas p/ 15 leads em 08/07). Não reescreve o texto do dossiê, só a marca d'água."""
    from app.agent import memory_manager as mm

    store = {"claimable": True, "calls": []}
    delta = [
        {"role": "user", "content": "oi", "created_at": "2026-07-08T18:00:00+00:00"},
        {"role": "assistant", "content": "olá", "created_at": "2026-07-08T18:01:30+00:00"},
    ]
    with patch.object(mm, "get_supabase", return_value=_FakeLockSupabase(store)), \
         patch.object(mm, "get_lead", return_value={"id": "l1", "rolling_summary": "MESMO", "rolling_summary_updated_at": "2026-07-08T17:00:00+00:00"}), \
         patch.object(mm, "get_history", return_value=delta), \
         patch.object(mm, "generate_rolling_summary", new=AsyncMock(return_value="MESMO")), \
         patch.object(mm, "update_lead") as upd:
        ok = await mm.refresh_lead_memory("l1", model="gemini-2.5-flash")

    assert ok is False  # não gravou dossiê novo
    upd.assert_called_once()  # mas AVANÇOU a marca d'água
    _, kwargs = upd.call_args
    assert kwargs.get("rolling_summary_updated_at") == "2026-07-08T18:01:30+00:00"  # última msg do delta
    assert "rolling_summary" not in kwargs  # texto do dossiê não é reescrito à toa
    assert store["calls"] == ["claim", "release"]


@pytest.mark.asyncio
async def test_refresh_lead_memory_watermark_uses_last_delta_created_at_on_write():
    """Quando o dossiê muda, a marca d'água é o created_at da ÚLTIMA msg do delta (não now()),
    p/ não pular mensagens que chegaram durante o processamento."""
    from app.agent import memory_manager as mm

    store = {"claimable": True, "calls": []}
    delta = [
        {"role": "user", "content": "novidade", "created_at": "2026-07-08T18:05:00+00:00"},
    ]
    with patch.object(mm, "get_supabase", return_value=_FakeLockSupabase(store)), \
         patch.object(mm, "get_lead", return_value={"id": "l1", "rolling_summary": "P", "rolling_summary_updated_at": "2026-07-08T17:00:00+00:00"}), \
         patch.object(mm, "get_history", return_value=delta), \
         patch.object(mm, "generate_rolling_summary", new=AsyncMock(return_value="NOVO")), \
         patch.object(mm, "update_lead") as upd:
        ok = await mm.refresh_lead_memory("l1", model="gemini-2.5-flash")

    assert ok is True
    _, kwargs = upd.call_args
    assert kwargs["rolling_summary"] == "NOVO"
    assert kwargs["rolling_summary_updated_at"] == "2026-07-08T18:05:00+00:00"


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


@pytest.mark.asyncio
async def test_process_stale_skips_leads_already_summarized_past_last_message():
    """Não reprocessa (nem pega lock de) leads cujo dossiê já cobre a última msg do cliente —
    evita o lock churn/egress de reselecionar os mesmos leads a cada tick só p/ achar delta vazio."""
    from app.agent import memory_manager as mm

    rows = [
        # dossiê ATRASADO (updated_at < last_msg) → processa
        {"id": "novo", "last_customer_message_at": "2026-07-08T18:00:00+00:00",
         "rolling_summary_updated_at": "2026-07-08T17:00:00+00:00"},
        # dossiê EM DIA (updated_at >= last_msg E texto gravado) → pula
        {"id": "em_dia", "last_customer_message_at": "2026-07-08T18:00:00+00:00",
         "rolling_summary_updated_at": "2026-07-08T18:00:00+00:00",
         "rolling_summary": "## DOSSIÊ DO LEAD\n- em dia"},
        # nunca resumido (updated_at null) → processa
        {"id": "virgem", "last_customer_message_at": "2026-07-08T18:00:00+00:00",
         "rolling_summary_updated_at": None},
    ]
    store = {"rows": rows, "filters": [], "limit": None}
    refreshed = []

    async def fake_refresh(lead_id, **k):
        refreshed.append(lead_id)
        return True

    with patch.object(mm, "get_supabase", return_value=_FakeSelSupabase(store)), \
         patch.object(mm, "refresh_lead_memory", new=fake_refresh):
        count = await mm.process_stale_lead_memories()

    assert refreshed == ["novo", "virgem"]  # "em_dia" nunca chega a refresh_lead_memory
    assert count == 2
