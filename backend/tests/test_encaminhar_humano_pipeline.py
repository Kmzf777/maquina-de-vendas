import pytest
from unittest.mock import patch

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
