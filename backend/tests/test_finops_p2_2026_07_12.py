"""FinOps P2 (12/07/2026) — Trilha B: histórico enxuto + dedup de tool-call + summary lite.

Contexto (diagnostico_completo_custos_llm.md): system-rows compravam janela do limit=60 e
eram descartadas na montagem; histórico sem teto de tokens re-pagava a cauda inteira a cada
chamada; turnos com ≥5 chamadas LLM (23% dos turnos) concentravam 51% do custo de resposta,
tipicamente o modelo re-pedindo a MESMA tool; o briefing de handoff herdava o flash do agente
para uma extração mecânica.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.gemini_fakes import fake_text, fake_tool_call


# ---------------------------------------------------------------------------
# 1. get_history: filtro de roles na query + teto de caracteres
# ---------------------------------------------------------------------------

class _FakeQuery:
    """Captura a cadeia PostgREST de get_history e devolve linhas pré-armadas."""

    def __init__(self, rows):
        self._rows = rows
        self.in_calls: list[tuple] = []

    def select(self, *_): return self
    def eq(self, *_): return self
    def order(self, *_, **__): return self
    def limit(self, *_): return self

    def in_(self, column, values):
        self.in_calls.append((column, list(values)))
        return self

    def execute(self):
        return MagicMock(data=self._rows)


def _fake_sb(rows):
    sb = MagicMock()
    query = _FakeQuery(rows)
    sb.table.return_value = query
    return sb, query


def _row(content, role="user"):
    return {"role": role, "content": content, "message_type": "text", "stage": "s",
            "created_at": "t", "wamid": None, "quoted_wamid": None, "metadata": None,
            "sent_by": None}


def test_get_history_filtra_roles_na_query():
    from app.conversations import service
    sb, query = _fake_sb([])
    with patch.object(service, "get_supabase", return_value=sb):
        service.get_history("conv-1", limit=60, roles=("user", "assistant"))
    assert query.in_calls == [("role", ["user", "assistant"])]


def test_get_history_sem_roles_nao_filtra():
    """Contrato antigo intacto: chamadores legados não ganham filtro novo."""
    from app.conversations import service
    sb, query = _fake_sb([])
    with patch.object(service, "get_supabase", return_value=sb):
        service.get_history("conv-1", limit=30)
    assert query.in_calls == []


def test_get_history_char_budget_corta_as_mais_antigas():
    from app.conversations import service
    # Query devolve desc (mais recente primeiro); retorno é cronológico ascendente.
    rows_desc = [_row("nova " + "x" * 95), _row("meio " + "y" * 95), _row("velha " + "z" * 95)]
    sb, _ = _fake_sb(rows_desc)
    with patch.object(service, "get_supabase", return_value=sb):
        out = service.get_history("conv-1", limit=60, char_budget=220)
    contents = [r["content"] for r in out]
    assert len(out) == 2
    assert contents[0].startswith("meio") and contents[1].startswith("nova")


def test_get_history_char_budget_sempre_mantem_a_mais_recente():
    from app.conversations import service
    sb, _ = _fake_sb([_row("gigante " + "x" * 500)])
    with patch.object(service, "get_supabase", return_value=sb):
        out = service.get_history("conv-1", limit=60, char_budget=100)
    assert len(out) == 1  # a mais recente entra mesmo estourando o teto sozinha


def test_get_history_sem_budget_devolve_tudo():
    from app.conversations import service
    sb, _ = _fake_sb([_row(f"m{i}") for i in range(5)])
    with patch.object(service, "get_supabase", return_value=sb):
        out = service.get_history("conv-1", limit=60, char_budget=0)
    assert len(out) == 5


# ---------------------------------------------------------------------------
# 2. Dedup de tool-call por turno no loop ReAct
# ---------------------------------------------------------------------------

def _run_agent_patches(call_responses, execute_tool_mock):
    return [
        patch("app.agent.orchestrator.get_history", return_value=[
            {"role": "user", "content": "oi", "stage": "secretaria",
             "created_at": "2026-07-12T13:30:00Z", "wamid": "w", "quoted_wamid": None,
             "message_type": "text", "metadata": None}
        ]),
        patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-p2", "phone": "5565996414453", "ai_enabled": True}),
        patch("app.agent.orchestrator.update_lead", new=MagicMock()),
        patch("app.agent.orchestrator._schedule_memory_refresh", new=MagicMock()),
        patch("app.agent.orchestrator.execute_tool", new=execute_tool_mock),
        patch("app.agent.orchestrator.track_token_usage"),
        patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=call_responses)),
    ]


@pytest.mark.asyncio
async def test_tool_repetida_nao_reexecuta_e_forca_texto(monkeypatch):
    """2ª chamada idêntica no mesmo turno: execute_tool roda 1x; a iteração 100% duplicada
    derruba tools=None na continuação (mata o loop patológico sem esperar o loop-guard)."""
    from app.agent.orchestrator import run_agent
    monkeypatch.delenv("LLM_INITIAL_THINKING", raising=False)

    conversation = {"id": "conv-p2-dedup", "stage": "secretaria",
                    "leads": {"id": "lead-p2", "name": "Ana", "phone": "5565996414453",
                              "ai_enabled": True}}
    responses = [
        fake_tool_call("salvar_nome", {"name": "Ana"}),
        fake_tool_call("salvar_nome", {"name": "Ana"}),  # repetição exata
        fake_text("prazer, Ana"),
    ]
    exec_mock = AsyncMock(return_value="Nome salvo: Ana")
    patches = _run_agent_patches(responses, exec_mock)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
            patches[6] as m_gen:
        out = await run_agent(conversation, "oi")

    assert exec_mock.await_count == 1          # dedup: não re-executou
    assert m_gen.await_count == 3
    assert m_gen.await_args_list[2].kwargs["tools"] is None  # iteração duplicada → força texto
    assert out == "prazer, Ana"


@pytest.mark.asyncio
async def test_tool_mesma_com_args_diferentes_executa_ambas(monkeypatch):
    from app.agent.orchestrator import run_agent
    monkeypatch.delenv("LLM_INITIAL_THINKING", raising=False)

    conversation = {"id": "conv-p2-dedup2", "stage": "secretaria",
                    "leads": {"id": "lead-p2", "name": None, "phone": "5565996414453",
                              "ai_enabled": True}}
    responses = [
        fake_tool_call("adicionar_tag_lead", {"tags": ["B2B"]}),
        fake_tool_call("adicionar_tag_lead", {"tags": ["Revenda"]}),  # args distintos
        fake_text("anotado"),
    ]
    exec_mock = AsyncMock(return_value="ok")
    patches = _run_agent_patches(responses, exec_mock)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
            patches[6] as m_gen:
        await run_agent(conversation, "oi")

    assert exec_mock.await_count == 2          # args diferentes = execução legítima
    assert m_gen.await_args_list[2].kwargs["tools"] is not None


# ---------------------------------------------------------------------------
# 3. Briefing de handoff em flash-lite (SUMMARY_MODEL)
# ---------------------------------------------------------------------------

def test_summary_model_default_flash_lite():
    from app.config import Settings
    assert Settings().summary_model == "gemini-2.5-flash-lite"


def test_handoff_usa_summary_model_e_nao_o_modelo_do_agente():
    """Guard de fonte: o caller do briefing lê settings.summary_model (não DEFAULT_MODEL)."""
    import inspect
    import app.agent.tools as tools_mod
    src = inspect.getsource(tools_mod)
    assert "settings.summary_model" in src
    assert "DEFAULT_MODEL" not in src
