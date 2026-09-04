"""Opt-out tem de desarmar OS DOIS motores, nao so o de follow-up.

`apply_optout_side_effects` e o ponto de convergencia dos tres caminhos de opt-out — o
botao de saida do template (`campaigns/worker.py::handle_optout_reply`), a tool do LLM
(`agent/tools.py::registrar_optout`) e o botao do operador
(`POST /api/leads/{id}/optout`). Ela movia os deals para a Blacklist e cancelava os
`follow_up_jobs`, mas nunca tocava em `campaign_enrollments`: quem pedia para sair no meio
de uma cadencia continuava inscrito, e o proximo toque saia.

O segundo ganho e simetrico e menos obvio: `is_already_enrolled` conta `active` E `paused`
como "ja inscrito". Enrollment pendurado nesses estados nunca e retomado por ninguem —
entao o lead que pede para sair hoje ficaria INELEGIVEL PARA SEMPRE, invisivel para
qualquer campanha futura, mesmo que volte a comprar daqui a um ano. Cancelar devolve o
lead ao mundo.
"""
import logging
from unittest.mock import MagicMock, patch

from app.campaigns.service import cancel_enrollments_for_lead
from app.leads.service import apply_optout_side_effects


def _sb(rows):
    """Supabase falso cujo update().eq().in_().execute().data == rows."""
    sb = MagicMock()
    (sb.table.return_value.update.return_value
       .eq.return_value.in_.return_value.execute.return_value.data) = rows
    return sb


# ── A consulta em lote ───────────────────────────────────────────────────────────


class TestCancelEnrollmentsForLead:
    def test_cancela_em_uma_consulta_so(self):
        sb = _sb([{"id": "e1"}, {"id": "e2"}])
        with patch("app.campaigns.service.get_supabase", return_value=sb):
            assert cancel_enrollments_for_lead("lead-1") == 2
        sb.table.assert_called_once_with("campaign_enrollments")
        sb.table.return_value.update.assert_called_once_with({"status": "cancelled"})
        sb.table.return_value.update.return_value.eq.assert_called_once_with("lead_id", "lead-1")

    def test_alcanca_paused_alem_de_active(self):
        """`paused` conta como inscrito em `is_already_enrolled` e ninguem o retoma —
        deixar para tras e condenar o lead a nunca mais entrar em campanha nenhuma."""
        sb = _sb([])
        with patch("app.campaigns.service.get_supabase", return_value=sb):
            cancel_enrollments_for_lead("lead-1")
        status_filtro = (sb.table.return_value.update.return_value
                           .eq.return_value.in_.call_args)
        assert status_filtro.args[0] == "status"
        assert set(status_filtro.args[1]) == {"active", "paused"}

    def test_idempotente_segunda_chamada_nao_acha_nada(self):
        sb = _sb([])
        with patch("app.campaigns.service.get_supabase", return_value=sb):
            assert cancel_enrollments_for_lead("lead-1") == 0

    def test_sem_lead_id_nao_toca_no_banco(self):
        sb = _sb([{"id": "e1"}])
        with patch("app.campaigns.service.get_supabase", return_value=sb):
            assert cancel_enrollments_for_lead("") == 0
        sb.table.assert_not_called()


# ── A integracao no opt-out ──────────────────────────────────────────────────────


class TestApplyOptoutSideEffects:
    def test_cancela_enrollments_do_lead(self):
        with (
            patch("app.leads.service.move_lead_deals_to_blacklist"),
            patch("app.campaigns.service.cancel_enrollments_for_lead", return_value=1) as mock_cancel,
            patch("app.follow_up.service.cancel_followups_by_phone"),
        ):
            apply_optout_side_effects("lead-1", "5511999990000", reason="optout")
        mock_cancel.assert_called_once_with("lead-1")

    def test_roda_mesmo_sem_telefone(self):
        """O cancelamento de follow-up depende do phone; o de enrollment nao — e um lead
        sem telefone gravado tambem tem direito a sair da esteira."""
        with (
            patch("app.leads.service.move_lead_deals_to_blacklist"),
            patch("app.campaigns.service.cancel_enrollments_for_lead") as mock_cancel,
            patch("app.follow_up.service.cancel_followups_by_phone") as mock_fu,
        ):
            apply_optout_side_effects("lead-1", "", reason="optout")
        mock_cancel.assert_called_once_with("lead-1")
        mock_fu.assert_not_called()

    def test_erro_ao_cancelar_enrollment_nao_derruba_o_opt_out(self, caplog):
        """Fail-soft: a parte que o cliente pediu (sair) nao pode cair junto — e o
        cancelamento de follow-up, que vem depois, precisa acontecer mesmo assim."""
        with (
            patch("app.leads.service.move_lead_deals_to_blacklist") as mock_move,
            patch("app.campaigns.service.cancel_enrollments_for_lead",
                  side_effect=RuntimeError("postgrest down")),
            patch("app.follow_up.service.cancel_followups_by_phone") as mock_fu,
        ):
            caplog.set_level(logging.ERROR, logger="app.leads.service")
            apply_optout_side_effects("lead-1", "5511999990000", reason="optout")  # nao levanta
        mock_move.assert_called_once_with("lead-1")
        mock_fu.assert_called_once()
        assert any(
            "apply_optout_side_effects" in rec.message and rec.levelname == "ERROR"
            for rec in caplog.records
        )


# ── Os tres caminhos convergem aqui ──────────────────────────────────────────────


def test_botao_do_template_chega_no_cancelamento_de_enrollment():
    """Ponta a ponta do caminho novo: clique na saida digna -> enrollment cancelado."""
    from app.campaigns.worker import handle_optout_reply

    with (
        patch("app.leads.service.update_lead"),
        patch("app.leads.service.move_lead_deals_to_blacklist"),
        patch("app.campaigns.service.cancel_enrollments_for_lead") as mock_cancel,
        patch("app.follow_up.service.cancel_followups_by_phone"),
        patch("app.leads.service.append_lead_observation"),
        patch("app.leads.service.save_message"),
    ):
        handle_optout_reply(
            {"id": "lead-1", "phone": "5511999999999", "ai_enabled": False},
            "Nao tenho interesse",
        )
    mock_cancel.assert_called_once_with("lead-1")
