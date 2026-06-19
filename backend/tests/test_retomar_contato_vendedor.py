"""Tests for the retomar_contato_vendedor re-engagement tool and its business-window plumbing."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.agent.tools import get_tools_for_stage, execute_tool

SP_TZ = ZoneInfo("America/Sao_Paulo")


# ─── schema / stage exposure ────────────────────────────────────────────────

def test_retomar_contato_vendedor_in_commercial_stages():
    for stage in ["secretaria", "atacado", "private_label", "exportacao"]:
        names = [t["function"]["name"] for t in get_tools_for_stage(stage)]
        assert "retomar_contato_vendedor" in names, f"ausente no stage '{stage}'"


def test_retomar_contato_vendedor_absent_in_consumo():
    names = [t["function"]["name"] for t in get_tools_for_stage("consumo")]
    assert "retomar_contato_vendedor" not in names


def test_retomar_contato_vendedor_description_exige_sim_explicito():
    from app.agent.tools import TOOLS_SCHEMA
    schema = next(t for t in TOOLS_SCHEMA if t["function"]["name"] == "retomar_contato_vendedor")
    desc = schema["function"]["description"]
    assert "SIM" in desc
    assert "Joao" in desc
    assert "AGORA" in desc and "AGENDA" in desc


# ─── is_within_business_window ──────────────────────────────────────────────

def test_is_within_business_window_true_on_weekday_noon():
    from app.follow_up.service import is_within_business_window
    target = datetime(2026, 5, 25, 12, 0, tzinfo=SP_TZ).astimezone(timezone.utc)  # segunda 12h
    assert is_within_business_window(target) is True


def test_is_within_business_window_false_after_16h():
    from app.follow_up.service import is_within_business_window
    target = datetime(2026, 5, 25, 17, 0, tzinfo=SP_TZ).astimezone(timezone.utc)  # segunda 17h
    assert is_within_business_window(target) is False


def test_is_within_business_window_false_on_weekend():
    from app.follow_up.service import is_within_business_window
    target = datetime(2026, 5, 23, 12, 0, tzinfo=SP_TZ).astimezone(timezone.utc)  # sabado
    assert is_within_business_window(target) is False


# ─── tool behavior ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retomar_in_business_hours_dispatches_now_and_disables_ai():
    """Dentro do horario: dispara AGORA, desativa IA e instrui despedida imediata."""
    with patch("app.agent.tools.update_lead") as mock_update, \
         patch("app.agent.tools.create_deal"), \
         patch("app.agent.tools.move_open_deal_for_handoff", return_value=None), \
         patch("app.agent.tools.save_message"), \
         patch("app.agent.tools.get_lead", return_value={"id": "lead-1", "name": "Rafael", "stage": "atacado"}), \
         patch("app.follow_up.service.is_within_business_window", return_value=True), \
         patch("app.follow_up.scheduler.send_joao_handoff_template", new=AsyncMock(return_value=True)) as mock_send:
        out = await execute_tool(
            "retomar_contato_vendedor",
            {"motivo": "achou caro, agora topa retomar"},
            lead_id="lead-1",
            phone="5511999999999",
            conversation_id="conv-1",
        )

    mock_update.assert_called_once_with("lead-1", ai_enabled=False, human_control=True, status="converted")
    mock_send.assert_awaited_once_with("5511999999999", "Rafael", lead_id="lead-1")
    assert "DISPARO REALIZADO AGORA" in out


@pytest.mark.asyncio
async def test_retomar_out_of_hours_schedules_and_disables_ai():
    """Fora do horario: agenda para proximo dia util, desativa IA, instrui despedida agendada."""
    fire_at = datetime(2026, 5, 26, 9, 0, tzinfo=SP_TZ).astimezone(timezone.utc)
    with patch("app.agent.tools.update_lead") as mock_update, \
         patch("app.agent.tools.create_deal"), \
         patch("app.agent.tools.move_open_deal_for_handoff", return_value=None), \
         patch("app.agent.tools.save_message"), \
         patch("app.agent.tools.get_lead", return_value={"id": "lead-1", "name": "Rafael", "stage": "atacado"}), \
         patch("app.agent.tools.get_channel_for_lead", return_value={"id": "ch-1"}), \
         patch("app.follow_up.service.is_within_business_window", return_value=False), \
         patch("app.follow_up.service.schedule_handoff_rescue", return_value=fire_at) as mock_sched:
        out = await execute_tool(
            "retomar_contato_vendedor",
            {"motivo": "fora do horario"},
            lead_id="lead-1",
            phone="5511999999999",
            conversation_id="conv-1",
        )

    mock_update.assert_called_once_with("lead-1", ai_enabled=False, human_control=True, status="converted")
    assert mock_sched.call_args.kwargs["delay_minutes"] == 0
    assert "DISPARO AGENDADO" in out


@pytest.mark.asyncio
async def test_retomar_returns_critical_when_disable_ai_fails(caplog):
    """Se update_lead falhar, retorna CRITICAL e nao tenta disparar."""
    import logging
    with patch("app.agent.tools.update_lead", side_effect=RuntimeError("db dead")), \
         patch("app.agent.tools.create_deal") as mock_deal, \
         patch("app.agent.tools.get_lead", return_value={"id": "lead-1", "stage": "atacado"}):
        caplog.set_level(logging.ERROR, logger="app.agent.tools")
        out = await execute_tool(
            "retomar_contato_vendedor",
            {"motivo": "x"},
            lead_id="lead-1",
            phone="5511999999999",
            conversation_id="conv-1",
        )
    assert "CRITICAL" in out
    mock_deal.assert_not_called()


@pytest.mark.asyncio
async def test_retomar_moves_lp_card_instead_of_creating():
    """Lead de LP: retomar MOVE o card para o funil do João (não cria outro)."""
    move_calls = []
    create_calls = []

    def fake_move(lead_id, title=None):
        move_calls.append({"lead_id": lead_id, "title": title})
        return {"id": "deal-lp", "pipeline_id": "joao-atacado"}  # truthy → moveu

    def fake_create(lead_id, title, **kw):
        create_calls.append(lead_id)

    with patch("app.agent.tools.update_lead"), \
         patch("app.agent.tools.move_open_deal_for_handoff", side_effect=fake_move), \
         patch("app.agent.tools.create_deal", side_effect=fake_create), \
         patch("app.agent.tools.save_message"), \
         patch("app.agent.tools.get_lead", return_value={"id": "lead-lp", "name": "Rafael", "stage": "atacado"}), \
         patch("app.follow_up.service.is_within_business_window", return_value=True), \
         patch("app.follow_up.scheduler.send_joao_handoff_template", new=AsyncMock(return_value=True)):
        await execute_tool(
            "retomar_contato_vendedor",
            {"motivo": "retomar"},
            lead_id="lead-lp",
            phone="5511999999999",
            conversation_id="conv-1",
        )

    assert len(move_calls) == 1
    assert move_calls[0]["title"] == "Joao (retomada) - retomar"
    assert create_calls == []  # moveu o card de LP → não criou novo


# ─── prompt signal ──────────────────────────────────────────────────────────

def test_base_prompt_surfaces_returning_lead_when_handoff_summary_present():
    from app.agent.prompts.base import build_base_prompt
    prompt = build_base_prompt(
        lead_name="Rafael",
        lead_company=None,
        now=datetime(2026, 5, 25, 10, 0),
        lead_context={"handoff_summary": "qualificado em 01/05, parou de responder"},
    )
    assert "LEAD RETORNANDO" in prompt
    assert "RETOMADA DE LEAD" in prompt
