"""Testes do épico 'Plano de Perfeição Outbound' (2026-06-22).

Cobre as três frentes:
  C — Objeção LGPD "onde pegou meu número" (prompt secretaria + reforço base)
  A — Personalização por DDD (helper ddd_to_region, plumbing, render base, segmento)
  B — Follow-up de vácuo/ghosting (gatilho engajou-e-esfriou, voz persona, clamp horário)
"""
from datetime import datetime, timezone, timedelta

TZ_BR = timezone(timedelta(hours=-3))


def _now():
    return datetime.now(TZ_BR)


# ===========================================================================
# Épico C — Objeção LGPD "onde pegou meu número"
# ===========================================================================

def test_secretaria_outbound_trata_objecao_origem_numero():
    """A secretaria outbound deve ter roteiro explícito para 'onde pegou meu número'."""
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT
    low = SECRETARIA_PROMPT.lower()
    assert "onde" in low and "numero" in low and (
        "pegou meu numero" in low or "conseguiu meu" in low or "meu contato" in low
    ), "secretaria outbound não trata a objeção de origem do número (LGPD)"


def test_secretaria_outbound_objecao_origem_abre_porta_de_saida():
    """O roteiro LGPD deve oferecer remoção imediata (porta de saída) e citar opt-out."""
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT
    low = SECRETARIA_PROMPT.lower()
    assert "removo" in low or "remover" in low or "tiro" in low or "te tiro" in low, (
        "roteiro LGPD não oferece porta de saída (remoção imediata)"
    )
    assert "registrar_optout" in SECRETARIA_PROMPT, (
        "roteiro LGPD não aciona registrar_optout quando o lead pede remoção"
    )


def test_base_prompt_nao_inventar_origem_numero():
    """O base deve proibir inventar de onde veio o número do lead."""
    from app.agent.prompts.base import build_base_prompt
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    low = prompt.lower()
    assert "origem do numero" in low or "origem do número" in low, (
        "base não menciona a objeção de origem do número"
    )
    # Proibição explícita de inventar a origem do número
    assert ("nunca invente" in low or "nao invente" in low or "não invente" in low), (
        "base não proíbe inventar a origem do número"
    )


# ===========================================================================
# Épico A — Personalização por DDD
# ===========================================================================

def test_ddd_to_region_minas():
    from app.utils.geo import ddd_to_region
    assert ddd_to_region("5531999990000") == "Minas Gerais"
    assert ddd_to_region("5534988887777") == "Minas Gerais"


def test_ddd_to_region_sao_paulo():
    from app.utils.geo import ddd_to_region
    assert ddd_to_region("5511999990000") == "São Paulo"
    assert ddd_to_region("5519999990000") == "São Paulo"


def test_ddd_to_region_rio():
    from app.utils.geo import ddd_to_region
    assert ddd_to_region("5521999990000") == "Rio de Janeiro"


def test_ddd_to_region_brasilia():
    from app.utils.geo import ddd_to_region
    assert ddd_to_region("5561999990000") == "Distrito Federal"


def test_ddd_to_region_sem_55():
    """Número já sem o código do país (11 dígitos) também resolve pelo DDD inicial."""
    from app.utils.geo import ddd_to_region
    assert ddd_to_region("31999990000") == "Minas Gerais"


def test_ddd_to_region_ddd_desconhecido():
    from app.utils.geo import ddd_to_region
    assert ddd_to_region("5500999990000") is None


def test_ddd_to_region_internacional_ou_curto():
    from app.utils.geo import ddd_to_region
    assert ddd_to_region("12025550123") is None  # +1 US
    assert ddd_to_region("123") is None
    assert ddd_to_region("") is None
    assert ddd_to_region(None) is None


def test_ddd_to_region_com_simbolos():
    """Deve tolerar '+', espaços e parênteses."""
    from app.utils.geo import ddd_to_region
    assert ddd_to_region("+55 (31) 99999-0000") == "Minas Gerais"


def test_base_prompt_renderiza_regiao_como_hipotese():
    """Quando lead_context tem lead_region, o base injeta como hipótese (não afirmação)."""
    from app.agent.prompts.base import build_base_prompt
    ctx = {"lead_region": "Minas Gerais"}
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now(), lead_context=ctx)
    assert "Minas Gerais" in prompt
    low = prompt.lower()
    assert "ddd" in low, "render de região não menciona que veio do DDD"
    # Deve instruir uso cauteloso, nunca afirmação categórica
    assert "nao confirmad" in low or "não confirmad" in low or "hipotese" in low or "hipótese" in low or "nunca afirme" in low, (
        "render de região não instrui uso cauteloso/não-categórico"
    )


def test_base_prompt_sem_regiao_nao_renderiza_bloco():
    """Sem lead_region, não deve aparecer menção a DDD."""
    from app.agent.prompts.base import build_base_prompt
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert "derivada do DDD" not in prompt


def test_context_builder_injeta_campaign_segment():
    """build_outbound_first_turn_context deve injetar o segmento da campanha como hipótese."""
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context
    result = build_outbound_first_turn_context(
        campaign_message="Template.",
        lead_name="Joao",
        campaign_segment="atacado",
    )
    assert "atacado" in result.lower()
    assert "hipotese" in result.lower() or "hipótese" in result.lower()


def test_context_builder_sem_segment_nao_quebra():
    """Sem campaign_segment, mantém compatibilidade (não menciona segmento)."""
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context
    result = build_outbound_first_turn_context(
        campaign_message="Template.",
        lead_name="Joao",
    )
    assert "Template." in result
    assert "segmento" not in result.lower()


import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_processor_plumba_regiao_e_company():
    """O processor deve injetar lead_region (via DDD) e company no lead_context."""
    from app.buffer.processor import process_buffered_messages

    lead_data = {
        "id": "lead-mg", "phone": "5531999990000", "company": "Hotel Serra",
        "stage": "secretaria", "status": "active", "human_control": False,
        "metadata": {"previous_stage": "secretaria"},
    }
    conv_data = {
        "id": "conv-mg", "stage": "secretaria", "status": "active",
        "ai_enabled": True, "agent_profile_id": None,
    }
    captured = {}

    async def fake_run_agent(conv, text, lead_context=None, agent_profile_id=None):
        captured["lead_context"] = lead_context
        return "resposta"

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead_data), \
         patch("app.buffer.processor.get_channel_by_id", return_value={"id": "ch", "agent_profiles": None}), \
         patch("app.buffer.processor.get_provider") as mock_prov, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conv_data), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message", return_value={}), \
         patch("app.buffer.processor.get_supabase") as mock_sb, \
         patch("app.buffer.processor.run_agent", side_effect=fake_run_agent), \
         patch("app.buffer.processor._resolve_media", new=AsyncMock(side_effect=lambda t, p: t)), \
         patch("app.buffer.processor.split_into_bubbles", return_value=["resposta"]):
        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_prov.return_value.send_text = AsyncMock()
        await process_buffered_messages("+5531999990000", "oi", channel_id="ch")

    ctx = captured.get("lead_context") or {}
    assert ctx.get("lead_region") == "Minas Gerais", f"esperava lead_region MG, recebeu {ctx}"
    assert ctx.get("company") == "Hotel Serra", f"esperava company, recebeu {ctx}"
    assert ctx.get("previous_stage") == "secretaria", "metadata original deve ser preservado"


@pytest.mark.asyncio
async def test_orchestrator_injeta_campaign_segment_no_primeiro_turno():
    """run_agent outbound deve repassar campaign_segment do lead_context ao contexto de 1º turno."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-seg", "stage": "secretaria",
        "leads": {"id": "lead-seg", "name": "Ana", "phone": "5531900000001"},
    }
    lead_context = {"campaign_message": "Ola, aqui e a Valeria.", "campaign_segment": "atacado"}

    def _resp():
        msg = MagicMock(); msg.tool_calls = None; msg.content = "ok"
        r = MagicMock(); r.choices = [MagicMock(message=msg)]; r.usage = None
        return r
    create_mock = AsyncMock(return_value=_resp())

    with patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-seg", "name": "Ana", "phone": "5531900000001", "ai_enabled": True}), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_outbound", "model": "gpt-4.1-mini"}), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = create_mock
        await run_agent(conversation, "sim", lead_context=lead_context, agent_profile_id="p")

    messages = create_mock.call_args_list[0].kwargs["messages"]
    assert "atacado" in messages[1]["content"].lower(), "segmento da campanha não foi injetado no 1º turno"
