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


def test_secretaria_lgpd_vocabulario_natural():
    """Humanização: a objeção LGPD não pode usar 'base comercial de cadastros' (frio/jurídico)."""
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT
    assert "base comercial de cadastros" not in SECRETARIA_PROMPT, (
        "vocabulário corporativo 'base comercial de cadastros' ainda presente na secretaria"
    )
    low = SECRETARIA_PROMPT.lower()
    assert "lista de contatos" in low or "cadastro aqui com a gente" in low or "nossa lista" in low, (
        "secretaria não usa vocabulário SDR natural para a origem do número"
    )
    # Porta de saída deve permanecer
    assert "registrar_optout" in SECRETARIA_PROMPT


def test_base_lgpd_vocabulario_natural():
    """O reforço de origem no base também deve usar vocabulário natural."""
    from app.agent.prompts.base import build_base_prompt
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    normalized = " ".join(prompt.split())  # colapsa quebras de linha do prompt
    assert "base comercial de cadastros" not in normalized, (
        "vocabulário corporativo 'base comercial de cadastros' ainda presente no base"
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


def test_base_prompt_regiao_sem_frase_robotica():
    """Humanização: a Valéria NÃO pode dizer 'DDD' ao lead (tell de robô)."""
    from app.agent.prompts.base import build_base_prompt
    ctx = {"lead_region": "Minas Gerais"}
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now(), lead_context=ctx)
    assert "seu DDD é de" not in prompt, "exemplo robótico 'seu DDD é de' ainda presente"
    assert "seu DDD" not in prompt.split("Exemplos CORRETOS")[0] or "pelo número" in prompt, (
        "render de região deve usar abordagem orgânica ('pelo número...')"
    )
    # Abordagem orgânica esperada
    assert "pelo número" in prompt or "o pessoal de" in prompt, (
        "render de região não usa abordagem casual/orgânica"
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


# ===========================================================================
# Épico B — Follow-up de vácuo/ghosting
# ===========================================================================

def _b_patches(lead, conv, schedule_mock, ai_enabled=True):
    """Conjunto comum de patches para exercitar o bloco de agendamento do processor."""
    return [
        patch("app.buffer.processor.get_or_create_lead", return_value=lead),
        patch("app.buffer.processor.get_channel_by_id", return_value={"id": "ch", "agent_profiles": None}),
        patch("app.buffer.processor.get_provider"),
        patch("app.buffer.processor.get_or_create_conversation", return_value=conv),
        patch("app.buffer.processor._is_recent_duplicate", return_value=False),
        patch("app.buffer.processor.get_active_enrollment", return_value=None),
        patch("app.buffer.processor.save_message", return_value={}),
        patch("app.buffer.processor.get_supabase", new=MagicMock()),
        patch("app.buffer.processor.run_agent", new=AsyncMock(return_value="resposta")),
        patch("app.buffer.processor._resolve_media", new=AsyncMock(side_effect=lambda t, p: t)),
        patch("app.buffer.processor.split_into_bubbles", return_value=["resposta"]),
        patch("app.buffer.processor.get_lead", return_value={"id": lead["id"], "ai_enabled": ai_enabled}),
        patch("app.buffer.processor._schedule_followup", new=schedule_mock),
    ]


@pytest.mark.asyncio
async def test_b1_outbound_engajou_e_esfriou_agenda_followup():
    """Outbound: lead respondeu e não há interesse explícito → agenda follow-up mesmo assim."""
    from app.buffer.processor import process_buffered_messages
    lead = {"id": "lead-o", "phone": "5531999990000", "stage": "secretaria",
            "status": "active", "human_control": False, "metadata": {}}
    conv = {"id": "conv-o", "stage": "secretaria", "status": "active",
            "ai_enabled": True, "agent_profile_id": "p-out", "followup_enabled": True}
    schedule_mock = MagicMock()

    import contextlib
    with contextlib.ExitStack() as stack:
        for p in _b_patches(lead, conv, schedule_mock):
            stack.enter_context(p)
        stack.enter_context(patch("app.buffer.processor.resolve_prompt_key", return_value="valeria_outbound"))
        prov = stack.enter_context(patch("app.buffer.processor.get_provider"))
        prov.return_value.send_text = AsyncMock()
        await process_buffered_messages("+5531999990000", "oi", channel_id="ch")

    assert schedule_mock.called, "follow-up deveria ser agendado para outbound que engajou e esfriou"


@pytest.mark.asyncio
async def test_b1_outbound_optout_nao_agenda():
    """Outbound mas IA foi desativada no turno (opt-out/soft) → NÃO agenda follow-up."""
    from app.buffer.processor import process_buffered_messages
    lead = {"id": "lead-opt", "phone": "5531999990000", "stage": "secretaria",
            "status": "active", "human_control": False, "metadata": {}}
    conv = {"id": "conv-opt", "stage": "secretaria", "status": "active",
            "ai_enabled": True, "agent_profile_id": "p-out", "followup_enabled": True}
    schedule_mock = MagicMock()

    import contextlib
    with contextlib.ExitStack() as stack:
        for p in _b_patches(lead, conv, schedule_mock, ai_enabled=False):
            stack.enter_context(p)
        stack.enter_context(patch("app.buffer.processor.resolve_prompt_key", return_value="valeria_outbound"))
        prov = stack.enter_context(patch("app.buffer.processor.get_provider"))
        prov.return_value.send_text = AsyncMock()
        await process_buffered_messages("+5531999990000", "nao quero mais contato", channel_id="ch")

    assert not schedule_mock.called, "não deveria agendar follow-up quando a IA foi desativada (opt-out)"


@pytest.mark.asyncio
async def test_b1_inbound_sem_interesse_nao_agenda():
    """Inbound sem interesse mantém comportamento antigo: não agenda."""
    from app.buffer.processor import process_buffered_messages
    lead = {"id": "lead-in", "phone": "5531999990000", "stage": "secretaria",
            "status": "active", "human_control": False, "metadata": {}}
    conv = {"id": "conv-in", "stage": "secretaria", "status": "active",
            "ai_enabled": True, "agent_profile_id": None, "followup_enabled": True}
    schedule_mock = MagicMock()

    import contextlib
    with contextlib.ExitStack() as stack:
        for p in _b_patches(lead, conv, schedule_mock):
            stack.enter_context(p)
        stack.enter_context(patch("app.buffer.processor.resolve_prompt_key", return_value="valeria_inbound"))
        prov = stack.enter_context(patch("app.buffer.processor.get_provider"))
        prov.return_value.send_text = AsyncMock()
        await process_buffered_messages("+5531999990000", "oi", channel_id="ch")

    assert not schedule_mock.called, "inbound sem interesse não deve agendar follow-up"


def test_b2_followup_system_prompt_usa_persona_valeria():
    """O system prompt do follow-up deve carregar a persona Valéria, não um prompt genérico."""
    from app.follow_up.scheduler import _build_followup_system_prompt
    sp_seq1 = _build_followup_system_prompt(1)
    assert "Valeria" in sp_seq1 or "Valéria" in sp_seq1
    assert "Cafe Canastra" in sp_seq1 or "Café Canastra" in sp_seq1
    # Regras de voz que o prompt genérico antigo não tinha
    low = sp_seq1.lower()
    assert "ponto final" in low or "fragment" in low, "system prompt do follow-up não carrega as regras de voz"
    # A diferenciação por sequência deve permanecer
    sp_seq2 = _build_followup_system_prompt(2)
    assert sp_seq1 != sp_seq2, "instrução de sequência (1 vs 2) deve diferir"


def test_b3_schedule_followup_clampa_janela_comercial():
    """Os jobs seq=1 e seq=2 devem ter fire_at dentro da janela comercial (nunca de madrugada)."""
    from app.follow_up import service
    from app.follow_up.service import is_within_business_window
    from datetime import datetime, timezone

    captured = {}
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"id": "conv"}])

    def _insert(jobs):
        captured["jobs"] = jobs
        return MagicMock(execute=MagicMock())
    sb.table.return_value.insert.side_effect = _insert

    with patch.object(service, "get_supabase", return_value=sb):
        service.schedule_followup("conv", "lead", "ch")

    jobs = captured.get("jobs")
    assert jobs and len(jobs) == 2, f"esperava 2 jobs, recebeu {jobs}"
    for job in jobs:
        fire_at = datetime.fromisoformat(job["fire_at"])
        assert is_within_business_window(fire_at), (
            f"fire_at {job['fire_at']} (seq={job['sequence']}) caiu fora da janela comercial"
        )


# ===========================================================================
# Épico A4 — Hook do dispatcher: persistir campaign_segment no metadata
# ===========================================================================

def test_pipeline_name_to_segment():
    from app.broadcast.worker import _pipeline_name_to_segment
    assert _pipeline_name_to_segment("Valeria - Atacado") == "atacado"
    assert _pipeline_name_to_segment("João - Atacado") == "atacado"
    assert _pipeline_name_to_segment("Valeria - Private Label") == "private_label"
    assert _pipeline_name_to_segment("Arthur - Exportação") == "exportacao"
    assert _pipeline_name_to_segment("Valeria - Consumo") == "consumo"


def test_pipeline_name_to_segment_desconhecido():
    from app.broadcast.worker import _pipeline_name_to_segment
    assert _pipeline_name_to_segment("Valeria - Importação Leads Frios") is None
    assert _pipeline_name_to_segment("João - Recuperação") is None
    assert _pipeline_name_to_segment("") is None
    assert _pipeline_name_to_segment(None) is None


def test_build_lead_updates_com_segmento_persiste_metadata():
    from app.broadcast.worker import _build_lead_updates
    broadcast = {"agent_profile_id": "ap-out"}
    channel = {"id": "ch", "mode": "ai"}
    lead = {"id": "l1", "metadata": {"previous_stage": "secretaria"}}
    updates = _build_lead_updates(broadcast, channel, lead, campaign_segment="atacado")
    assert updates["ai_enabled"] is True
    assert updates["human_control"] is False
    # metadata original preservado + campaign_segment adicionado
    assert updates["metadata"]["campaign_segment"] == "atacado"
    assert updates["metadata"]["previous_stage"] == "secretaria"


def test_build_lead_updates_sem_segmento_nao_toca_metadata():
    from app.broadcast.worker import _build_lead_updates
    broadcast = {"agent_profile_id": "ap-out"}
    channel = {"id": "ch", "mode": "ai"}
    lead = {"id": "l1", "metadata": {"x": 1}}
    updates = _build_lead_updates(broadcast, channel, lead, campaign_segment=None)
    assert "metadata" not in updates, "sem segmento, não deve sobrescrever metadata do lead"
    assert updates["ai_enabled"] is True


def test_build_lead_updates_canal_humano_ai_desligada():
    from app.broadcast.worker import _build_lead_updates
    broadcast = {"agent_profile_id": "ap-out"}
    channel = {"id": "ch", "mode": "human"}
    lead = {"id": "l1", "metadata": None}
    updates = _build_lead_updates(broadcast, channel, lead, campaign_segment="atacado")
    assert updates["ai_enabled"] is False
    # mesmo em canal humano, o segmento é registrado para inteligência futura
    assert updates["metadata"]["campaign_segment"] == "atacado"
