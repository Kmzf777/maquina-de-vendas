# backend/tests/test_automation_variables.py
import pytest
from unittest.mock import patch, MagicMock
from app.automation.variables import substitute_variables

LEAD = {
    "id": "lead-001",
    "name": "João Silva",
    "company": "Empresa X",
    "phone": "5511999990000",
    "assigned_to": None,
}

ENROLLMENT = {"lead_id": "lead-001"}


class TestSubstituteVariables:
    def test_basic_lead_vars(self):
        result = substitute_variables("Olá {{nome}} da {{empresa}}", LEAD, ENROLLMENT)
        assert result == "Olá João Silva da Empresa X"

    def test_missing_name_becomes_empty(self):
        lead = {**LEAD, "name": None}
        result = substitute_variables("Olá {{nome}}!", lead, ENROLLMENT)
        assert result == "Olá !"

    def test_phone_var(self):
        result = substitute_variables("Seu telefone: {{telefone}}", LEAD, ENROLLMENT)
        assert result == "Seu telefone: 5511999990000"

    def test_sale_vars_with_sale(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {"product": "Café Especial", "value": 150.50, "sold_at": "2026-05-10T10:00:00+00:00"}
        ]
        with patch("app.automation.variables.get_supabase", return_value=mock_sb):
            result = substitute_variables("Comprou {{produto}} por {{valor_ultima_venda}}", LEAD, ENROLLMENT)
        assert "Café Especial" in result
        assert "R$" in result

    def test_sale_vars_without_sale(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        with patch("app.automation.variables.get_supabase", return_value=mock_sb):
            result = substitute_variables("Produto: {{produto}}", LEAD, ENROLLMENT)
        assert result == "Produto: "

    def test_no_db_call_when_no_sale_vars(self):
        with patch("app.automation.variables.get_supabase") as mock_get_sb:
            substitute_variables("Olá {{nome}}", LEAD, ENROLLMENT)
        mock_get_sb.assert_not_called()
