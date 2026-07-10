"""QA conversacional da run "DSP 10-07-26 10-57" (auditoria 10/07 — caso Marisete).

Dois desvios encontrados na transcrição real:

1. SUPER-NOMEAÇÃO: a Valéria abriu 3 turnos consecutivos com o vocativo "Marisete"
   ("boa, Marisete" → "que legal, Marisete" → "vale a pena conhecer, Marisete, ...")
   violando a regra explícita do prompt (base.py: "Nunca repita o nome do lead em
   mensagens consecutivas — padrão de telemarketing") e o item 13 do checklist.
   O prompt sozinho não segurou → guarda determinística `strip_consecutive_vocative_name`
   em app.agent.adherence, no mesmo padrão dos guards de 04-08/07.

2. mudar_stage SEM IDEMPOTÊNCIA: o modelo re-chamou a tool com o stage ATUAL
   ('consumo' → 'consumo') e o marcador "stage alterado para: consumo" saiu DUPLICADO
   na transcrição (que realimenta o prompt), além de writes redundantes. Guard: quando
   lead E conversa já estão no stage pedido, a tool vira no-op informativo. Divergência
   entre lead.stage e conversation.stage ainda re-sincroniza (não é no-op).
"""

from unittest.mock import MagicMock, patch

import pytest

from app.agent.adherence import strip_consecutive_vocative_name


# ─── 1. strip_consecutive_vocative_name ──────────────────────────────────────

_PRIOR_WITH_NAME = ["que legal, Marisete", "café especial no dia a dia faz toda a diferença"]
_PRIOR_WITHOUT_NAME = ["vale a pena conhecer", "qualquer dúvida me chama"]


def test_vocative_stripped_when_name_used_in_previous_turn():
    """Vocativo ', Nome' no fim do trecho cai quando o turno anterior já nomeou."""
    out = strip_consecutive_vocative_name(
        "vale a pena conhecer, Marisete, vou te passar um cupom de 10%",
        "Marisete", _PRIOR_WITH_NAME,
    )
    assert "Marisete" not in out
    assert "vale a pena conhecer" in out
    assert "cupom de 10%" in out


def test_vocative_at_end_of_text_stripped():
    out = strip_consecutive_vocative_name("que legal, Marisete", "Marisete", ["boa, Marisete"])
    assert out == "que legal"


def test_vocative_opening_line_stripped():
    out = strip_consecutive_vocative_name(
        "Marisete, o cupom vale pra toda a loja", "Marisete", _PRIOR_WITH_NAME,
    )
    assert "Marisete" not in out
    assert "o cupom vale pra toda a loja" in out


def test_name_kept_when_previous_turn_did_not_use_it():
    text = "que legal, Marisete"
    assert strip_consecutive_vocative_name(text, "Marisete", _PRIOR_WITHOUT_NAME) == text


def test_semantic_use_of_name_is_never_touched():
    """Uso semântico (não-vocativo) do nome não casa com os padrões de vocativo."""
    text = "o pedido da Marisete chegou na loja"
    assert strip_consecutive_vocative_name(text, "Marisete", _PRIOR_WITH_NAME) == text


def test_no_lead_name_is_noop():
    text = "que legal, Marisete"
    assert strip_consecutive_vocative_name(text, None, _PRIOR_WITH_NAME) == text
    assert strip_consecutive_vocative_name(text, "  ", _PRIOR_WITH_NAME) == text


def test_short_names_are_skipped_to_avoid_collisions():
    """Nomes de 1-2 letras colidem com palavras comuns — guard não atua."""
    text = "boa, Ed"
    assert strip_consecutive_vocative_name(text, "Ed", ["oi, Ed"]) == text


def test_accented_name_matches_case_insensitively():
    out = strip_consecutive_vocative_name("boa, josé, fechou então", "José Carlos", ["oi, José"])
    assert "josé" not in out.lower()
    assert "fechou então" in out


def test_result_never_empties_fail_open():
    """Se o strip esvaziar o texto, devolve o original (nunca fantasmar o lead)."""
    out = strip_consecutive_vocative_name("Marisete", "Marisete", _PRIOR_WITH_NAME)
    assert out == "Marisete"


# ─── 2. mudar_stage idempotente ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mudar_stage_same_stage_is_informative_noop():
    """lead E conversa já no stage pedido → sem writes, sem marcador duplicado."""
    from app.agent import tools as t
    with patch.object(t, "get_lead", return_value={"id": "L1", "stage": "consumo"}), \
         patch.object(t, "get_conversation", return_value={"id": "C1", "stage": "consumo"}), \
         patch.object(t, "update_conversation") as up_conv, \
         patch.object(t, "update_lead") as up_lead, \
         patch.object(t, "ensure_segment_deal") as ensure, \
         patch.object(t, "save_message") as save:
        result = await t.execute_tool("mudar_stage", {"stage": "consumo"}, "L1", "5511999999999", "C1")

    assert not up_conv.called
    assert not up_lead.called
    assert not ensure.called
    assert not save.called, "marcador 'stage alterado' duplicado polui a transcrição"
    assert "consumo" in result and "já" in result.lower()


@pytest.mark.asyncio
async def test_mudar_stage_divergent_conversation_still_resyncs():
    """lead já no stage mas conversa divergente → NÃO é no-op (re-sincroniza)."""
    from app.agent import tools as t
    with patch.object(t, "get_lead", return_value={"id": "L1", "stage": "consumo"}), \
         patch.object(t, "get_conversation", return_value={"id": "C1", "stage": "secretaria"}), \
         patch.object(t, "update_conversation") as up_conv, \
         patch.object(t, "update_lead") as up_lead, \
         patch.object(t, "ensure_segment_deal"), \
         patch.object(t, "save_message") as save:
        result = await t.execute_tool("mudar_stage", {"stage": "consumo"}, "L1", "5511999999999", "C1")

    assert up_conv.called and up_lead.called and save.called
    assert result == "Stage alterado para: consumo"


@pytest.mark.asyncio
async def test_mudar_stage_normal_transition_unchanged():
    """Transição real (secretaria → consumo) segue o caminho completo."""
    from app.agent import tools as t
    with patch.object(t, "get_lead", return_value={"id": "L1", "stage": "secretaria"}), \
         patch.object(t, "get_conversation", return_value={"id": "C1", "stage": "secretaria"}), \
         patch.object(t, "update_conversation") as up_conv, \
         patch.object(t, "update_lead") as up_lead, \
         patch.object(t, "ensure_segment_deal") as ensure, \
         patch.object(t, "save_message") as save:
        result = await t.execute_tool("mudar_stage", {"stage": "consumo"}, "L1", "5511999999999", "C1")

    assert up_conv.called and up_lead.called and ensure.called and save.called
    assert result == "Stage alterado para: consumo"


@pytest.mark.asyncio
async def test_mudar_stage_guard_fails_open_on_fetch_error():
    """Se o fetch do estado atual falhar, o caminho normal roda (fail-open)."""
    from app.agent import tools as t
    with patch.object(t, "get_lead", side_effect=RuntimeError("db down")), \
         patch.object(t, "get_conversation", side_effect=RuntimeError("db down")), \
         patch.object(t, "update_conversation") as up_conv, \
         patch.object(t, "update_lead") as up_lead, \
         patch.object(t, "ensure_segment_deal"), \
         patch.object(t, "save_message") as save:
        result = await t.execute_tool("mudar_stage", {"stage": "consumo"}, "L1", "5511999999999", "C1")

    assert up_conv.called and up_lead.called and save.called
    assert result == "Stage alterado para: consumo"
