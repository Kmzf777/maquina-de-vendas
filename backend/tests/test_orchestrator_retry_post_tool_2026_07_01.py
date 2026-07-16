"""Testes TDD para o fechamento do ciclo ReAct no retry-on-empty (2026-07-01).

Contexto forense (lead Karl 5531982950127):
  20:03:52 UTC chamada inicial ao Gemini: completion_tokens=0 (thinking-burn).
  20:03:53 UTC retry (tools mantidas, Change A/B) recuperou uma tool NÃO-terminal
  (salvar_nome) e a EXECUTOU — mas o código NÃO fechava o ciclo ReAct: não havia
  chamada PÓS-TOOL de continuação. O turno terminava com retry vazio →
  _SAFETY_FALLBACK_GENERIC ("opa, me embolei aqui..."), engolindo a fala real.

Correção validada aqui:
  Após executar tool(s) NÃO-terminal(is) recuperada(s) no retry, o orchestrator faz
  UMA chamada PÓS-TOOL de continuação (espelha o loop principal), gerando o texto
  natural. Tools TERMINAIS (encaminhar_humano / registrar_optout /
  registrar_sem_interesse_atual) fazem curto-circuito ANTES da chamada pós-tool.
  Retry com texto puro (sem function_calls) NÃO dispara chamada pós-tool.

Cobertura:
  1. Karl: inicial vazia → retry recupera salvar_nome → PÓS-TOOL gera texto natural.
     (3 chamadas; execute_tool chamado; resultado da tool entra nos contents do pós-tool.)
  2. Pós-tool também vazio → cai no fallback genérico honesto (nunca silêncio "").
  3. Regressão: encaminhar_humano recuperado → SEM chamada pós-tool (2 chamadas) → None.
  4. Regressão: retry com texto puro (sem function_calls) → SEM chamada pós-tool (2 chamadas).

Contrato Gemini nativo (migração 09/07/2026): as chamadas ao LLM saem por
`app.agent.orchestrator.generate` (gemini_client) com `contents`/`system_instruction`;
o resultado de tool viaja como Part.function_response num Content role='user'.
"""
import pytest
from unittest.mock import AsyncMock, patch

from tests.gemini_fakes import fake_text, fake_tool_call


# ---------------------------------------------------------------------------
# Helpers (espelham o arquivo de retry irmão)
# ---------------------------------------------------------------------------

def _conversation(stage: str = "secretaria") -> dict:
    return {
        "id": "conv-karl-001",
        "stage": stage,
        "leads": {
            "id": "lead-karl-001",
            "name": None,
            "phone": "5531982950127",
            "ai_enabled": True,
        },
    }


def _history_one_user_msg(content: str = "Karl") -> list:
    return [
        {
            "role": "user",
            "content": content,
            "stage": "secretaria",
            "created_at": "2026-07-01T20:03:50Z",
            "wamid": "wamid-karl-01",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]


def _has_function_response(contents) -> bool:
    """True se algum Content do snapshot carrega um Part.function_response —
    equivalente nativo do antigo role 'tool' nas messages OpenAI."""
    for c in contents or []:
        for p in (getattr(c, "parts", None) or []):
            if getattr(p, "function_response", None) is not None:
                return True
    return False


# ---------------------------------------------------------------------------
# Teste 1: Karl — retry recupera tool NÃO-terminal → chamada PÓS-TOOL gera fala natural
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_nonterminal_tool_completes_react_cycle():
    """Caso Karl: inicial vazia → retry recupera salvar_nome (não-terminal) → o orchestrator
    faz a chamada PÓS-TOOL de continuação e devolve o texto natural, NÃO o genérico."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    natural_text = "prazer, Karl! como posso te ajudar hoje?"

    # Snapshot por chamada (cópia por valor, imune a mutações posteriores da lista):
    # a lista `contents` é mutada pelo orchestrator entre as chamadas.
    fr_snapshots: list[bool] = []
    tools_per_call: list = []
    n = {"i": 0}

    async def fake_generate(**kwargs):
        n["i"] += 1
        fr_snapshots.append(_has_function_response(kwargs.get("contents")))
        tools_per_call.append(kwargs.get("tools"))
        idx = n["i"]
        if idx == 1:
            # Chamada inicial → thinking-burn (vazia, sem function_calls)
            return fake_text("")
        if idx == 2:
            # Retry (tools mantidas) → recupera salvar_nome, sem texto
            return fake_tool_call("salvar_nome", {"name": "Karl"})
        # Chamada PÓS-TOOL de continuação → texto natural real
        return fake_text(natural_text)

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-karl-001", "phone": "5531982950127", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="Nome salvo: Karl") as mock_exec, \
         patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=fake_generate)):
        result = await run_agent(_conversation("secretaria"), "Karl")

    # Fez exatamente 3 chamadas: inicial + retry + PÓS-TOOL
    assert n["i"] == 3, f"esperado 3 chamadas (inicial+retry+pós-tool), got {n['i']}"
    # salvar_nome foi executado
    assert mock_exec.called
    assert mock_exec.call_args.args[0] == "salvar_nome"
    # Devolveu a fala natural — NÃO o genérico de recomeço
    assert result == natural_text, f"esperado o texto natural, got {result!r}"
    assert result != _SAFETY_FALLBACK_GENERIC
    # A chamada PÓS-TOOL (3ª) recebeu o resultado da tool nos contents (function_response
    # presente), provando que o ciclo ReAct foi fechado com contexto — e não só uma
    # releitura do vazio.
    assert fr_snapshots[2], (
        "a chamada pós-tool deve conter o resultado da tool (function_response) nos contents"
    )
    # A chamada de RETRY (2ª) ainda NÃO tinha o resultado da tool.
    assert not fr_snapshots[1], (
        "a chamada de retry não deve conter resultado de tool (function_response)"
    )
    # A chamada PÓS-TOOL manteve as tools do stage (mesmo contrato do loop principal).
    assert tools_per_call[2] is not None, "a chamada pós-tool deve manter as tools do stage"


# ---------------------------------------------------------------------------
# Teste 2: pós-tool também vazio → fallback genérico honesto (não silêncio "")
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_nonterminal_tool_post_tool_empty_falls_to_generic():
    """Se a chamada PÓS-TOOL também vier vazia, o lead ainda recebe o genérico honesto —
    nunca "" (silêncio), pois não houve soft-reject nem suppress."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    m_gen = AsyncMock(side_effect=[
        fake_text(""),                                    # inicial vazia
        fake_tool_call("salvar_nome", {"name": "Karl"}),  # retry → salvar_nome
        fake_text(""),                                    # pós-tool vazio também
        fake_text(""),                                    # retry2 (Etapa 2) vazio
    ])

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-karl-001", "phone": "5531982950127", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="Nome salvo: Karl") as mock_exec, \
         patch("app.agent.orchestrator.generate", new=m_gen):
        result = await run_agent(_conversation("secretaria"), "Karl")

    # Etapa 2: pós-tool vazio ainda deixa assistant_text vazio → dispara o retry2 (4ª chamada,
    # também vazia neste teste) antes de cair no fallback genérico.
    assert m_gen.await_count == 4, (
        f"esperado 4 chamadas (inicial+retry+pos-tool+retry2), got {m_gen.await_count}"
    )
    assert mock_exec.called and mock_exec.call_args.args[0] == "salvar_nome"
    assert result == _SAFETY_FALLBACK_GENERIC, f"esperado genérico honesto, got {result!r}"
    assert result != "", "nunca silêncio após tool não-terminal recuperada"


# ---------------------------------------------------------------------------
# Teste 3 (regressão terminal): encaminhar_humano recuperado no retry → SEM pós-tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_encaminhar_humano_no_post_tool_call():
    """encaminhar_humano recuperado no retry faz curto-circuito ANTES da chamada pós-tool:
    exatamente 2 chamadas (inicial + retry) e run_agent retorna None."""
    from app.agent.orchestrator import run_agent

    m_gen = AsyncMock(side_effect=[
        fake_text(""),
        fake_tool_call(
            "encaminhar_humano",
            {"mensagem_despedida": "vou te passar pro João!", "motivo": "ticket alto"},
        ),
    ])

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-karl-001", "phone": "5531982950127", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="handoff enviado") as mock_exec, \
         patch("app.agent.orchestrator.generate", new=m_gen):
        result = await run_agent(_conversation("secretaria"), "quero fechar um pedido grande")

    assert result is None, f"esperado None (handoff sentinel), got {result!r}"
    # CRÍTICO: terminal faz curto-circuito → NENHUMA 3ª chamada pós-tool
    assert m_gen.await_count == 2, (
        f"terminal não deve disparar chamada pós-tool; esperado 2, got {m_gen.await_count}"
    )
    assert mock_exec.called and mock_exec.call_args.args[0] == "encaminhar_humano"


# ---------------------------------------------------------------------------
# Teste 4 (regressão texto puro): retry sem function_calls → SEM pós-tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_pure_text_no_post_tool_call():
    """Quando o retry devolve texto puro (sem function_calls), NÃO há chamada pós-tool:
    exatamente 2 chamadas e o texto do retry é entregue como está."""
    from app.agent.orchestrator import run_agent

    m_gen = AsyncMock(side_effect=[
        fake_text(""),
        fake_text("oi! me conta o que você precisa"),
    ])

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-karl-001", "phone": "5531982950127", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=m_gen):
        result = await run_agent(_conversation("secretaria"), "oi")

    assert result == "oi! me conta o que você precisa"
    assert m_gen.await_count == 2, (
        f"texto puro no retry não deve disparar pós-tool; esperado 2, got {m_gen.await_count}"
    )
