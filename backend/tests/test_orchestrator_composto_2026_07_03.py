"""Testes TDD para os cenários de COMPOSIÇÃO entre o guard same-turn de mídia (Change B,
commit 50bca7f) e o retry-on-empty de 2 degraus (Etapa 2, Tasks 1/3) — follow-up review E2
(2026-07-03, plano docs/superpowers/plans/2026-07-03-valeria-pendencias-e1e2.md, Task 2).

Contexto forense (finding E2 do review final da Etapa 2):
  O guard same-turn de mídia (test_orchestrator_media_once_per_turn_2026_07_02.py) usa
  `media_tool_used`, que marca INTENÇÃO — setado ANTES do try/except que chama execute_tool,
  independente do resultado. Se execute_tool LEVANTAR exceção para uma tool de mídia no loop
  principal, `media_tool_used` fica True mesmo a execução tendo FALHADO de verdade (o lead
  não recebeu nada). Quando o retry recupera a MESMA tool_call (Change B), o guard usava só
  `media_tool_used` e bloqueava a RE-EXECUÇÃO LEGÍTIMA — o lead nunca recebe as fotos, mesmo
  a tentativa original tendo falhado.

  Corrigido com uma 2ª flag, `media_exec_failed` (default False, setada nos DOIS ramos
  `except Exception` que envolvem execute_tool de uma tool de mídia — loop principal E
  Change B): o guard same-turn passa de `media_tool_used` para `media_tool_used and not
  media_exec_failed`.

  `media_tool_used` (intenção) continua INTOCADO como sinal do fallback de mídia
  (_empty_fallback_text/_SAFETY_FALLBACK_MEDIA) — mudar essa semântica do fallback foi
  explicitamente ADIADA pelo review; não faz parte deste follow-up.

Cobertura (Task 2 do plano):
  (a) mídia executa OK no loop principal → pós-tool vazio → retry1 vazio → retry2 devolve
      TEXTO → run_agent retorna o texto (texto real vence o fallback de mídia — composição
      preexistente, pin de regressão; NÃO depende da flag nova).
  (b) guard same-turn dispara (mídia já ok no turno, SEM falha) → continuação Change B vazia
      → retry2 RODA ("response_retry2" presente na ordem de call_types — composição
      preexistente, pin de regressão; guard bloqueia igual antes/depois da flag nova).
  (c) NOVO comportamento: mídia FALHA no loop principal (execute_tool levanta exceção) →
      retry1 recupera a MESMA tool → guard NÃO bloqueia (media_exec_failed=True) → executa
      de verdade (execute_tool chamado 2x) — RED antes do fix, GREEN depois.
  (d) fast-follow (Important reproduzido pela review desta task): mídia com args MALFORMADOS
      no loop principal — era `arguments` JSON malformado na era OpenAI; hoje, com o SDK
      nativo entregando args como dict, o assunto é ARGS COM SHAPE INESPERADO (não-dict).
      media_tool_used vira True ANTES da checagem de shape, a tool NUNCA executa (continue)
      e, sem o fix, media_exec_failed não era setada → o guard bloqueava a re-execução
      legítima no retry e o turno fechava com execute_tool chamado 0x (o modelo "acha" que
      as fotos saíram). Com o fix, o ramo de args inválidos também seta media_exec_failed
      (mesma classe do except de execute_tool) → retry1 com args VÁLIDOS executa 1x —
      RED antes do fix, GREEN depois.

Migração 09/07 (Gemini 100% nativo): mocks via `app.agent.orchestrator.generate`
(GenerateResult fakes de tests/gemini_fakes). Os tool results agora viajam como parts
`function_response` dentro de kwargs["contents"] (não mais mensagens role="tool" com
tool_call_id) — sem id de tool call no protocolo nativo, os asserts distinguem as duas
execuções de enviar_fotos pela ORDEM dos function_response no histórico do turno.
"""
import pytest
from unittest.mock import AsyncMock, patch

from tests.gemini_fakes import fake_text, fake_tool_call


# ---------------------------------------------------------------------------
# Helpers (espelham test_orchestrator_retry2_2026_07_02.py /
# test_orchestrator_media_once_per_turn_2026_07_02.py)
# ---------------------------------------------------------------------------

def _conversation(stage: str = "atacado") -> dict:
    return {
        "id": "conv-composto-001",
        "stage": stage,
        "leads": {
            "id": "lead-composto-001",
            "name": None,
            "phone": "5531900000099",
            "ai_enabled": True,
        },
    }


def _history_one_user_msg(content: str = "manda as fotos") -> list:
    return [
        {
            "role": "user",
            "content": content,
            "stage": "atacado",
            "created_at": "2026-07-03T09:00:00Z",
            "wamid": "wamid-composto-01",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]


def _function_response_results(contents, tool_name: str) -> list[str]:
    """Extrai, na ORDEM do turno, os textos de function_response da tool dada.

    Contrato nativo: cada tool result é um types.Content role='user' com um part
    function_response(name=..., response={'result': texto}) — substitui a antiga
    mensagem {'role': 'tool', 'tool_call_id': ..., 'content': ...}.
    """
    results = []
    for c in contents:
        for p in (getattr(c, "parts", None) or []):
            fr = getattr(p, "function_response", None)
            if fr is not None and fr.name == tool_name:
                results.append((fr.response or {}).get("result", ""))
    return results


# ---------------------------------------------------------------------------
# Caso (a): mídia OK no loop principal → pós-tool vazio → retry1 vazio → retry2 devolve
# TEXTO → run_agent retorna o TEXTO (não o fallback de mídia)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_ok_then_empty_retries_then_retry2_text_wins_over_media_fallback():
    """Mídia executa com sucesso no loop principal, mas o turno fica mudo (pós-tool +
    retry1) até o retry2 recuperar texto real. O texto do retry2 deve vencer o fallback
    estático de mídia (_SAFETY_FALLBACK_MEDIA) — o fallback só entra quando TUDO fica
    vazio, e aqui o retry2 recuperou texto de verdade."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_MEDIA

    retry2_text = "consegui recuperar aqui: qual dessas fotos te chamou mais atenção?"
    gen_results = [
        fake_tool_call("enviar_fotos", {"categoria": "atacado"}),  # loop principal: envia fotos
        fake_text(""),           # pós-tool (loop principal): vazio
        fake_text(""),           # retry1: também vazio
        fake_text(retry2_text),  # retry2: recupera texto
    ]

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-composto-001", "phone": "5531900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               return_value="5 fotos de atacado enfileiradas para envio após o texto") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage") as mock_track, \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=gen_results)) as m_gen:
        result = await run_agent(_conversation("atacado"), "manda as fotos")

    assert result == retry2_text, f"esperado o texto do retry2 (vence o fallback), got {result!r}"
    assert result != _SAFETY_FALLBACK_MEDIA
    assert m_gen.await_count == 4, f"esperado 4 chamadas ao LLM, got {m_gen.await_count}"
    assert mock_exec.call_count == 1, "enviar_fotos deve executar UMA vez só (sucesso, sem retry de mídia)"
    call_types = [c.kwargs.get("call_type") for c in mock_track.call_args_list]
    assert call_types == ["response", "response", "response_retry", "response_retry2"], (
        f"ordem de call_types incorreta: {call_types}"
    )


# ---------------------------------------------------------------------------
# Caso (b): guard same-turn dispara (mídia já ok no turno, SEM falha) → continuação
# Change B vazia → retry2 RODA
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_guard_blocks_duplicate_then_change_b_continuation_empty_runs_retry2():
    """Mídia executa OK no loop principal; retry1 recupera a MESMA intenção de mídia
    (thinking-burn) — o guard same-turn bloqueia a 2ª execução (comportamento preexistente,
    sem falha: media_exec_failed nunca vira True aqui). A continuação pós-tool do Change B
    (que processa o result sintético do guard) também vem vazia → retry2 deve RODAR em vez
    de cair direto no fallback estático de mídia."""
    from app.agent.orchestrator import run_agent

    retry2_text = "te mandei as fotos de novo por aqui, alguma te chamou atenção?"
    gen_results = [
        fake_tool_call("enviar_fotos", {"categoria": "atacado"}),  # loop principal: envia fotos
        fake_text(""),                                             # pós-tool (loop principal): vazio
        fake_tool_call("enviar_fotos", {"categoria": "atacado"}),  # retry1: recupera a MESMA intenção
        fake_text(""),                                             # continuação Change B: vazia também
        fake_text(retry2_text),                                    # retry2: recupera texto
    ]

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-composto-001", "phone": "5531900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               return_value="5 fotos de atacado enfileiradas para envio após o texto") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage") as mock_track, \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=gen_results)) as m_gen:
        result = await run_agent(_conversation("atacado"), "manda as fotos")

    assert result == retry2_text, f"esperado o texto do retry2, got {result!r}"
    assert m_gen.await_count == 5, f"esperado 5 chamadas ao LLM, got {m_gen.await_count}"
    assert mock_exec.call_count == 1, (
        f"guard deve bloquear a 2ª execução (sem falha na 1ª); esperado 1 execute_tool, "
        f"got {mock_exec.call_count}"
    )
    call_types = [c.kwargs.get("call_type") for c in mock_track.call_args_list]
    assert call_types == [
        "response", "response", "response_retry", "response_retry", "response_retry2",
    ], f"ordem de call_types incorreta: {call_types}"


# ---------------------------------------------------------------------------
# Caso (c) — NOVO comportamento (RED principal): mídia FALHA no loop principal → retry1
# recupera a MESMA tool → guard NÃO bloqueia (media_exec_failed) → executa de verdade
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_exec_fails_then_retry_recovers_and_guard_does_not_block():
    """execute_tool LEVANTA exceção pra enviar_fotos no loop principal (falha REAL, não
    intenção) — o lead NÃO recebeu as fotos. O retry1 recupera a MESMA tool_call; como a
    execução anterior falhou de fato (media_exec_failed=True), o guard same-turn NÃO deve
    bloquear a re-execução: execute_tool deve ser chamado uma 2ª vez (desta vez com
    sucesso), e o turno deve terminar com o texto natural da continuação — não com o
    result sintético 'não reenviar' do guard."""
    from app.agent.orchestrator import run_agent

    final_text = "consegui te mandar as fotos agora, qual chamou mais atenção?"
    gen_results = [
        fake_tool_call("enviar_fotos", {"categoria": "atacado"}),  # loop principal: tenta enviar fotos
        fake_text(""),                                             # pós-tool (loop principal): vazio
        fake_tool_call("enviar_fotos", {"categoria": "atacado"}),  # retry1: recupera a MESMA tool
        fake_text(final_text),                                     # continuação Change B: texto natural
    ]

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-composto-001", "phone": "5531900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               side_effect=[
                   Exception("falha simulada ao enviar fotos (timeout do provedor)"),
                   "5 fotos de atacado enfileiradas para envio após o texto",
               ]) as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=gen_results)) as m_gen:
        result = await run_agent(_conversation("atacado"), "manda as fotos")

    assert result == final_text, f"esperado o texto final da 2ª execução, got {result!r}"
    assert m_gen.await_count == 4, f"esperado 4 chamadas ao LLM, got {m_gen.await_count}"
    assert mock_exec.call_count == 2, (
        f"guard NÃO deve bloquear a re-execução após falha real; esperado 2 chamadas a "
        f"execute_tool, got {mock_exec.call_count}"
    )
    executed_names = [c.args[0] for c in mock_exec.call_args_list]
    assert executed_names == ["enviar_fotos", "enviar_fotos"]

    # A continuação Change B (4ª chamada) NÃO deve conter o result sintético de bloqueio —
    # prova de que a 2ª tentativa foi executada de verdade, não sintetizada pelo guard.
    # (No protocolo nativo não há tool_call_id: distinguimos as duas execuções pela ORDEM
    # dos function_response de enviar_fotos nos contents.)
    fr_results = _function_response_results(
        m_gen.await_args_list[3].kwargs["contents"], "enviar_fotos"
    )
    assert len(fr_results) == 2, f"esperado 2 tool results de enviar_fotos, got {fr_results}"
    # 1º = falha real do loop principal; 2º = re-execução legítima do retry.
    assert "erro ao executar enviar_fotos" in fr_results[0]
    assert "não reenviar" not in fr_results[1], (
        "o result da 2ª tentativa deve ser o resultado REAL da execução (sucesso), "
        "não o bloqueio sintético do guard"
    )
    assert fr_results[1] == "5 fotos de atacado enfileiradas para envio após o texto"


# ---------------------------------------------------------------------------
# Caso (d) — fast-follow (review desta task): mídia com args de SHAPE INESPERADO no loop
# principal → tool nunca executou → retry1 recupera com args VÁLIDOS → guard NÃO bloqueia
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_malformed_args_then_retry_with_valid_args_executes():
    """No loop principal, enviar_fotos chega com args de shape inesperado (não-dict —
    era `arguments` JSON malformado na era OpenAI; o SDK nativo entrega dict, então o
    assunto migrou para shape inesperado): media_tool_used vira True antes da checagem,
    o ramo de args inválidos anexa o result de erro e dá continue — execute_tool NUNCA
    roda (mesma classe de 'intenção sem execução' do caso (c), só que a falha é no shape,
    não na tool). Quando o retry1 recupera a MESMA tool com args válidos, o guard
    same-turn NÃO deve bloquear: execute_tool deve rodar exatamente 1x (a re-execução
    legítima) e o result real — não o bloqueio sintético 'não reenviar' — deve chegar à
    continuação do Change B."""
    from app.agent.orchestrator import run_agent

    # Args com shape inesperado: fabricamos o GenerateResult e substituímos os args
    # por uma string (não-dict) — o equivalente nativo do JSON truncado de antes.
    bad_result = fake_tool_call("enviar_fotos", {})
    bad_result.function_calls[0].args = '{"categoria": "atacado"'  # não-dict de propósito

    final_text = "te mandei as fotos aqui no chat, qual chamou mais atenção?"
    gen_results = [
        bad_result,                                                # loop principal: args de shape inesperado
        fake_text(""),                                             # pós-tool (loop principal): vazio
        fake_tool_call("enviar_fotos", {"categoria": "atacado"}),  # retry1: MESMA tool, args válidos
        fake_text(final_text),                                     # continuação Change B: texto natural
    ]

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-composto-001", "phone": "5531900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               return_value="5 fotos de atacado enfileiradas para envio após o texto") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=gen_results)) as m_gen:
        result = await run_agent(_conversation("atacado"), "manda as fotos")

    assert result == final_text, f"esperado o texto final da re-execução, got {result!r}"
    assert m_gen.await_count == 4, f"esperado 4 chamadas ao LLM, got {m_gen.await_count}"
    assert mock_exec.call_count == 1, (
        f"a re-execução no retry é a ÚNICA execução do turno (o shape inválido nunca "
        f"chegou a execute_tool); guard não deve bloquear — esperado 1 chamada, "
        f"got {mock_exec.call_count}"
    )
    assert mock_exec.call_args.args[0] == "enviar_fotos"
    assert mock_exec.call_args.args[1] == {"categoria": "atacado"}, (
        "a execução deve usar os args VÁLIDOS recuperados pelo retry"
    )

    # A continuação Change B (4ª chamada) deve receber o result REAL da execução —
    # não o bloqueio sintético do guard nem o erro de args do loop principal. E o result
    # de ERRO de args do loop principal continua registrado nos contents — o contrato do
    # ramo de args inválidos (function_response de erro no histórico do turno) não muda
    # com o fix. Ordem: 1º erro de args, 2º execução real.
    fr_results = _function_response_results(
        m_gen.await_args_list[3].kwargs["contents"], "enviar_fotos"
    )
    assert len(fr_results) == 2, f"esperado 2 tool results de enviar_fotos, got {fr_results}"
    assert "argumentos inválidos" in fr_results[0]
    assert "não reenviar" not in fr_results[1], (
        "guard não deve sintetizar bloqueio: a mídia nunca executou neste turno"
    )
    assert fr_results[1] == "5 fotos de atacado enfileiradas para envio após o texto"
