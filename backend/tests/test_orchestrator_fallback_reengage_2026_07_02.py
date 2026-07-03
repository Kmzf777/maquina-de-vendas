"""Testes TDD para o reengajamento de último recurso por stage ATUAL (Etapa 2, Task 2 —
2026-07-02).

Contexto forense:
  Davi (02/07 15:45): o fallback genérico antigo ("me conta de novo o que você precisa")
  fez o lead redigitar a objeção de preço inteira depois de um turno que ficou vazio em
  TODOS os degraus de retry (initial + retry1 + retry2, todos completion_tokens=0). O texto
  pedia RECALL (repetir o que já foi dito) em vez de AVANÇO — o problema que esta task resolve.

Correção validada aqui:
  _empty_fallback_text ganha o parâmetro `current_stage` e um 3º degrau de prioridade
  (_STAGE_REENGAGE_FALLBACKS) entre mídia e o genérico: quando o turno termina vazio SEM
  transição de stage nem mídia neste turno, mas o lead já está num stage comercial mapeado
  (atacado/private_label/exportacao/consumo), o fallback é uma pergunta de AVANÇO desse
  stage — nunca um pedido de repetição. _SAFETY_FALLBACK_GENERIC (stages não mapeados, ex.
  secretaria) também deixou de pedir repetição.

  Prioridade final: transição de stage > mídia > reengajamento do stage atual > genérico.
  _STAGE_TRANSITION_FALLBACKS (aberturas pós-transição) e _SAFETY_FALLBACK_MEDIA ficam
  INTOCADOS — continuam vencendo o reengajamento por stage quando aplicáveis.

  As exceções de silêncio (soft_reject_used / suppress_generic_fallback) passam a valer
  também para o reengajamento por stage — não só para o genérico — via o novo helper
  _is_last_resort_fallback (ver orchestrator.py). Fallbacks CONTEXTUAIS (mídia/transição)
  continuam vencendo essas exceções, como antes.

Cobertura (Step 1 do brief):
  1. stage atacado, vazio pós-TODOS os retries, sem transição/mídia → texto de
     reengajamento de atacado; NÃO contém "de novo".
  2. stage secretaria (sem entry no dict de reengajamento) → novo genérico; a string antiga
     ("me conta de novo") NÃO aparece.
  3a. transição de stage no turno → _STAGE_TRANSITION_FALLBACKS continua vencendo o
      reengajamento por stage (mesmo quando o stage pós-transição também tem entry em
      _STAGE_REENGAGE_FALLBACKS).
  3b. mídia no turno → _SAFETY_FALLBACK_MEDIA continua vencendo o reengajamento por stage.
  4. soft_reject_used com stage atacado (reengajamento aplicável) → silêncio "".
  5. suppress_generic_fallback com stage atacado (reengajamento aplicável) → silêncio "".

Espelha os helpers de test_orchestrator_retry2_2026_07_02.py (fila: initial vazio + retry1
vazio + retry2 vazio → fallback estático; retry2 é PULADO quando soft_reject_used ou
suppress_generic_fallback já decidiram o destino do turno).
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers (espelham test_orchestrator_retry2_2026_07_02.py)
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, args: dict = None, call_id: str = "tc-001") -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args or {})
    return tc


def _make_response(content: str | None, tool_calls=None, usage: bool = True) -> MagicMock:
    """Constrói uma resposta fake. usage=True (default) garante que track_token_usage seja
    chamado (response.usage truthy), como em test_orchestrator_retry2_2026_07_02.py."""
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    msg.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.choices = [MagicMock(message=msg)]
    resp.usage = MagicMock(prompt_tokens=100, completion_tokens=(20 if content else 0)) if usage else None
    return resp


def _conversation(stage: str = "secretaria") -> dict:
    return {
        "id": "conv-reengage-001",
        "stage": stage,
        "leads": {
            "id": "lead-reengage-001",
            "name": None,
            "phone": "5531900000002",
            "ai_enabled": True,
        },
    }


def _history_one_user_msg(content: str) -> list:
    return [
        {
            "role": "user",
            "content": content,
            "stage": "atacado",
            "created_at": "2026-07-02T16:00:00Z",
            "wamid": "wamid-reengage-01",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]


# ---------------------------------------------------------------------------
# Unit tests for _empty_fallback_text / _is_last_resort_fallback (pure helpers,
# sem mocks — espelha a estratégia de test_post_media_closing.py)
# ---------------------------------------------------------------------------

def test_empty_fallback_text_current_stage_atacado_returns_reengage_text():
    from app.agent.orchestrator import _empty_fallback_text, _STAGE_REENGAGE_FALLBACKS
    result = _empty_fallback_text(media_tool_used=False, transitioned_to_stage=None, current_stage="atacado")
    assert result == _STAGE_REENGAGE_FALLBACKS["atacado"]
    assert "de novo" not in result


def test_empty_fallback_text_transition_wins_over_reengage():
    """Transição de stage neste turno vence o reengajamento do stage atual, mesmo quando
    current_stage aponta pro MESMO stage comercial mapeado em ambos os dicts."""
    from app.agent.orchestrator import _empty_fallback_text, _STAGE_TRANSITION_FALLBACKS
    result = _empty_fallback_text(media_tool_used=False, transitioned_to_stage="atacado", current_stage="atacado")
    assert result == _STAGE_TRANSITION_FALLBACKS["atacado"]


def test_empty_fallback_text_media_wins_over_reengage():
    from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_MEDIA
    result = _empty_fallback_text(media_tool_used=True, transitioned_to_stage=None, current_stage="atacado")
    assert result == _SAFETY_FALLBACK_MEDIA


def test_empty_fallback_text_unmapped_current_stage_returns_generic():
    from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_GENERIC
    result = _empty_fallback_text(media_tool_used=False, transitioned_to_stage=None, current_stage="secretaria")
    assert result == _SAFETY_FALLBACK_GENERIC
    assert "me conta de novo" not in result


def test_is_last_resort_fallback_recognizes_generic_and_stage_reengage():
    from app.agent.orchestrator import (
        _is_last_resort_fallback, _SAFETY_FALLBACK_GENERIC, _STAGE_REENGAGE_FALLBACKS,
        _STAGE_TRANSITION_FALLBACKS, _SAFETY_FALLBACK_MEDIA,
    )
    assert _is_last_resort_fallback(_SAFETY_FALLBACK_GENERIC, None) is True
    assert _is_last_resort_fallback(_SAFETY_FALLBACK_GENERIC, "atacado") is True
    for stage, txt in _STAGE_REENGAGE_FALLBACKS.items():
        assert _is_last_resort_fallback(txt, stage) is True, f"reengajamento de {stage} deveria ser last-resort"
    # Texto de reengajamento de UM stage não bate quando o stage informado é outro (ou None).
    assert _is_last_resort_fallback(_STAGE_REENGAGE_FALLBACKS["atacado"], "consumo") is False
    assert _is_last_resort_fallback(_STAGE_REENGAGE_FALLBACKS["atacado"], None) is False
    # Fallbacks CONTEXTUAIS (transição, mídia) NUNCA são "último recurso".
    assert _is_last_resort_fallback(_STAGE_TRANSITION_FALLBACKS["atacado"], "atacado") is False
    assert _is_last_resort_fallback(_SAFETY_FALLBACK_MEDIA, "atacado") is False


def test_all_commercial_stages_have_reengage_fallback():
    from app.agent.orchestrator import _STAGE_REENGAGE_FALLBACKS
    for stage in ("atacado", "private_label", "exportacao", "consumo"):
        assert stage in _STAGE_REENGAGE_FALLBACKS, f"missing reengage fallback for {stage}"
        assert _STAGE_REENGAGE_FALLBACKS[stage].strip()
    msgs = list(_STAGE_REENGAGE_FALLBACKS.values())
    assert len(set(msgs)) == len(msgs), "stage reengage messages must be distinct"


def test_voice_rules_stage_reengage_fallbacks():
    """_STAGE_REENGAGE_FALLBACKS: minúsculas, sem ponto final, máx 2 bolhas, exatamente 1
    pergunta de avanço, sem pedir repetição (voz da Valéria)."""
    from app.agent.orchestrator import _STAGE_REENGAGE_FALLBACKS
    for stage, txt in _STAGE_REENGAGE_FALLBACKS.items():
        assert txt == txt.lower(), f"[{stage}] texto deve ser minúsculo: {txt!r}"
        assert not txt.rstrip().endswith("."), f"[{stage}] sem ponto final: {txt!r}"
        assert ". " not in txt, f"[{stage}] sem ponto de sentença: {txt!r}"
        assert txt.count("\n\n") <= 1, f"[{stage}] máx 2 bolhas: {txt!r}"
        assert txt.count("?") == 1, f"[{stage}] exatamente 1 pergunta: {txt!r}"
        assert "de novo" not in txt, f"[{stage}] não pode pedir repetição: {txt!r}"
        assert "repet" not in txt, f"[{stage}] não pode pedir repetição: {txt!r}"


def test_voice_rules_new_generic_fallback():
    """_SAFETY_FALLBACK_GENERIC (Etapa 2): minúsculas, sem ponto final, máx 2 bolhas, sem
    pedir repetição e sem afirmar que a mensagem chegou cortada. Texto verbatim do brief —
    convite de avanço, não necessariamente formulado como pergunta."""
    from app.agent.orchestrator import _SAFETY_FALLBACK_GENERIC
    txt = _SAFETY_FALLBACK_GENERIC
    assert txt == txt.lower()
    assert not txt.rstrip().endswith(".")
    assert ". " not in txt
    assert txt.count("\n\n") <= 1
    assert "de novo" not in txt
    assert "repet" not in txt
    assert "cortada" not in txt


# ---------------------------------------------------------------------------
# Caso 1: stage atacado, vazio pós-TODOS os retries (initial+retry1+retry2), sem
# transição/mídia → reengajamento de atacado
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case1_stage_atacado_empty_after_all_retries_uses_reengage_fallback():
    from app.agent.orchestrator import run_agent, _STAGE_REENGAGE_FALLBACKS

    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        return _make_response(content="", tool_calls=None)  # initial + retry1 + retry2, todos vazios

    with patch("app.agent.orchestrator.get_history",
               return_value=_history_one_user_msg("quanto custa o café em volume?")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-reengage-001", "phone": "5531900000002", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("atacado"), "quanto custa o café em volume?")

    assert result == _STAGE_REENGAGE_FALLBACKS["atacado"], f"esperado reengajamento de atacado, got {result!r}"
    assert "de novo" not in result
    assert n["i"] == 3, f"esperado 3 chamadas (inicial+retry1+retry2), got {n['i']}"


# ---------------------------------------------------------------------------
# Caso 2: stage secretaria (sem entry) → novo genérico, sem a string antiga
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case2_stage_secretaria_empty_after_all_retries_uses_new_generic():
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        return _make_response(content="", tool_calls=None)

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg("oi, tudo bem?")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-reengage-001", "phone": "5531900000002", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "oi, tudo bem?")

    assert result == _SAFETY_FALLBACK_GENERIC, f"esperado o genérico novo, got {result!r}"
    assert "me conta de novo" not in result
    assert n["i"] == 3, f"esperado 3 chamadas (inicial+retry1+retry2), got {n['i']}"


# ---------------------------------------------------------------------------
# Caso 3a: transição de stage no turno → _STAGE_TRANSITION_FALLBACKS continua vencendo
# o reengajamento por stage, mesmo quando o stage pós-transição também tem entry em
# _STAGE_REENGAGE_FALLBACKS.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case3a_stage_transition_still_wins_over_reengage():
    from app.agent.orchestrator import run_agent, _STAGE_TRANSITION_FALLBACKS

    tool_call = _make_tool_call("mudar_stage", {"stage": "atacado"}, "tc-transition-001")
    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        if n["i"] == 1:
            return _make_response(content=None, tool_calls=[tool_call])  # mudar_stage → atacado
        return _make_response(content="", tool_calls=None)  # pós-tool + retry1 + retry2, vazios

    with patch("app.agent.orchestrator.get_history",
               return_value=_history_one_user_msg("tenho uma cafeteria, quero revender")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-reengage-001", "phone": "5531900000002", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.update_lead", new=MagicMock()), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="Stage alterado para: atacado"), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("secretaria"), "tenho uma cafeteria, quero revender")

    assert result == _STAGE_TRANSITION_FALLBACKS["atacado"], (
        f"transição deve vencer o reengajamento por stage, got {result!r}"
    )
    assert n["i"] == 4, f"esperado 4 chamadas (tool+pos-tool+retry1+retry2), got {n['i']}"


# ---------------------------------------------------------------------------
# Caso 3b: mídia no turno → _SAFETY_FALLBACK_MEDIA continua vencendo o reengajamento por
# stage (stage já é atacado desde o início do turno, sem transição).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case3b_media_still_wins_over_reengage():
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_MEDIA

    tool_call = _make_tool_call("enviar_fotos", {}, "tc-media-001")
    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        if n["i"] == 1:
            return _make_response(content=None, tool_calls=[tool_call])  # enviar_fotos
        return _make_response(content="", tool_calls=None)  # pós-tool + retry1 + retry2, vazios

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg("me manda fotos")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-reengage-001", "phone": "5531900000002", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="fotos enfileiradas para envio após o texto"), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("atacado"), "me manda fotos")

    assert result == _SAFETY_FALLBACK_MEDIA, f"mídia deve vencer o reengajamento por stage, got {result!r}"
    assert n["i"] == 4, f"esperado 4 chamadas (tool+pos-tool+retry1+retry2), got {n['i']}"


# ---------------------------------------------------------------------------
# Caso 4: soft_reject_used com stage atacado (reengajamento aplicável) → silêncio ""
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case4_soft_reject_used_with_reengage_eligible_stage_returns_empty():
    """Espelha test_soft_reject_used_skips_retry2_returns_empty (retry2 file), mas com stage
    atacado — sem o novo helper _is_last_resort_fallback, o texto de reengajamento de
    atacado NÃO bateria na comparação antiga (== _SAFETY_FALLBACK_GENERIC) e vazaria pro
    lead recém-descartado. A exceção de silêncio precisa vencer também aqui."""
    from app.agent.orchestrator import run_agent

    sem_int_tc = _make_tool_call(
        "registrar_sem_interesse_atual", {"motivo": "achou caro"}, "tc-semint-reengage"
    )
    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        if n["i"] == 1:
            return _make_response(content=None, tool_calls=[sem_int_tc])  # loop principal: descarte
        return _make_response(content="", tool_calls=None)  # pós-tool (2) e retry1 (3): mudos

    with patch("app.agent.orchestrator.get_history",
               return_value=_history_one_user_msg("é caro demais, não quero mais")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-reengage-001", "phone": "5531900000002", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="descarte registrado") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage") as mock_track, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation("atacado"), "é caro demais, não quero mais")

    assert result == "", (
        f"esperado silêncio após soft rejection mesmo com reengajamento de stage aplicável, got {result!r}"
    )
    assert n["i"] == 3, f"retry2 NÃO deve ser chamado após soft_reject_used; esperado 3, got {n['i']}"
    assert mock_exec.called and mock_exec.call_args.args[0] == "registrar_sem_interesse_atual"
    call_types = [c.kwargs.get("call_type") for c in mock_track.call_args_list]
    assert "response_retry2" not in call_types, f"retry2 não deveria ter registrado uso: {call_types}"


# ---------------------------------------------------------------------------
# Caso 5: suppress_generic_fallback com stage atacado (reengajamento aplicável) → silêncio ""
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case5_suppress_generic_fallback_with_reengage_eligible_stage_returns_empty():
    """Gatilho interno (ex.: reabertura proativa ai_scheduled_return) sem mensagem real do
    lead, mas em stage atacado (reengajamento aplicável) → ainda assim silêncio "": a
    exceção de silêncio cobre o reengajamento por stage, não só o genérico."""
    from app.agent.orchestrator import run_agent

    n = {"i": 0}

    async def fake_create(**kwargs):
        n["i"] += 1
        return _make_response(content="", tool_calls=None)

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg("[GATILHO INTERNO]")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-reengage-001", "phone": "5531900000002", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage") as mock_track, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(
            _conversation("atacado"), "[GATILHO INTERNO]",
            suppress_generic_fallback=True,
        )

    assert result == "", f"esperado '', got {result!r}"
    assert n["i"] == 2, f"retry2 NÃO deve ser chamado com suppress_generic_fallback=True; esperado 2, got {n['i']}"
    call_types = [c.kwargs.get("call_type") for c in mock_track.call_args_list]
    assert "response_retry2" not in call_types, f"retry2 não deveria ter registrado uso: {call_types}"
