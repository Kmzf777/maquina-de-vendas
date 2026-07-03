"""Testes TDD para o 2º degrau do retry-on-empty (Etapa 2, Task 1 — 2026-07-02).

Contexto forense:
  Davi (02/07 15:45): objeção de preço + pedido de granel → initial + retry1 ambos
  completion_tokens=0 (duas linhas no token_usage no MESMO segundo) → o lead recebeu
  "me conta de novo o que você precisa" e teve que redigitar a objeção inteira.
  Samuel (01/07 08:10): mesma dupla de zero-completion.

Correção validada aqui:
  Quando o retry silencioso (1º degrau, thinking off) TAMBÉM volta vazio, o orchestrator
  tenta UMA última geração text-only com temperatura elevada (_RETRY2_TEMPERATURE=0.9,
  recomendação literal do guia de prompting do Gemini para fallback responses) + um nudge
  de fechamento (_RETRY2_NUDGE) como última message role=user. tools=None de propósito.
  NUNCA roda quando o destino do turno já é o silêncio (soft_reject_used /
  suppress_generic_fallback) — não há texto pra "recuperar" nesses casos.

  call_type no token_usage: a chamada inicial e as pós-tool do loop principal continuam
  "response"; as chamadas do retry existente (retry_resp E a continuação pós-tool do
  Change B) passam a "response_retry"; o novo retry2 usa "response_retry2".

Cobertura (itens 1-6 do brief):
  1. Caso Davi: initial vazio + retry1 vazio + retry2 devolve texto → retorna o texto do
     retry2; call_types ["response", "response_retry", "response_retry2"] nessa ordem.
  2. retry2 também vazio → cai no fallback final; exatamente UMA chamada de retry2.
  3. kwargs do retry2: temperature==0.9, tools is None, última message é o nudge (role user).
  4. soft_reject_used (registrar_sem_interesse_atual no loop principal) + turno vazio →
     retry2 NÃO chamado, retorno "" (silêncio preservado).
  5. suppress_generic_fallback=True + turno vazio → retry2 NÃO chamado, retorno "".
  6. Change B: retry1 recupera tool_call não-terminal (salvar_nome) e a continuação
     pós-tool devolve texto → retry2 NÃO chamado; call_types contêm "response_retry"
     tanto para o retry quanto para a continuação pós-tool.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers (espelham test_orchestrator_retry_post_tool_2026_07_01.py /
# test_orchestrator_retry_no_silence_2026_06_30.py)
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, args: dict = None, call_id: str = "tc-001") -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args or {})
    return tc


def _make_response(content: str | None, tool_calls=None, usage: bool = True) -> MagicMock:
    """Constrói uma resposta fake. usage=True (default) garante que track_token_usage
    seja chamado (response.usage truthy) — necessário para os testes que verificam
    a sequência de call_types."""
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls  # None → falsy → loop/branch sai
    msg.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.choices = [MagicMock(message=msg)]
    resp.usage = MagicMock(prompt_tokens=100, completion_tokens=(20 if content else 0)) if usage else None
    return resp


def _conversation(stage: str = "secretaria") -> dict:
    return {
        "id": "conv-retry2-001",
        "stage": stage,
        "leads": {
            "id": "lead-retry2-001",
            "name": None,
            "phone": "5531900000001",
            "ai_enabled": True,
        },
    }


def _history_one_user_msg(content: str = "preço") -> list:
    return [
        {
            "role": "user",
            "content": content,
            "stage": "secretaria",
            "created_at": "2026-07-02T15:45:00Z",
            "wamid": "wamid-retry2-01",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]


# ---------------------------------------------------------------------------
# Caso 1 (Davi): initial vazio + retry1 vazio + retry2 recupera o texto
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_davi_initial_and_retry1_empty_retry2_recovers_text():
    """Caso Davi 02/07 15:45: dois zeros seguidos (initial+retry1) — o retry2 com
    temperatura elevada recupera o texto e o lead NÃO precisa redigitar a objeção."""
    from app.agent.orchestrator import run_agent

    davi_text = "entendo a questao do preco\n\nposso fechar o granel com um desconto especial pra voce"
    user_msg = "acho caro, da pra fazer por menos no granel?"
    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        if n["i"] == 1:
            return _make_response(content="", tool_calls=None)      # inicial: thinking-burn
        if n["i"] == 2:
            return _make_response(content="", tool_calls=None)      # retry1: ainda vazio
        return _make_response(content=davi_text, tool_calls=None)   # retry2: recupera o texto

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg(user_msg)), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-retry2-001", "phone": "5531900000001", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage") as mock_track, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), user_msg)

    assert result == davi_text, f"esperado o texto do retry2, got {result!r}"
    assert n["i"] == 3, f"esperado exatamente 3 chamadas (inicial+retry1+retry2), got {n['i']}"
    call_types = [c.kwargs.get("call_type") for c in mock_track.call_args_list]
    assert call_types == ["response", "response_retry", "response_retry2"], (
        f"ordem de call_types incorreta: {call_types}"
    )


# ---------------------------------------------------------------------------
# Caso 2: retry2 TAMBÉM vazio → cai no fallback final; UMA chamada de retry2 (sem loop)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry2_also_empty_falls_to_final_fallback_single_attempt():
    """Os três tiros vazios → run_agent cai no fallback final (comportamento preservado);
    retry2 dispara exatamente UMA vez — não há loop de retentativas."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        return _make_response(content="", tool_calls=None)  # sempre vazio

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-retry2-001", "phone": "5531900000001", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage") as mock_track, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "preço")

    assert result == _SAFETY_FALLBACK_GENERIC, f"esperado o fallback final, got {result!r}"
    assert n["i"] == 3, f"esperado exatamente 3 chamadas (inicial+retry1+retry2), got {n['i']}"
    call_types = [c.kwargs.get("call_type") for c in mock_track.call_args_list]
    assert call_types == ["response", "response_retry", "response_retry2"], (
        f"ordem de call_types incorreta: {call_types}"
    )


# ---------------------------------------------------------------------------
# Caso 3: kwargs do retry2 — temperature==0.9, tools is None, última message é o nudge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry2_kwargs_temperature_tools_none_and_nudge_last_message():
    """A chamada de retry2 deve usar temperatura elevada, tools=None e ter o nudge de
    recuperação como a ÚLTIMA message (role=user)."""
    from app.agent.orchestrator import run_agent, _RETRY2_TEMPERATURE, _RETRY2_NUDGE

    assert _RETRY2_TEMPERATURE == 0.9

    captured_calls: list[dict] = []

    async def fake_create(**kwargs):
        captured_calls.append(kwargs)
        idx = len(captured_calls)
        if idx <= 2:
            return _make_response(content="", tool_calls=None)
        return _make_response(content="ok, entendi", tool_calls=None)

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-retry2-001", "phone": "5531900000001", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "preço")

    assert len(captured_calls) == 3, f"esperado 3 chamadas, got {len(captured_calls)}"
    retry2_kwargs = captured_calls[2]
    assert retry2_kwargs.get("temperature") == 0.9
    assert retry2_kwargs.get("tools") is None
    retry2_messages = retry2_kwargs.get("messages")
    assert retry2_messages, "retry2 deve receber messages"
    assert retry2_messages[-1] == {"role": "user", "content": _RETRY2_NUDGE}, (
        f"a ultima message do retry2 deve ser o nudge (role=user), got {retry2_messages[-1]!r}"
    )
    assert result == "ok, entendi"


# ---------------------------------------------------------------------------
# Caso 4: soft_reject_used (registrar_sem_interesse_atual no loop principal) → retry2
# NÃO chamado, retorno "" (silêncio preservado)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_soft_reject_used_skips_retry2_returns_empty():
    """Caminho mais simples (per brief): registrar_sem_interesse_atual no LOOP PRINCIPAL
    seguido de mute pós-tool + mute no retry1 → retry2 NÃO deve rodar (destino é o
    silêncio) e run_agent retorna "" — nunca gasta a chamada extra à toa."""
    from app.agent.orchestrator import run_agent

    sem_int_tc = _make_tool_call(
        "registrar_sem_interesse_atual", {"motivo": "ja tem fornecedor fixo"}, "tc-semint-retry2"
    )
    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        if n["i"] == 1:
            return _make_response(content=None, tool_calls=[sem_int_tc])  # loop principal: descarte
        return _make_response(content="", tool_calls=None)  # pós-tool (2) e retry1 (3): mudos

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg("ja temos fornecedor fixo")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-retry2-001", "phone": "5531900000001", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="descarte registrado") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage") as mock_track, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "ja temos fornecedor fixo")

    assert result == "", f"esperado silencio apos soft rejection, got {result!r}"
    assert n["i"] == 3, f"retry2 NAO deve ser chamado apos soft_reject_used; esperado 3, got {n['i']}"
    assert mock_exec.called and mock_exec.call_args.args[0] == "registrar_sem_interesse_atual"
    call_types = [c.kwargs.get("call_type") for c in mock_track.call_args_list]
    assert "response_retry2" not in call_types, f"retry2 nao deveria ter registrado uso: {call_types}"


# ---------------------------------------------------------------------------
# Caso 5: suppress_generic_fallback=True + turno vazio → retry2 NÃO chamado, retorno ""
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_suppress_generic_fallback_skips_retry2_returns_empty():
    """Gatilho interno (ex.: reabertura proativa ai_scheduled_return) sem mensagem real
    do lead → retry2 NÃO deve rodar quando suppress_generic_fallback=True; retorna ""."""
    from app.agent.orchestrator import run_agent

    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        return _make_response(content="", tool_calls=None)

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg("[GATILHO INTERNO]")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-retry2-001", "phone": "5531900000001", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage") as mock_track, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(
            _conversation("secretaria"), "[GATILHO INTERNO]",
            suppress_generic_fallback=True,
        )

    assert result == "", f"esperado '', got {result!r}"
    assert n["i"] == 2, f"retry2 NAO deve ser chamado com suppress_generic_fallback=True; esperado 2, got {n['i']}"
    call_types = [c.kwargs.get("call_type") for c in mock_track.call_args_list]
    assert "response_retry2" not in call_types, f"retry2 nao deveria ter registrado uso: {call_types}"


# ---------------------------------------------------------------------------
# Caso 6 (Change B): retry1 recupera tool não-terminal (salvar_nome) e a continuação
# pós-tool devolve texto → retry2 NÃO chamado; call_types contêm "response_retry" para
# a continuação (E para o retry1 que a precedeu).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_change_b_post_tool_recovers_text_skips_retry2():
    """Espelha o caso Karl (test_orchestrator_retry_post_tool_2026_07_01.py): retry1
    recupera salvar_nome (não-terminal) e a chamada pós-tool de continuação (Change B)
    já devolve o texto natural — retry2 não deve rodar (assistant_text já não está vazio).
    call_types: retry1 E a continuação pós-tool ficam "response_retry"."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    natural_text = "prazer, Karl! como posso te ajudar hoje?"
    salvar_tc = _make_tool_call("salvar_nome", {"name": "Karl"}, "tc-salvar-retry2")
    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        if n["i"] == 1:
            return _make_response(content="", tool_calls=None)          # inicial: vazia
        if n["i"] == 2:
            return _make_response(content="", tool_calls=[salvar_tc])   # retry1: recupera salvar_nome
        return _make_response(content=natural_text, tool_calls=None)    # pós-tool (Change B): texto natural

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg("Karl")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-retry2-001", "phone": "5531900000001", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="Nome salvo: Karl") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage") as mock_track, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "Karl")

    assert result == natural_text, f"esperado o texto natural, got {result!r}"
    assert result != _SAFETY_FALLBACK_GENERIC
    assert mock_exec.called and mock_exec.call_args.args[0] == "salvar_nome"
    assert n["i"] == 3, (
        f"retry2 NAO deve ser chamado quando a continuacao pos-tool do Change B ja "
        f"recuperou texto; esperado 3 chamadas, got {n['i']}"
    )
    call_types = [c.kwargs.get("call_type") for c in mock_track.call_args_list]
    assert call_types == ["response", "response_retry", "response_retry"], (
        f"esperado response -> response_retry (retry1) -> response_retry (continuacao), got {call_types}"
    )
