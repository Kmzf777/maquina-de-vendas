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

Nota de conversão (Gemini 100% nativo, 09/07/2026): mocks OpenAI → GenerateResult fakes
(tests/gemini_fakes) com patch de app.agent.orchestrator.generate. O teste de "JSON
malformado" (Teste 6) virou "args com shape inesperado" — o SDK nativo entrega dict, mas
o orchestrator mantém a defesa herdada (isinstance(args, dict)); o teste injeta um
FunctionCall com args string (o equivalente moderno do arguments não-parseável) e valida
o MESMO contrato: pula a tool sem chamar execute_tool com {}.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.agent.gemini_client import FunctionCall
from tests.gemini_fakes import fake_text, fake_tool_call


def _malformed_args_result(name: str = "salvar_nome"):
    """GenerateResult cujo FunctionCall.args tem shape inesperado (string em vez de dict)
    — equivalente nativo do antigo `arguments = "{name: 'sem aspas',,}"` (JSON inválido)."""
    result = fake_tool_call(name, {})
    result.function_calls = [FunctionCall(name=name, args="{name: 'sem aspas',,}")]
    return result


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

    async def fake_generate(**kwargs):
        captured_calls.append(kwargs.copy())
        idx = len(captured_calls)
        if idx == 1:
            # Chamada inicial → vazia (sem tool_calls, sem text)
            return fake_text("")
        # Retry → text real (encerra o fluxo)
        return fake_text("oi, me conta o que você precisa")

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
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
    async def fake_generate(**kwargs):
        captured_calls.append(kwargs.copy())
        idx = len(captured_calls)
        if idx == 1:
            # Chamada inicial → tool_call (entra no loop, iter 1)
            return fake_tool_call("marcar_interesse", {})
        if idx == 2:
            # Pós-tool iter 1 → tool_call (iter 2 > MAX=1 → loop guard dispara)
            return fake_tool_call("marcar_interesse", {})
        if idx == 3:
            # Loop guard faz sua própria chamada com tools=None → retorna vazio
            return fake_text("")
        # Retry-on-empty (idx 4) e retry2 (idx 5) → vazios (para o teste chegar ao fallback)
        return fake_text("")

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="interesse registrado")), \
         patch("app.agent.orchestrator.MAX_TOOL_ITERATIONS", 1), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
        result = await run_agent(_conversation("secretaria"), "Marca própria")

    # Deve ter feito 5 chamadas: inicial, pós-tool, loop-guard, retry-on-empty, retry2 (Etapa 2)
    assert len(captured_calls) == 5, f"esperado 5 chamadas, got {len(captured_calls)}"
    # Call #3 = loop guard (tools=None)
    assert captured_calls[2].get("tools") is None, "loop guard deve ter tools=None"
    # Call #4 = retry-on-empty com tool_iterations=2 > MAX=1 → retry_tools=None
    assert captured_calls[3].get("tools") is None, "retry deve ter tools=None em loop runaway"
    # Call #5 = retry2 (Etapa 2) → tools=None sempre, por design
    assert captured_calls[4].get("tools") is None, "retry2 deve ter tools=None"
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

    call_count = {"n": 0}

    async def fake_generate(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Chamada inicial → vazia (thinking budget esgotado)
            return fake_text("")
        # Retry (tools mantidas) → modelo recupera e retorna encaminhar_humano
        return fake_tool_call(
            "encaminhar_humano",
            {"mensagem_despedida": "passando pro João!", "motivo": "interesse complexo"},
        )

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               return_value="handoff enviado") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
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
        fake_text(""),  # chamada inicial vazia
        fake_text(""),  # retry vazio
        fake_text(""),  # retry2 (Etapa 2) também vazio
    ]
    idx = {"i": 0}

    async def fake_generate(**kwargs):
        resp = responses[idx["i"]]
        idx["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
        result = await run_agent(_conversation("secretaria"), "Marca própria")

    # NUNCA retorna ""
    assert result != "", "run_agent nunca deve retornar '' para turno com histórico real"
    # Retorna o fallback genérico honesto
    assert result == _SAFETY_FALLBACK_GENERIC, f"esperado genérico, got {result!r}"
    # O texto proibido (auditoria 2026-06-24) não pode ter voltado
    assert "cortada" not in result
    assert idx["i"] == 3, "deve ter feito exatamente 3 chamadas (inicial + retry + retry2)"


# ---------------------------------------------------------------------------
# Teste 6 (Important #1): retry com args de shape inesperado → PULA o tool_call (não
# chama execute_tool com {}). Mesmo contrato do loop principal — evita corrupção silenciosa.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_malformed_json_skips_tool_call_no_empty_args():
    """Change B / Important #1: se o tool_call recuperado no retry tem args com shape
    inesperado (não-dict — herdeiro do JSON malformado da era OpenAI), o tool_call é
    PULADO (continue) — execute_tool NUNCA é chamado com args vazios."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    call_count = {"n": 0}

    async def fake_generate(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return fake_text("")  # inicial vazia
        if call_count["n"] == 2:
            # retry → recupera salvar_nome com args quebrados, sem content
            return _malformed_args_result("salvar_nome")
        # continuação pós-tool / retry2 → vazias (para o teste chegar ao fallback)
        return fake_text("")

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="ok") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
        result = await run_agent(_conversation("secretaria"), "Marca própria")

    # execute_tool NUNCA deve ter sido chamado (tool_call malformado pulado)
    assert not mock_exec.called, "execute_tool não deve ser chamado para tool_call com args malformados"
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

    call_count = {"n": 0}

    async def fake_generate(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return fake_text("")  # inicial vazia
        # retry → recupera registrar_optout COM despedida no content
        return fake_tool_call("registrar_optout", {"motivo": "pediu pra parar"}, text=farewell)

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="opt-out registrado") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
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

    call_count = {"n": 0}

    async def fake_generate(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return fake_text("")
        return fake_tool_call("registrar_optout", {"motivo": "parar"})  # sem despedida

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="opt-out registrado"), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
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

    call_count = {"n": 0}

    async def fake_generate(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return fake_text("")
        return fake_tool_call("registrar_sem_interesse_atual", {"motivo": "fora do ICP"})

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="descarte registrado") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
        result = await run_agent(_conversation("secretaria"), "já temos fornecedor")

    assert result == "", f"esperado '' (silêncio após soft rejection), got {result!r}"
    assert result != _SAFETY_FALLBACK_GENERIC
    assert mock_exec.called
    assert mock_exec.call_args.args[0] == "registrar_sem_interesse_atual"


# ---------------------------------------------------------------------------
# Teste 9 (Regressão Change C #1): registrar_sem_interesse_atual no LOOP PRINCIPAL,
# seguido de mute pós-tool + mute no retry → "" (silêncio), NÃO o genérico.
# O lead foi descartado (stage=perdido, ai_enabled=False); re-engajar é incoerente.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_loop_sem_interesse_then_mute_returns_empty_not_generic():
    """O loop principal executa registrar_sem_interesse_atual (descarte), o modelo fica mudo
    no pós-tool E no retry → run_agent retorna "" em vez do fallback genérico de re-engajamento."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    call_count = {"n": 0}

    async def fake_generate(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Chamada inicial → tool_call de descarte (entra no loop)
            return fake_tool_call("registrar_sem_interesse_atual", {"motivo": "já temos fornecedor fixo"})
        # Pós-tool (2) e retry (3) → mudos
        return fake_text("")

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="descarte registrado") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
        result = await run_agent(_conversation("secretaria"), "já temos fornecedor")

    assert result == "", f"esperado '' (silêncio após descarte no loop principal), got {result!r}"
    assert result != _SAFETY_FALLBACK_GENERIC
    assert mock_exec.called
    assert mock_exec.call_args.args[0] == "registrar_sem_interesse_atual"


# ---------------------------------------------------------------------------
# Teste 10 (Regressão Change C #2): suppress_generic_fallback=True → turno todo mudo
# em secretaria retorna "" (reabertura proativa não deve mandar re-engajamento incoerente).
# Sem o flag, o MESMO turno retorna o genérico (trava ambos os lados).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_suppress_generic_fallback_returns_empty_on_mute():
    """run_agent(..., suppress_generic_fallback=True) com turno totalmente mudo → ""."""
    from app.agent.orchestrator import run_agent

    responses = [
        fake_text(""),  # inicial mudo
        fake_text(""),  # retry mudo
    ]
    idx = {"i": 0}

    async def fake_generate(**kwargs):
        resp = responses[idx["i"]]
        idx["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
        result = await run_agent(
            _conversation("secretaria"), "[GATILHO INTERNO]",
            suppress_generic_fallback=True,
        )

    assert result == "", f"com suppress_generic_fallback=True deve retornar '', got {result!r}"


@pytest.mark.asyncio
async def test_without_suppress_flag_same_mute_turn_returns_generic():
    """Mesmo turno mudo, SEM o flag → retorna o genérico (lado oposto do par, trava o contrato)."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    responses = [
        fake_text(""),
        fake_text(""),
        fake_text(""),  # retry2 (Etapa 2) também mudo
    ]
    idx = {"i": 0}

    async def fake_generate(**kwargs):
        resp = responses[idx["i"]]
        idx["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
        result = await run_agent(_conversation("secretaria"), "[GATILHO INTERNO]")

    assert result == _SAFETY_FALLBACK_GENERIC, (
        f"sem o flag, turno mudo normal deve usar o genérico, got {result!r}"
    )


@pytest.mark.asyncio
async def test_normal_mute_turn_still_returns_generic_regression_guard():
    """Guarda de regressão: turno mudo NORMAL (sem soft-reject, sem flag) continua devolvendo
    o genérico honesto — a Change C original não pode ter sido revertida acidentalmente."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    responses = [
        fake_text(""),
        fake_text(""),
        fake_text(""),  # retry2 (Etapa 2) também mudo
    ]
    idx = {"i": 0}

    async def fake_generate(**kwargs):
        resp = responses[idx["i"]]
        idx["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg("oi tudo bem?")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-pl-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=fake_generate)):
        result = await run_agent(_conversation("secretaria"), "oi tudo bem?")

    assert result == _SAFETY_FALLBACK_GENERIC
