import pytest


# ---------------------------------------------------------------------------
# Task 1 — build_outbound_first_turn_context
# ---------------------------------------------------------------------------

def test_context_builder_com_nome_e_campanha():
    """Deve incluir campaign_message, nome do lead e o frame de PRIMEIRO turno outbound."""
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context

    result = build_outbound_first_turn_context(
        campaign_message="Ola, aqui e a Valeria da Cafe Canastra.",
        lead_name="Joao",
    )

    assert "Ola, aqui e a Valeria da Cafe Canastra." in result
    assert "O lead se chama Joao" in result
    assert "PRIMEIRO turno" in result  # arco AIDA (1674bc5) reescreveu o texto antigo


def test_context_builder_sem_nome():
    """Sem lead_name, não deve incluir linha de nome mas deve manter o restante."""
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context

    result = build_outbound_first_turn_context(
        campaign_message="Template da campanha.",
        lead_name=None,
    )

    assert "O lead se chama" not in result
    assert "Template da campanha." in result
    assert "PRIMEIRO turno" in result  # arco AIDA (1674bc5) reescreveu o texto antigo


# ---------------------------------------------------------------------------
# Task 2 — secretaria.py outbound não contém mais conteúdo transitório
# ---------------------------------------------------------------------------

def test_secretaria_outbound_sem_bloco_transitorio():
    """SECRETARIA_PROMPT outbound não deve mais conter o bloco 'CONTEXTO DESTA ABORDAGEM'."""
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT

    assert "CONTEXTO DESTA ABORDAGEM" not in SECRETARIA_PROMPT
    assert "Voce iniciou este contato via campanha de WhatsApp. A mensagem que voce enviou foi" not in SECRETARIA_PROMPT
    assert "O lead esta RESPONDENDO a essa mensagem agora" not in SECRETARIA_PROMPT


def test_secretaria_outbound_mantem_regras_de_negocio():
    """As regras de negócio e o funil devem permanecer no prompt."""
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT

    assert "CONTEXTO OUTBOUND" in SECRETARIA_PROMPT
    assert "POSTURA OUTBOUND" in SECRETARIA_PROMPT
    assert "REGRAS CRITICAS DE SEGURANCA" in SECRETARIA_PROMPT
    assert "ETAPA 1" in SECRETARIA_PROMPT
    assert "ETAPA 4" in SECRETARIA_PROMPT


# ---------------------------------------------------------------------------
# Task 2 addendum — cobertura de ETAPA 2/3 (melhoria sugerida em code review)
# ---------------------------------------------------------------------------

def test_secretaria_outbound_mantem_etapas_intermediarias():
    """ETAPA 2 e ETAPA 3 também devem estar presentes."""
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT

    assert "ETAPA 2" in SECRETARIA_PROMPT
    assert "ETAPA 3" in SECRETARIA_PROMPT


# ---------------------------------------------------------------------------
# Task 3 — orchestrator injeta contexto outbound como primeiro content de user
#
# Contrato Gemini nativo (migração 09/07/2026): o system prompt vive em
# system_instruction (fora dos contents); o contexto de campanha e o user_text são
# types.Content role="user" (texto em .parts[0].text).
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, patch

from tests.gemini_fakes import fake_text


def _capture_generate_kwargs(m_gen):
    """Retorna os kwargs da primeira chamada a generate."""
    return m_gen.await_args_list[0].kwargs


def _orchestrator_patches(lead: dict, history: list, prompt_key: str, m_gen):
    return [
        patch("app.agent.orchestrator.get_lead", return_value=lead),
        patch("app.agent.orchestrator.get_history", return_value=history),
        patch("app.agent.orchestrator.get_agent_profile",
              return_value={"prompt_key": prompt_key, "model": "gemini-2.5-flash"}),
        patch("app.agent.orchestrator.track_token_usage"),
        patch("app.agent.orchestrator.generate", new=m_gen),
    ]


@pytest.mark.asyncio
async def test_outbound_primeiro_turno_injeta_contexto_campanha():
    """No turno 1 outbound, contents[0] deve ser o contexto da campanha (role user)."""
    import contextlib
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-out-1",
        "stage": "secretaria",
        "leads": {"id": "lead-out-1", "name": "Maria", "phone": "5511900000001"},
    }
    lead_context = {"campaign_message": "Ola, aqui e a Valeria."}

    m_gen = AsyncMock(return_value=fake_text("resposta da ia"))

    with contextlib.ExitStack() as stack:
        for p in _orchestrator_patches(
            {"id": "lead-out-1", "name": "Maria", "phone": "5511900000001", "ai_enabled": True},
            [], "valeria_outbound", m_gen,
        ):
            stack.enter_context(p)
        await run_agent(conversation, "sim", lead_context=lead_context, agent_profile_id="profile-out")

    kwargs = _capture_generate_kwargs(m_gen)
    # system vive FORA dos contents (system_instruction);
    # contents[0] = contexto campanha, contents[1] = user_text
    assert kwargs.get("system_instruction"), "system prompt deve ir em system_instruction"
    contents = kwargs["contents"]
    assert len(contents) == 2
    assert contents[0].role == "user"
    assert "Ola, aqui e a Valeria." in contents[0].parts[0].text
    assert "PRIMEIRO turno" in contents[0].parts[0].text  # arco AIDA (1674bc5)
    assert contents[1].role == "user"
    assert contents[1].parts[0].text == "sim"


@pytest.mark.asyncio
async def test_outbound_segundo_turno_nao_injeta_contexto():
    """Com histórico existente (turno 2+), não deve injetar o contexto de campanha."""
    import contextlib
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-out-2",
        "stage": "secretaria",
        "leads": {"id": "lead-out-2", "phone": "5511900000002"},
    }
    lead_context = {"campaign_message": "Ola, aqui e a Valeria."}
    existing_history = [
        {"role": "user", "content": "sim"},
        {"role": "assistant", "content": "Que bom confirmar."},
    ]

    m_gen = AsyncMock(return_value=fake_text("resposta da ia"))

    with contextlib.ExitStack() as stack:
        for p in _orchestrator_patches(
            {"id": "lead-out-2", "phone": "5511900000002", "ai_enabled": True},
            existing_history, "valeria_outbound", m_gen,
        ):
            stack.enter_context(p)
        await run_agent(conversation, "quero saber mais", lead_context=lead_context, agent_profile_id="profile-out")

    kwargs = _capture_generate_kwargs(m_gen)
    contents = kwargs["contents"]
    # 2 history + user_text = 3 contents (system em system_instruction);
    # nenhum content extra de contexto
    assert len(contents) == 3
    roles = [c.role for c in contents]
    assert roles == ["user", "model", "user"]


@pytest.mark.asyncio
async def test_inbound_nao_injeta_contexto_de_campanha():
    """Fluxo inbound (valeria_inbound) nunca deve injetar o contexto de campanha."""
    import contextlib
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-in-1",
        "stage": "secretaria",
        "leads": {"id": "lead-in-1", "phone": "5511900000003"},
    }
    # Mesmo passando campaign_message, inbound não deve injetar
    lead_context = {"campaign_message": "Mensagem que nao deveria aparecer."}

    m_gen = AsyncMock(return_value=fake_text("resposta da ia"))

    with contextlib.ExitStack() as stack:
        for p in _orchestrator_patches(
            {"id": "lead-in-1", "phone": "5511900000003", "ai_enabled": True},
            [], "valeria_inbound", m_gen,
        ):
            stack.enter_context(p)
        await run_agent(conversation, "oi", lead_context=lead_context, agent_profile_id="profile-in")

    kwargs = _capture_generate_kwargs(m_gen)
    contents = kwargs["contents"]
    assert len(contents) == 1  # apenas user_text (system em system_instruction)
    assert all("Mensagem que nao deveria aparecer" not in str(c) for c in contents)
    assert "Mensagem que nao deveria aparecer" not in (kwargs.get("system_instruction") or "")


@pytest.mark.asyncio
async def test_outbound_sem_campaign_message_nao_injeta():
    """Se campaign_message estiver ausente em lead_context, não deve injetar nada extra."""
    import contextlib
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-out-3",
        "stage": "secretaria",
        "leads": {"id": "lead-out-3", "phone": "5511900000004"},
    }

    m_gen = AsyncMock(return_value=fake_text("resposta da ia"))

    with contextlib.ExitStack() as stack:
        for p in _orchestrator_patches(
            {"id": "lead-out-3", "phone": "5511900000004", "ai_enabled": True},
            [], "valeria_outbound", m_gen,
        ):
            stack.enter_context(p)
        # lead_context sem campaign_message
        await run_agent(conversation, "oi", lead_context={"name": "Carlos"}, agent_profile_id="profile-out")

    kwargs = _capture_generate_kwargs(m_gen)
    assert len(kwargs["contents"]) == 1  # apenas user_text (system em system_instruction)


# ---------------------------------------------------------------------------
# Task 4 — harmonizacao pos-review Frente C (item 5, codigo em orchestrator.py):
# sanitize_display_name no call site do contexto outbound de 1o turno (~L721).
# Leads antigos (pre-C4, ver commit 119232e) podem ter nome-saudacao gravado no
# cadastro ("Olá, boa tarde"); sem o sanitize no call site, esse nome cru vazava
# pro contexto outbound do primeiro turno via build_outbound_first_turn_context.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outbound_primeiro_turno_nome_saudacao_nao_vaza_para_contexto():
    """Lead com nome-saudacao no cadastro (lead antigo pre-C4): o contexto outbound
    do primeiro turno nao pode carregar a saudacao crua como se fosse nome real."""
    import contextlib
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-out-greeting",
        "stage": "secretaria",
        "leads": {"id": "lead-out-greeting", "name": "Olá, boa tarde", "phone": "5511900000005"},
    }
    lead_context = {"campaign_message": "Ola, aqui e a Valeria."}

    m_gen = AsyncMock(return_value=fake_text("resposta da ia"))

    with contextlib.ExitStack() as stack:
        for p in _orchestrator_patches(
            {"id": "lead-out-greeting", "name": "Olá, boa tarde", "phone": "5511900000005", "ai_enabled": True},
            [], "valeria_outbound", m_gen,
        ):
            stack.enter_context(p)
        await run_agent(conversation, "sim", lead_context=lead_context, agent_profile_id="profile-out")

    kwargs = _capture_generate_kwargs(m_gen)
    contents = kwargs["contents"]
    # contents[0] = contexto campanha, contents[1] = user_text (system em system_instruction)
    assert len(contents) == 2
    assert contents[0].role == "user"
    assert "Olá, boa tarde" not in contents[0].parts[0].text
    assert "O lead se chama" not in contents[0].parts[0].text
