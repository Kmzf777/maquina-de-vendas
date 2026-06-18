import pytest
from unittest.mock import patch, AsyncMock

from app.agent.tools import execute_tool


@pytest.mark.asyncio
async def test_encaminhar_humano_atacado_usa_category_correta(monkeypatch):
    calls = []

    def fake_create_deal(lead_id, title, **kwargs):
        calls.append({"lead_id": lead_id, "title": title, **kwargs})
        return {"id": "deal-fake"}

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: {"id": "lead-1", "stage": "atacado", "phone": "+5511999999999"})
    monkeypatch.setattr("app.agent.tools.create_deal", fake_create_deal)
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kwargs: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: None)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: None)

    with patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras", "motivo": "qualificado"},
            lead_id="lead-1",
            phone="+5511999999999",
            conversation_id="conv-1",
        )

    assert len(calls) == 1
    assert calls[0]["category"] == "atacado"


@pytest.mark.asyncio
async def test_encaminhar_humano_private_label_usa_category_correta(monkeypatch):
    calls = []

    def fake_create_deal(lead_id, title, **kwargs):
        calls.append({"lead_id": lead_id, "title": title, **kwargs})
        return {"id": "deal-fake"}

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: {"id": "lead-2", "stage": "private_label", "phone": "+5511999999999"})
    monkeypatch.setattr("app.agent.tools.create_deal", fake_create_deal)
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kwargs: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: None)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: None)

    with patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras", "motivo": "qualificado"},
            lead_id="lead-2",
            phone="+5511999999999",
            conversation_id="conv-1",
        )

    assert len(calls) == 1
    assert calls[0]["category"] == "private_label"


@pytest.mark.asyncio
async def test_encaminhar_humano_envia_despedida_da_ia_e_cartao_de_contato(monkeypatch):
    """encaminhar_humano envia a mensagem_despedida escrita pela IA e, em seguida, o vCard do João."""
    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.123"}]})
    mock_provider.send_contact = AsyncMock(return_value={"messages": [{"id": "wamid.456"}]})

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: {"id": "lead-1", "stage": "atacado"})
    monkeypatch.setattr("app.agent.tools.create_deal", lambda lead_id, title, **kw: {"id": "deal-1"})
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kw: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: {
        "id": "ch-1", "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "111", "access_token": "tok"},
    })
    monkeypatch.setattr("app.agent.tools.get_provider", lambda channel: mock_provider)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: None)

    despedida = "Foi um prazer, João! Vou te passar pro nosso supervisor pra fechar tudo certinho."
    with patch("app.agent.tools.save_message"):
        await execute_tool(
            "encaminhar_humano",
            {"mensagem_despedida": despedida, "vendedor": "João", "motivo": "qualificado"},
            lead_id="lead-1",
            phone="5511999999999",
            conversation_id="conv-1",
        )

    # 1) o texto enviado é exatamente a despedida escrita pela IA (sem link/wa.me)
    mock_provider.send_text.assert_called_once()
    _, sent_msg = mock_provider.send_text.call_args[0]
    assert sent_msg == despedida
    assert "wa.me" not in sent_msg

    # 2) logo após, o cartão de contato do João é enviado
    mock_provider.send_contact.assert_called_once()
    kwargs = mock_provider.send_contact.call_args.kwargs
    assert kwargs["contact_name"] == "João"
    assert kwargs["contact_phone"] == "553491461669"


@pytest.mark.asyncio
async def test_encaminhar_humano_fallback_quando_sem_mensagem_despedida(monkeypatch):
    """Sem mensagem_despedida (ex.: guardrail), usa o texto estático e ainda envia o vCard."""
    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.123"}]})
    mock_provider.send_contact = AsyncMock(return_value={"messages": [{"id": "wamid.456"}]})

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: {"id": "lead-1", "stage": "atacado"})
    monkeypatch.setattr("app.agent.tools.create_deal", lambda lead_id, title, **kw: {"id": "deal-1"})
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kw: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: {
        "id": "ch-1", "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "111", "access_token": "tok"},
    })
    monkeypatch.setattr("app.agent.tools.get_provider", lambda channel: mock_provider)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: None)

    with patch("app.agent.tools.save_message"):
        await execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras", "motivo": "frustracao — guardrail"},
            lead_id="lead-1",
            phone="5511999999999",
            conversation_id="conv-1",
        )

    mock_provider.send_text.assert_called_once()
    mock_provider.send_contact.assert_called_once()


@pytest.mark.asyncio
async def test_encaminhar_humano_schedules_rescue_job(monkeypatch):
    """encaminhar_humano chama schedule_handoff_rescue com lead_id, phone e conv_id."""
    rescue_calls = []
    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.123"}]})

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: {"id": "lead-1", "stage": "atacado"})
    monkeypatch.setattr("app.agent.tools.create_deal", lambda lead_id, title, **kw: {"id": "deal-1"})
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kw: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: {
        "id": "ch-ai-1", "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "111", "access_token": "tok"},
    })
    monkeypatch.setattr("app.agent.tools.get_provider", lambda channel: mock_provider)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: rescue_calls.append(kw))

    with patch("app.agent.tools.save_message"):
        await execute_tool(
            "encaminhar_humano",
            {"vendedor": "João", "motivo": "qualificado"},
            lead_id="lead-1",
            phone="5511999999999",
            conversation_id="conv-1",
        )

    assert len(rescue_calls) == 1
    assert rescue_calls[0]["lead_id"] == "lead-1"
    assert rescue_calls[0]["lead_phone"] == "5511999999999"
    assert rescue_calls[0]["conversation_id"] == "conv-1"
    assert rescue_calls[0]["channel_id"] == "ch-ai-1"


@pytest.mark.asyncio
async def test_encaminhar_humano_schedules_rescue_even_if_send_text_fails(monkeypatch):
    """Falha no send_text não impede agendamento do job de resgate."""
    rescue_calls = []
    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock(side_effect=RuntimeError("network error"))

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: {"id": "lead-1", "stage": "atacado"})
    monkeypatch.setattr("app.agent.tools.create_deal", lambda lead_id, title, **kw: {"id": "deal-1"})
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kw: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: {
        "id": "ch-ai-1", "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "111", "access_token": "tok"},
    })
    monkeypatch.setattr("app.agent.tools.get_provider", lambda channel: mock_provider)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: rescue_calls.append(kw))

    with patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "encaminhar_humano",
            {"vendedor": "João", "motivo": "qualificado"},
            lead_id="lead-1",
            phone="5511999999999",
            conversation_id="conv-1",
        )

    assert len(rescue_calls) == 1
    assert "encaminhado" in result.lower()
