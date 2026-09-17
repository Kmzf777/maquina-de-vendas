"""Fix do no `create_deal` do builder de automacao (Task 2).

Antes deste fix, `_execute_action` (app/automation/engine.py) so passava `category`
para `app.leads.service.create_deal`. Como a tela do builder nem tem campo de
categoria, `category` chegava sempre None, a resolucao de funil dentro de
`create_deal` caia no fallback "(4) primeiro pipeline por order_index" e o card
nascia no funil errado, na primeira coluna nao protegida — e sem `dedupe_open`, era
duplicado a cada execucao do no. Foi esse mecanismo que espalhou 19 cards de
reposicao no funil "Valeria - Importacao Leads Frios" em producao.

O contrato novo: sem `pipeline_id` explicito no config do no, `_execute_action` NAO
chama `create_deal` e devolve False (skipped) — nao agir e visivel; criar no funil
errado nao e. Com `pipeline_id`, o no repassa `stage_key` e `dedupe_open` (escopado
ao proprio `pipeline_id` via `dedupe_pipeline_id`) para `create_deal`.
"""
from unittest.mock import MagicMock, patch

from app.automation.engine import _execute_action


def _sb():
    """`_execute_action` chama `get_supabase()` incondicionalmente no topo da funcao,
    mesmo para o ramo create_deal (que delega tudo a app.leads.service.create_deal e
    nao usa `sb` diretamente). Mock simples so para a chamada nao estourar rede."""
    return MagicMock()


class TestCreateDealComPipelineId:
    def test_passa_pipeline_id_stage_key_e_dedupe_open_true(self):
        enrollment = {"id": "e1", "lead_id": "lead1"}
        node = {"id": "n1", "config": {
            "action_type": "create_deal",
            "title_template": "Deal automático",
            "pipeline_id": "pipe-123",
            "stage_key": "novo",
            "dedupe_open": True,
        }}
        lead = {"id": "lead1", "phone": "5511999", "name": "Maria"}

        with patch("app.automation.engine.get_supabase", return_value=_sb()), \
             patch("app.leads.service.create_deal") as mock_create_deal:
            mock_create_deal.return_value = {"id": "deal-1"}
            agiu = _execute_action(enrollment, node, lead)

        assert agiu is True
        mock_create_deal.assert_called_once()
        _, kwargs = mock_create_deal.call_args
        assert kwargs["pipeline_id"] == "pipe-123"
        assert kwargs["stage_key"] == "novo"
        assert kwargs["dedupe_open"] is True
        # dedupe escopado ao MESMO pipeline_id do no — sem isso, dedupe_open
        # reaproveitaria qualquer deal aberto do lead em QUALQUER funil.
        assert kwargs["dedupe_pipeline_id"] == "pipe-123"


class TestCreateDealDedupeAusente:
    def test_dedupe_open_ausente_vira_false_e_dedupe_pipeline_id_none(self):
        enrollment = {"id": "e1", "lead_id": "lead1"}
        node = {"id": "n1", "config": {
            "action_type": "create_deal",
            "title_template": "Deal automático",
            "pipeline_id": "pipe-123",
        }}
        lead = {"id": "lead1", "phone": "5511999"}

        with patch("app.automation.engine.get_supabase", return_value=_sb()), \
             patch("app.leads.service.create_deal") as mock_create_deal:
            mock_create_deal.return_value = {"id": "deal-1"}
            agiu = _execute_action(enrollment, node, lead)

        assert agiu is True
        _, kwargs = mock_create_deal.call_args
        assert kwargs["dedupe_open"] is False
        assert kwargs["dedupe_pipeline_id"] is None

    def test_dedupe_open_false_explicito_tambem_vira_dedupe_pipeline_id_none(self):
        enrollment = {"id": "e1", "lead_id": "lead1"}
        node = {"id": "n1", "config": {
            "action_type": "create_deal",
            "pipeline_id": "pipe-123",
            "dedupe_open": False,
        }}
        lead = {"id": "lead1", "phone": "5511999"}

        with patch("app.automation.engine.get_supabase", return_value=_sb()), \
             patch("app.leads.service.create_deal") as mock_create_deal:
            mock_create_deal.return_value = {"id": "deal-1"}
            _execute_action(enrollment, node, lead)

        _, kwargs = mock_create_deal.call_args
        assert kwargs["dedupe_open"] is False
        assert kwargs["dedupe_pipeline_id"] is None


class TestCreateDealSemPipelineId:
    """Coracao do fix: melhor nao agir do que criar o card no funil errado."""

    def test_sem_pipeline_id_nao_chama_create_deal_e_devolve_false(self):
        enrollment = {"id": "e1", "lead_id": "lead1"}
        node = {"id": "n1", "config": {
            "action_type": "create_deal",
            "title_template": "Deal automático",
            "category": "atacado",
        }}
        lead = {"id": "lead1", "phone": "5511999"}

        with patch("app.automation.engine.get_supabase", return_value=_sb()), \
             patch("app.leads.service.create_deal") as mock_create_deal:
            agiu = _execute_action(enrollment, node, lead)

        assert agiu is False
        mock_create_deal.assert_not_called()

    def test_pipeline_id_vazio_tambem_nao_chama_create_deal(self):
        enrollment = {"id": "e1", "lead_id": "lead1"}
        node = {"id": "n1", "config": {
            "action_type": "create_deal",
            "pipeline_id": "",
        }}
        lead = {"id": "lead1", "phone": "5511999"}

        with patch("app.automation.engine.get_supabase", return_value=_sb()), \
             patch("app.leads.service.create_deal") as mock_create_deal:
            agiu = _execute_action(enrollment, node, lead)

        assert agiu is False
        mock_create_deal.assert_not_called()


class TestCreateDealTitleTemplate:
    def test_title_template_passa_por_substitute_variables(self):
        enrollment = {"id": "e1", "lead_id": "lead1"}
        node = {"id": "n1", "config": {
            "action_type": "create_deal",
            "title_template": "Deal de {{lead.name}}",
            "pipeline_id": "pipe-123",
        }}
        lead = {"id": "lead1", "name": "João", "phone": "5511999"}

        with patch("app.automation.engine.get_supabase", return_value=_sb()), \
             patch("app.leads.service.create_deal") as mock_create_deal:
            mock_create_deal.return_value = {"id": "deal-1"}
            _execute_action(enrollment, node, lead)

        args, _ = mock_create_deal.call_args
        # create_deal(lead_id, title, category, ...) — title é o 2º posicional.
        assert args[1] == "Deal de João"

    def test_title_template_ausente_usa_default(self):
        enrollment = {"id": "e1", "lead_id": "lead1"}
        node = {"id": "n1", "config": {
            "action_type": "create_deal",
            "pipeline_id": "pipe-123",
        }}
        lead = {"id": "lead1", "phone": "5511999"}

        with patch("app.automation.engine.get_supabase", return_value=_sb()), \
             patch("app.leads.service.create_deal") as mock_create_deal:
            mock_create_deal.return_value = {"id": "deal-1"}
            _execute_action(enrollment, node, lead)

        args, _ = mock_create_deal.call_args
        assert args[1] == "Deal automático"
