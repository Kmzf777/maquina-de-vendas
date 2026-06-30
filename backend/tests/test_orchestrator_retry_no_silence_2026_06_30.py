"""Testes TDD para as mudanças de 2026-06-30 no retry-on-empty do orchestrator.

Contexto forense:
  Lead private_label, stage 'secretaria', respondeu 'Marca própria'.
  Primeira chamada ao Gemini: completion_tokens=0 (vazio). O retry anterior passava
  tools=None, castrando o agente: quando o turno vazio precisava de encaminhar_humano, o
  modelo re-vazava o call como tool_code, o sanitizer limpava, e o lead ficava 21h mudo.

Mudanças validadas aqui:
  Change A — retry mantém tools, salvo loop descontrolado (tool_iterations > MAX).
  Change B — retry com tool_calls executa a intenção (encaminhar_humano → sentinel None).
  Change C — _empty_fallback_text nunca mais retorna None; lead nunca fica em silêncio.

Cobertura:
  1. _empty_fallback_text(False, None) retorna string não-vazia sem 'cortada'.
  2. Retry recebe tools PRESENTES quando tool_iterations <= MAX_TOOL_ITERATIONS.
  3. Retry recebe tools=None quando tool_iterations > MAX_TOOL_ITERATIONS (runaway).
  4. Retry com encaminhar_humano tool_call → execute_tool chamado, run_agent retorna None.
  5. End-to-end: turno vazio no stage 'secretaria' sem mídia/transição → retorna genérico.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, args: dict = None, call_id: str = "tc-001") -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args or {})
    return tc


def _make_response(content: str | None, tool_calls=None) -> MagicMock:
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls  # None → falsy → loop exits
    msg.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


def _conversation(stage: str = "secretaria") -> dict:
    return {
        "id": "conv-pl-001",
        "stage": stage,
        "leads": {
            "id": "lead-pl-001",
            "name": "Fulana",
            "phone": "5511900000099",
            "ai_enabled": True,
        },
    }


def _history_one_user_msg(content: str = "Marca própria") -> list:
    return [
        {
            "role": "user",
            "content": content,
            "stage": "secretaria",
            "created_at": "2026-06-29T12:00:00Z",
            "wamid": "wamid-pl-01",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]


# ---------------------------------------------------------------------------
# Teste 1: _empty_fallback_text genérico → string não-vazia, sem 'cortada'
# ---------------------------------------------------------------------------

def test_empty_fallback_text_generic_returns_nonempty_string():
    """Change C: _empty_fallback_text(False, None) retorna o genérico honesto, nunca None."""
    from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_GENERIC
    result = _empty_fallback_text(False, None)
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    assert result == _SAFETY_FALLBACK_GENERIC
    # Garante que o texto proibido (auditoria 2026-06-24) não voltou
    assert "cortada" not in result


# ---------------------------------------------------------------------------
# Teste 2: retry passa tools PRESENTES quando tool_iterations <= MAX
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_keeps_tools_when_iterations_within_limit():
    """Change A: quando tool_iterations <= MAX_TOOL_ITERATIONS, o retry usa os tools do stage."""
    from app.agent.orchestrator import run_agent

    captured_calls: list[dict] = []

    async def fake_create(**kwargs):
        captured_calls.append(kwargs.copy())
        idx = len(captured_calls)
        if idx == 1:
            # Chamada inicial → vazia (sem tool_calls, sem text)
            return _make_response(content="", tool_calls=None)
        # Retry → text real (encerra o fluxo)
        return _make_response(content="oi, me conta o que você precisa", tool_calls=None)

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "Marca própria")

    assert len(captured_calls) == 2, "deve ter feito exatamente inicial + retry"
    # Chamada inicial: tools presentes (stage secretaria tem tools)
    initial_tools = captured_calls[0].get("tools")
    assert initial_tools is not None, "chamada inicial deve ter tools"
    # Retry: tool_iterations=0 (sem tool loop) → retry_tools deve ser não-None
    retry_tools = captured_calls[1].get("tools")
    assert retry_tools is not None, "retry deve manter tools quando tool_iterations <= MAX"
    assert result == "oi, me conta o que você precisa"


# ---------------------------------------------------------------------------
# Teste 3: retry usa tools=None quando tool_iterations > MAX_TOOL_ITERATIONS (runaway)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_strips_tools_when_runaway_loop():
    """Change A: quando tool_iterations > MAX_TOOL_ITERATIONS, retry usa tools=None (loop guard)."""
    from app.agent.orchestrator import run_agent

    captured_calls: list[dict] = []

    # Usamos um tool simples que roda N vezes até o loop guard intervir.
    # Com MAX_TOOL_ITERATIONS=5, precisamos 6 iterações. Para simplificar,
    # patchamos MAX_TOOL_ITERATIONS=1: 2 iterações já disparam o guard.
    runaway_tc = _make_tool_call("marcar_interesse", {}, "tc-runaway")

    async def fake_create(**kwargs):
        captured_calls.append(kwargs.copy())
        idx = len(captured_calls)
        if idx == 1:
            # Chamada inicial → tool_call (entra no loop, iter 1)
            return _make_response(content=None, tool_calls=[runaway_tc])
        if idx == 2:
            # Pós-tool iter 1 → tool_call (iter 2 > MAX=1 → loop guard dispara)
            return _make_response(content=None, tool_calls=[runaway_tc])
        if idx == 3:
            # Loop guard faz sua própria chamada com tools=None → retorna vazio
            return _make_response(content="", tool_calls=None)
        # Retry-on-empty → vazio (para o teste chegar ao fallback)
        return _make_response(content="", tool_calls=None)

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="interesse registrado")), \
         patch("app.agent.orchestrator.MAX_TOOL_ITERATIONS", 1), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "Marca própria")

    # Deve ter feito 4 chamadas: inicial, pós-tool, loop-guard, retry-on-empty
    assert len(captured_calls) == 4, f"esperado 4 chamadas, got {len(captured_calls)}"
    # Call #3 = loop guard (tools=None)
    assert captured_calls[2].get("tools") is None, "loop guard deve ter tools=None"
    # Call #4 = retry-on-empty com tool_iterations=2 > MAX=1 → retry_tools=None
    assert captured_calls[3].get("tools") is None, "retry deve ter tools=None em loop runaway"
    # Com fallback genérico (Change C) o resultado nunca é ""
    from app.agent.orchestrator import _SAFETY_FALLBACK_GENERIC
    assert result == _SAFETY_FALLBACK_GENERIC


# ---------------------------------------------------------------------------
# Teste 4: retry retorna encaminhar_humano → execute_tool chamado, retorna None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_encaminhar_humano_executes_and_returns_none():
    """Change B: quando o retry recupera encaminhar_humano tool_call, execute_tool é chamado
    e run_agent retorna None (handoff sentinel), igual ao loop principal."""
    from app.agent.orchestrator import run_agent

    handoff_tc = _make_tool_call(
        "encaminhar_humano",
        {"mensagem_despedida": "passando pro João!", "motivo": "interesse complexo"},
        "tc-handoff",
    )

    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Chamada inicial → vazia (thinking budget esgotado)
            return _make_response(content="", tool_calls=None)
        # Retry (tools mantidas) → modelo recupera e retorna encaminhar_humano
        return _make_response(content=None, tool_calls=[handoff_tc])

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               return_value="handoff enviado") as mock_exec, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "Marca própria")

    # run_agent deve retornar None (sentinel de handoff)
    assert result is None, f"esperado None (handoff), got {result!r}"
    # execute_tool deve ter sido chamado para encaminhar_humano
    assert mock_exec.called, "execute_tool deve ter sido chamado para encaminhar_humano"
    called_tool_name = mock_exec.call_args.args[0]
    assert called_tool_name == "encaminhar_humano", (
        f"execute_tool deve ter sido chamado com 'encaminhar_humano', got {called_tool_name!r}"
    )


# ---------------------------------------------------------------------------
# Teste 5: end-to-end secretaria vazia (sem media, sem transição) → genérico honesto
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_secretaria_double_empty_yields_generic_fallback_not_empty_string():
    """End-to-end Change C: stage secretaria, ambas as chamadas vazias, sem tool call.
    run_agent nunca retorna '' — devolve o fallback genérico honesto."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    responses = [
        _make_response(content="", tool_calls=None),  # chamada inicial vazia
        _make_response(content="", tool_calls=None),  # retry vazio
    ]
    idx = {"i": 0}

    async def fake_create(**kwargs):
        resp = responses[idx["i"]]
        idx["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "Marca própria")

    # NUNCA retorna ""
    assert result != "", "run_agent nunca deve retornar '' para turno com histórico real"
    # Retorna o fallback genérico honesto
    assert result == _SAFETY_FALLBACK_GENERIC, f"esperado genérico, got {result!r}"
    # O texto proibido (auditoria 2026-06-24) não pode ter voltado
    assert "cortada" not in result
    assert idx["i"] == 2, "deve ter feito exatamente 2 chamadas (inicial + retry)"


# ---------------------------------------------------------------------------
# Teste 6 (Important #1): retry com JSON malformado → PULA o tool_call (não chama
# execute_tool com {}). Mesmo contrato do loop principal — evita corrupção silenciosa.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_malformed_json_skips_tool_call_no_empty_args():
    """Change B / Important #1: se o tool_call recuperado no retry tem JSON malformado,
    o tool_call é PULADO (continue) — execute_tool NUNCA é chamado com args vazios."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    # tool_call com arguments inválidos (não-JSON) — simula salvar_nome malformado
    bad_tc = MagicMock()
    bad_tc.id = "tc-bad"
    bad_tc.function.name = "salvar_nome"
    bad_tc.function.arguments = "{name: 'sem aspas',,}"  # JSON inválido

    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _make_response(content="", tool_calls=None)  # inicial vazia
        # retry → recupera salvar_nome com JSON quebrado, sem content
        return _make_response(content="", tool_calls=[bad_tc])

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="ok") as mock_exec, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "Marca própria")

    # execute_tool NUNCA deve ter sido chamado (tool_call malformado pulado)
    assert not mock_exec.called, "execute_tool não deve ser chamado para tool_call com JSON malformado"
    # Turno ainda vazio → fallback genérico honesto (não silêncio)
    assert result == _SAFETY_FALLBACK_GENERIC


# ---------------------------------------------------------------------------
# Teste 7 (Important #2a): retry recupera registrar_optout → retorna despedida,
# NÃO o fallback genérico (senão lead recebe despedida + re-engajamento no mesmo turno).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_registrar_optout_returns_farewell_not_generic():
    """Important #2: registrar_optout recuperado no retry → despedida sanitizada do content,
    nunca o fallback genérico de re-engajamento."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    farewell = "tudo bem, não te mando mais nada por aqui"
    optout_tc = _make_tool_call("registrar_optout", {"motivo": "pediu pra parar"}, "tc-optout")

    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _make_response(content="", tool_calls=None)  # inicial vazia
        # retry → recupera registrar_optout COM despedida no content
        return _make_response(content=farewell, tool_calls=[optout_tc])

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="opt-out registrado") as mock_exec, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "para de me mandar mensagem")

    assert result == farewell, f"esperado a despedida, got {result!r}"
    assert result != _SAFETY_FALLBACK_GENERIC, "não pode cair no fallback genérico após opt-out"
    assert mock_exec.called
    assert mock_exec.call_args.args[0] == "registrar_optout"


@pytest.mark.asyncio
async def test_retry_registrar_optout_empty_content_uses_default_farewell():
    """Important #2: registrar_optout recuperado sem despedida no content → default do loop
    principal, nunca o fallback genérico."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    default_farewell = "sem problema, não te mando mais mensagem por aqui\n\nqualquer coisa é só chamar"
    optout_tc = _make_tool_call("registrar_optout", {"motivo": "parar"}, "tc-optout-2")

    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _make_response(content="", tool_calls=None)
        return _make_response(content="", tool_calls=[optout_tc])  # sem despedida

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="opt-out registrado"), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "sair")

    assert result == default_farewell
    assert result != _SAFETY_FALLBACK_GENERIC


# ---------------------------------------------------------------------------
# Teste 8 (Important #2b): retry recupera registrar_sem_interesse_atual → retorna "".
# Silêncio é correto após soft rejection (a regra "nunca mudo" só vale p/ turnos normais).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_registrar_sem_interesse_returns_empty_string():
    """Important #2: registrar_sem_interesse_atual recuperado no retry → "" (silêncio),
    nunca o fallback genérico de re-engajamento."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    sem_int_tc = _make_tool_call(
        "registrar_sem_interesse_atual", {"motivo": "fora do ICP"}, "tc-semint"
    )

    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _make_response(content="", tool_calls=None)
        return _make_response(content="", tool_calls=[sem_int_tc])

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="descarte registrado") as mock_exec, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "já temos fornecedor")

    assert result == "", f"esperado '' (silêncio após soft rejection), got {result!r}"
    assert result != _SAFETY_FALLBACK_GENERIC
    assert mock_exec.called
    assert mock_exec.call_args.args[0] == "registrar_sem_interesse_atual"
