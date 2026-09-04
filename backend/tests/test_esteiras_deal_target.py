"""mark_deal_* tem de agir no deal do ENROLLMENT, nao no mais recente do lead."""
from unittest.mock import MagicMock, patch

from app.automation.engine import _execute_action


def _sb_com_deal_mais_recente(deal_id="deal-mais-novo"):
    sb = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value
       .order.return_value.limit.return_value.execute.return_value.data) = [{"id": deal_id}]
    return sb


def _updates(sb):
    return [c[0][0] for c in sb.table.return_value.update.call_args_list]


def _ids_atualizados(sb):
    return [c[0][1] for c in sb.table.return_value.update.return_value.eq.call_args_list]


class TestDealAlvo:
    def test_usa_deal_id_do_enrollment_quando_existe(self):
        sb = _sb_com_deal_mais_recente()
        enrollment = {"id": "e1", "lead_id": "lead1", "deal_id": "deal-da-esteira"}
        node = {"config": {"action_type": "mark_deal_lost", "stage_id": "stage-lost"}}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            _execute_action(enrollment, node, {"id": "lead1", "phone": "5511999"})
        assert "deal-da-esteira" in _ids_atualizados(sb)
        assert "deal-mais-novo" not in _ids_atualizados(sb)

    def test_cai_para_o_mais_recente_sem_deal_id(self):
        sb = _sb_com_deal_mais_recente()
        enrollment = {"id": "e1", "lead_id": "lead1"}
        node = {"config": {"action_type": "mark_deal_lost", "stage_id": "stage-lost"}}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            _execute_action(enrollment, node, {"id": "lead1", "phone": "5511999"})
        assert "deal-mais-novo" in _ids_atualizados(sb)


class TestLostReason:
    def test_grava_lost_reason_quando_configurado(self):
        sb = _sb_com_deal_mais_recente()
        enrollment = {"id": "e1", "lead_id": "lead1", "deal_id": "d9"}
        node = {"config": {
            "action_type": "mark_deal_lost",
            "stage_id": "stage-lost",
            "lost_reason": "sem resposta na esteira de reposicao",
        }}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            _execute_action(enrollment, node, {"id": "lead1", "phone": "5511999"})
        assert any(u.get("lost_reason") == "sem resposta na esteira de reposicao"
                   for u in _updates(sb))

    def test_nao_grava_lost_reason_em_mark_deal_won(self):
        sb = _sb_com_deal_mais_recente()
        enrollment = {"id": "e1", "lead_id": "lead1", "deal_id": "d9"}
        node = {"config": {
            "action_type": "mark_deal_won",
            "stage_id": "stage-won",
            "lost_reason": "nao deveria aparecer",
        }}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            _execute_action(enrollment, node, {"id": "lead1", "phone": "5511999"})
        assert all("lost_reason" not in u for u in _updates(sb))
