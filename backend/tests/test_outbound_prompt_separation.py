import pytest


# ---------------------------------------------------------------------------
# Task 1 — build_outbound_first_turn_context
# ---------------------------------------------------------------------------

def test_context_builder_com_nome_e_campanha():
    """Deve incluir campaign_message, nome do lead e aviso de que está respondendo."""
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context

    result = build_outbound_first_turn_context(
        campaign_message="Ola, aqui e a Valeria da Cafe Canastra.",
        lead_name="Joao",
    )

    assert "Ola, aqui e a Valeria da Cafe Canastra." in result
    assert "O lead se chama Joao" in result
    assert "O lead está respondendo" in result


def test_context_builder_sem_nome():
    """Sem lead_name, não deve incluir linha de nome mas deve manter o restante."""
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context

    result = build_outbound_first_turn_context(
        campaign_message="Template da campanha.",
        lead_name=None,
    )

    assert "O lead se chama" not in result
    assert "Template da campanha." in result
    assert "O lead está respondendo" in result


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
# Task 3 — orchestrator injeta contexto outbound como primeiro user message
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, patch, MagicMock


def _mock_openai_response(text: str = "resposta da ia"):
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = text
    resp = MagicMock()
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


def _capture_messages(create_mock):
    """Retorna a lista de messages passada na primeira chamada ao create."""
    call_args = create_mock.call_args
    return call_args.kwargs.get("messages") or call_args.args[0]


@pytest.mark.asyncio
async def test_outbound_primeiro_turno_injeta_contexto_campanha():
    """No turno 1 outbound, messages[1] deve ser o contexto da campanha (role user)."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-out-1",
        "stage": "secretaria",
        "leads": {"id": "lead-out-1", "name": "Maria", "phone": "5511900000001"},
    }
    lead_context = {"campaign_message": "Ola, aqui e a Valeria."}

    create_mock = AsyncMock(return_value=_mock_openai_response())

    with patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-out-1", "name": "Maria", "phone": "5511900000001", "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_outbound", "model": "gpt-4.1-mini"}), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = create_mock
        await run_agent(conversation, "sim", lead_context=lead_context, agent_profile_id="profile-out")

    messages = _capture_messages(create_mock)
    # messages[0] = system, messages[1] = contexto campanha, messages[2] = user_text
    assert len(messages) == 3
    assert messages[1]["role"] == "user"
    assert "Ola, aqui e a Valeria." in messages[1]["content"]
    assert "O lead está respondendo" in messages[1]["content"]
    assert messages[2] == {"role": "user", "content": "sim"}


@pytest.mark.asyncio
async def test_outbound_segundo_turno_nao_injeta_contexto():
    """Com histórico existente (turno 2+), não deve injetar o contexto de campanha."""
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

    create_mock = AsyncMock(return_value=_mock_openai_response())

    with patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-out-2", "phone": "5511900000002", "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.get_history", return_value=existing_history), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_outbound", "model": "gpt-4.1-mini"}), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = create_mock
        await run_agent(conversation, "quero saber mais", lead_context=lead_context, agent_profile_id="profile-out")

    messages = _capture_messages(create_mock)
    # system + 2 history + user_text = 4 mensagens; nenhum role extra de contexto
    assert len(messages) == 4
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "user"]


@pytest.mark.asyncio
async def test_inbound_nao_injeta_contexto_de_campanha():
    """Fluxo inbound (valeria_inbound) nunca deve injetar o contexto de campanha."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-in-1",
        "stage": "secretaria",
        "leads": {"id": "lead-in-1", "phone": "5511900000003"},
    }
    # Mesmo passando campaign_message, inbound não deve injetar
    lead_context = {"campaign_message": "Mensagem que nao deveria aparecer."}

    create_mock = AsyncMock(return_value=_mock_openai_response())

    with patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-in-1", "phone": "5511900000003", "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_inbound", "model": "gpt-4.1-mini"}), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = create_mock
        await run_agent(conversation, "oi", lead_context=lead_context, agent_profile_id="profile-in")

    messages = _capture_messages(create_mock)
    assert len(messages) == 2  # system + user_text
    assert all("Mensagem que nao deveria aparecer" not in str(m) for m in messages)


@pytest.mark.asyncio
async def test_outbound_sem_campaign_message_nao_injeta():
    """Se campaign_message estiver ausente em lead_context, não deve injetar nada extra."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-out-3",
        "stage": "secretaria",
        "leads": {"id": "lead-out-3", "phone": "5511900000004"},
    }

    create_mock = AsyncMock(return_value=_mock_openai_response())

    with patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-out-3", "phone": "5511900000004", "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_outbound", "model": "gpt-4.1-mini"}), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = create_mock
        # lead_context sem campaign_message
        await run_agent(conversation, "oi", lead_context={"name": "Carlos"}, agent_profile_id="profile-out")

    messages = _capture_messages(create_mock)
    assert len(messages) == 2  # system + user_text apenas
