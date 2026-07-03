"""Testes TDD para idempotência de mídia POR TURNO no caminho de retry (Etapa 2, Task 3
— caso Samuel 01/07 08:11-08:12).

Contexto forense:
  Samuel (01/07 08:11-08:12): o loop principal executou `enviar_fotos` (catálogo de fotos
  de atacado). A chamada pós-tool do MESMO loop devolveu completion_tokens=0 (thinking-burn
  — o mesmo bug de fundo do retry-on-empty). O retry silencioso (Change B, 2026-06-30)
  recuperou `tool_calls` e, como o guard atual só olha `_MEDIA_TOOL_NAMES` para SETAR
  `media_tool_used`, executou `enviar_fotos` DE NOVO — o lead recebeu o catálogo de fotos
  2x na mesma janela de 1 minuto.

  O dedup CROSS-TURN via histórico já existe em tools.py (`enviar_fotos`/`enviar_foto_produto`
  leem o marcador `[enviar_fotos]`/`[enviar_foto_produto]` salvo no DB — ver
  test_enviar_fotos_idempotente.py). Esse dedup NÃO cobre o caso Samuel: a 1ª execução é
  do MESMO turno, e não há garantia de read-after-write no banco no instante em que o
  Change B roda — daí o furo SAME-TURN corrigido aqui.

Correção validada aqui:
  No caminho Change B (retry1 recuperou tool_calls), ANTES de `execute_tool` para cada
  tool call: se a tool é de mídia (`_MEDIA_TOOL_NAMES`) E `media_tool_used` já é True
  (uma tool de mídia já executou neste turno, no loop principal), NÃO executa de novo —
  anexa um tool result sintético ("fotos já processadas neste turno — não reenviar") e
  segue o fluxo normalmente (mesmo contrato de mensagem role=tool com tool_call_id).

  Casos legítimos preservados: retry recupera tool de mídia SEM execução prévia no turno
  → executa normalmente. Tools NÃO-mídia no retry (ex. salvar_nome) → sempre executam,
  independente de `media_tool_used`. Loop principal → intocado.

Cobertura (Step 1 do brief):
  1. Same-turn (o furo): loop principal executa enviar_fotos, pós-tool vazio, retry1
     devolve tool_calls=[enviar_fotos] de novo → execute_tool chamado UMA vez só; messages
     contêm o result sintético; fluxo continua até resposta final sem exceção.
  2. Retry1 recupera tool de mídia SEM execução prévia no turno (media_tool_used=False)
     → executa normalmente (guard não bloqueia o caso legítimo).
  3. Tool NÃO-mídia recuperada no retry (salvar_nome), mesmo com media_tool_used=True
     (mídia já executou no loop principal) → executa normalmente (guard só vale para
     _MEDIA_TOOL_NAMES).
  4. Regressão cross-turn (pin do fix já mergeado): test_enviar_fotos_idempotente.py
     continua verde — coberto rodando a regressão (-k "orchestrator or enviar_fotos or
     retry"), sem duplicar os casos aqui.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers (espelham test_orchestrator_retry2_2026_07_02.py / test_orchestrator_retry_
# post_tool_2026_07_01.py)
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, args: dict = None, call_id: str = "tc-001") -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args or {})
    return tc


def _make_response(content: str | None, tool_calls=None, usage: bool = True) -> MagicMock:
    """Constrói uma resposta fake. usage=True (default) garante que track_token_usage
    seja chamado (response.usage truthy)."""
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls  # None → falsy → loop/branch sai
    msg.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.choices = [MagicMock(message=msg)]
    resp.usage = MagicMock(prompt_tokens=100, completion_tokens=(20 if content else 0)) if usage else None
    return resp


def _conversation(stage: str = "atacado") -> dict:
    return {
        "id": "conv-media-once-001",
        "stage": stage,
        "leads": {
            "id": "lead-media-once-001",
            "name": None,
            "phone": "5531900000009",
            "ai_enabled": True,
        },
    }


def _history_one_user_msg(content: str = "manda as fotos") -> list:
    return [
        {
            "role": "user",
            "content": content,
            "stage": "atacado",
            "created_at": "2026-07-01T08:11:00Z",
            "wamid": "wamid-samuel-01",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]


# ---------------------------------------------------------------------------
# Caso 1 (Samuel, o furo): loop principal executa enviar_fotos, pós-tool vazio, retry1
# recupera enviar_fotos DE NOVO → guard bloqueia a 2ª execução
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_tool_same_turn_guard_blocks_second_execution():
    """Caso Samuel 01/07 08:11-08:12: enviar_fotos executa no loop principal; a chamada
    pós-tool (mesmo loop) vem vazia (thinking-burn); o retry silencioso recupera
    tool_calls=[enviar_fotos] DE NOVO. O guard do Change B deve impedir a 2ª execução:
    execute_tool chamado UMA vez só para enviar_fotos; a continuação pós-tool do Change B
    recebe o result sintético nas messages; o turno termina com o texto final, sem
    exceção."""
    from app.agent.orchestrator import run_agent

    fotos_tc_1 = _make_tool_call("enviar_fotos", {"categoria": "atacado"}, "tc-fotos-1")
    fotos_tc_2 = _make_tool_call("enviar_fotos", {"categoria": "atacado"}, "tc-fotos-2")
    final_text = "te mandei as fotos aqui\n\nqual delas chamou mais a sua atenção?"
    captured_calls: list[dict] = []

    async def fake_create(**kwargs):
        captured_calls.append(kwargs)
        idx = len(captured_calls)
        if idx == 1:
            return _make_response(content=None, tool_calls=[fotos_tc_1])  # loop principal: chama enviar_fotos
        if idx == 2:
            return _make_response(content="", tool_calls=None)  # pós-tool (loop principal): vazio
        if idx == 3:
            return _make_response(content="", tool_calls=[fotos_tc_2])  # retry1: recupera enviar_fotos DE NOVO
        return _make_response(content=final_text, tool_calls=None)  # continuação pós-tool (Change B)

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-media-once-001", "phone": "5531900000009", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               return_value="5 fotos de atacado enfileiradas para envio após o texto") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("atacado"), "manda as fotos")

    assert result == final_text, f"esperado o texto final, got {result!r}"
    assert len(captured_calls) == 4, f"esperado 4 chamadas ao LLM, got {len(captured_calls)}"
    assert mock_exec.call_count == 1, (
        f"enviar_fotos deve executar UMA vez so no turno (loop principal); "
        f"got {mock_exec.call_count} chamadas"
    )
    assert mock_exec.call_args.args[0] == "enviar_fotos"

    # A continuação pós-tool (4ª chamada, Change B) deve conter o result SINTÉTICO
    # associado ao tool_call_id da 2ª tool call (tc-fotos-2) — prova de que o fluxo
    # seguiu normalmente sem re-executar a tool.
    post_tool_messages = captured_calls[3]["messages"]
    synthetic = [
        m for m in post_tool_messages
        if isinstance(m, dict) and m.get("role") == "tool" and m.get("tool_call_id") == "tc-fotos-2"
    ]
    assert len(synthetic) == 1, f"esperado 1 tool result sintético para tc-fotos-2, got {synthetic}"
    assert "não reenviar" in synthetic[0]["content"] or "nao reenviar" in synthetic[0]["content"].lower()


# ---------------------------------------------------------------------------
# Caso 2: retry1 recupera tool de mídia SEM execução prévia no turno
# (media_tool_used=False) → guard NÃO bloqueia o caso legítimo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_recovers_media_tool_without_prior_execution_runs_normally():
    """Caso legítimo: nenhuma tool de mídia executou no loop principal deste turno
    (turno inicial veio vazio, sem tool_calls) — quando o retry1 recupera enviar_fotos
    pela PRIMEIRA vez, o guard não deve bloquear; executa normalmente e seta
    media_tool_used."""
    from app.agent.orchestrator import run_agent

    fotos_tc = _make_tool_call("enviar_fotos", {"categoria": "atacado"}, "tc-fotos-legit")
    final_text = "te mandei as fotos aqui\n\nqual delas chamou mais a sua atenção?"
    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        if n["i"] == 1:
            return _make_response(content="", tool_calls=None)  # inicial: vazio (thinking-burn)
        if n["i"] == 2:
            return _make_response(content="", tool_calls=[fotos_tc])  # retry1: recupera enviar_fotos (1ª vez)
        return _make_response(content=final_text, tool_calls=None)  # continuação pós-tool

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-media-once-001", "phone": "5531900000009", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               return_value="5 fotos de atacado enfileiradas para envio após o texto") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("atacado"), "manda as fotos")

    assert result == final_text, f"esperado o texto final, got {result!r}"
    assert n["i"] == 3, f"esperado 3 chamadas (inicial+retry1+pós-tool), got {n['i']}"
    assert mock_exec.call_count == 1, "enviar_fotos deve executar (1ª vez no turno, guard não se aplica)"
    assert mock_exec.call_args.args[0] == "enviar_fotos"


# ---------------------------------------------------------------------------
# Caso 3: tool NÃO-mídia recuperada no retry (salvar_nome), mesmo com media_tool_used=True
# (mídia já executou no loop principal) → guard só vale para _MEDIA_TOOL_NAMES
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_recovers_non_media_tool_runs_normally_even_with_media_used():
    """Guard escopado: mesmo com media_tool_used=True (enviar_fotos já executou no loop
    principal deste turno), uma tool NÃO-mídia (salvar_nome) recuperada no retry1 deve
    executar normalmente — o guard nunca bloqueia tools fora de _MEDIA_TOOL_NAMES."""
    from app.agent.orchestrator import run_agent

    fotos_tc = _make_tool_call("enviar_fotos", {"categoria": "atacado"}, "tc-fotos-mainloop")
    salvar_tc = _make_tool_call("salvar_nome", {"name": "Samuel"}, "tc-salvar-nomidia")
    natural_text = "prazer, Samuel! bora ver as opções"
    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        if n["i"] == 1:
            return _make_response(content=None, tool_calls=[fotos_tc])  # loop principal: mídia
        if n["i"] == 2:
            return _make_response(content="", tool_calls=None)  # pós-tool (loop principal): vazio
        if n["i"] == 3:
            return _make_response(content="", tool_calls=[salvar_tc])  # retry1: recupera salvar_nome
        return _make_response(content=natural_text, tool_calls=None)  # continuação pós-tool

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg("Samuel, manda as fotos")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-media-once-001", "phone": "5531900000009", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               side_effect=[
                   "5 fotos de atacado enfileiradas para envio após o texto",
                   "Nome salvo: Samuel",
               ]) as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("atacado"), "Samuel, manda as fotos")

    assert result == natural_text, f"esperado o texto natural, got {result!r}"
    assert n["i"] == 4, f"esperado 4 chamadas, got {n['i']}"
    assert mock_exec.call_count == 2, (
        f"ambas as tools devem executar (mídia 1x no loop principal + salvar_nome 1x no "
        f"retry); got {mock_exec.call_count}"
    )
    executed_names = [c.args[0] for c in mock_exec.call_args_list]
    assert executed_names == ["enviar_fotos", "salvar_nome"], (
        f"esperado ['enviar_fotos', 'salvar_nome'] nessa ordem, got {executed_names}"
    )
