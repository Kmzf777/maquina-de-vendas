"""Acao alert_seller: alerta de sistema + nota no card, fail-soft."""
from unittest.mock import MagicMock, patch

from app.automation.engine import _execute_action


NODE = {"config": {
    "action_type": "alert_seller",
    "severity": "warning",
    "title": "Proposta esfriando",
    "message_template": "{{nome}} nao respondeu a proposta.",
}}
ENROLLMENT = {"id": "e1", "lead_id": "lead1", "deal_id": "d1", "campaign_id": "c1"}
LEAD = {"id": "lead1", "phone": "5511999", "name": "Marcella"}


def test_cria_alerta_com_metadata():
    sb = MagicMock()
    with (
        patch("app.automation.engine.get_supabase", return_value=sb),
        patch("app.alerts.service.create_system_alert") as mock_alert,
    ):
        _execute_action(ENROLLMENT, NODE, LEAD)
    mock_alert.assert_called_once()
    kwargs = mock_alert.call_args.kwargs
    assert kwargs["type"] == "esteira_vendedor"
    assert kwargs["severity"] == "warning"
    assert kwargs["metadata"]["lead_id"] == "lead1"
    assert kwargs["metadata"]["deal_id"] == "d1"
    assert kwargs["metadata"]["campaign_id"] == "c1"


def test_substitui_variaveis_na_mensagem():
    sb = MagicMock()
    with (
        patch("app.automation.engine.get_supabase", return_value=sb),
        patch("app.alerts.service.create_system_alert") as mock_alert,
    ):
        _execute_action(ENROLLMENT, NODE, LEAD)
    assert "Marcella" in mock_alert.call_args.kwargs["message"]


def test_grava_nota_no_lead():
    sb = MagicMock()
    with (
        patch("app.automation.engine.get_supabase", return_value=sb),
        patch("app.alerts.service.create_system_alert"),
    ):
        _execute_action(ENROLLMENT, NODE, LEAD)
    sb.table.assert_any_call("lead_notes")


def test_fail_soft_quando_alerta_explode():
    sb = MagicMock()
    with (
        patch("app.automation.engine.get_supabase", return_value=sb),
        patch("app.alerts.service.create_system_alert", side_effect=RuntimeError("boom")),
    ):
        _execute_action(ENROLLMENT, NODE, LEAD)  # nao levanta


def test_severity_default_e_warning():
    sb = MagicMock()
    node = {"config": {"action_type": "alert_seller", "title": "x", "message_template": "y"}}
    with (
        patch("app.automation.engine.get_supabase", return_value=sb),
        patch("app.alerts.service.create_system_alert") as mock_alert,
    ):
        _execute_action(ENROLLMENT, node, LEAD)
    assert mock_alert.call_args.kwargs["severity"] == "warning"
