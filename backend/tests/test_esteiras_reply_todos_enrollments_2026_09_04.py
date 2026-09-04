"""Resposta do lead tem de encerrar TODAS as esteiras dele, nao so uma.

O furo: `get_active_enrollment_for_lead` faz `.limit(1)` sem ordenacao e
`handle_campaign_reply` agia so sobre essa linha. Mas `is_already_enrolled` e por
CAMPANHA — o mesmo lead pode estar em duas esteiras ao mesmo tempo, e e o caso normal
aqui (`ensure_reposicao_deal` cria cards de recompra e a base tem leads com varios
deals).

Cenario real: card em "Ja chamado" (esteira de reposicao) + card em "Proposta Enviada"
(esteira de proposta). O lead responde a proposta. Cancelava-se a linha que o PostgREST
devolvesse primeiro — que podia ser a da reposicao. Dai ou a esteira de proposta mandava
o D+8 para quem ja tinha respondido, ou a de reposicao rodava ate o fim e marcava como
PERDIDO o card de um lead que engajou.
"""
from unittest.mock import MagicMock, patch

from app.campaigns.service import get_active_enrollments_for_lead
from app.campaigns.worker import handle_campaign_reply

TRIGGER_CANCEL = [{"type": "trigger", "config": {"on_reply": "cancel"}}]
TRIGGER_SEM_REGRA = [{"type": "trigger", "config": {}}]


def _enr(eid, campaign_id, node):
    return {"id": eid, "campaign_id": campaign_id, "campaign_nodes": node}


def _roda(enrollments, list_nodes_side_effect=None):
    """Executa handle_campaign_reply e devolve (mock_cancel, mock_pause)."""
    kwargs = (
        {"side_effect": list_nodes_side_effect}
        if list_nodes_side_effect is not None
        else {"side_effect": lambda cid: {"c-reposicao": TRIGGER_CANCEL,
                                          "c-proposta": TRIGGER_CANCEL,
                                          "c-pausa": TRIGGER_SEM_REGRA}.get(cid, [])}
    )
    with (
        patch("app.campaigns.service.get_active_enrollments_for_lead", return_value=enrollments),
        patch("app.campaigns.service.list_nodes", **kwargs),
        patch("app.campaigns.worker.cancel_enrollment") as mock_cancel,
        patch("app.campaigns.worker.pause_enrollment") as mock_pause,
    ):
        handle_campaign_reply("lead-1")
    return mock_cancel, mock_pause


# ── A consulta ───────────────────────────────────────────────────────────────────


class TestConsultaDevolveTodos:
    def test_devolve_todas_as_linhas_ativas_sem_limit(self):
        """Sem `.limit(1)`: com dois enrollments ativos, os DOIS voltam."""
        linhas = [{"id": "e1"}, {"id": "e2"}]
        sb = MagicMock()
        (sb.table.return_value.select.return_value
           .eq.return_value.eq.return_value.eq.return_value
           .execute.return_value.data) = linhas
        with patch("app.campaigns.service.get_supabase", return_value=sb):
            assert get_active_enrollments_for_lead("lead-1") == linhas

    def test_sem_enrollment_devolve_lista_vazia(self):
        sb = MagicMock()
        (sb.table.return_value.select.return_value
           .eq.return_value.eq.return_value.eq.return_value
           .execute.return_value.data) = None
        with patch("app.campaigns.service.get_supabase", return_value=sb):
            assert get_active_enrollments_for_lead("lead-1") == []


# ── O handler ────────────────────────────────────────────────────────────────────


class TestRespostaEncerraTodasAsEsteiras:
    def test_dois_enrollments_ativos_sao_ambos_cancelados(self):
        """O caso que mandava o D+8 para quem ja respondeu."""
        cancel, pause = _roda([
            _enr("e-reposicao", "c-reposicao", {"type": "wait", "config": {}}),
            _enr("e-proposta", "c-proposta", {"type": "wait", "config": {}}),
        ])
        assert sorted(c.args[0] for c in cancel.call_args_list) == ["e-proposta", "e-reposicao"]
        pause.assert_not_called()

    def test_cada_enrollment_segue_a_sua_propria_regra(self):
        """Precedencia no -> gatilho -> pausa vale POR enrollment, nao para o lead."""
        cancel, pause = _roda([
            _enr("e-cancela", "c-proposta", {"type": "wait", "config": {}}),
            _enr("e-pausa", "c-pausa", {"type": "wait", "config": {}}),
        ])
        cancel.assert_called_once_with("e-cancela")
        pause.assert_called_once_with("e-pausa")

    def test_no_com_on_reply_proprio_vence_o_gatilho_do_seu_enrollment(self):
        cancel, pause = _roda([
            _enr("e-no-pausa", "c-proposta", {"type": "send", "config": {"on_reply": "pause"}}),
            _enr("e-gatilho", "c-proposta", {"type": "wait", "config": {}}),
        ])
        pause.assert_called_once_with("e-no-pausa")
        cancel.assert_called_once_with("e-gatilho")

    def test_erro_num_enrollment_nao_deixa_o_outro_armado(self):
        """Sem isolamento, uma linha ruim deixaria a outra esteira viva e disparando."""
        enrollments = [
            _enr("e-quebrado", "c-proposta", {"type": "wait", "config": {}}),
            _enr("e-ok", "c-proposta", {"type": "wait", "config": {}}),
        ]
        with (
            patch("app.campaigns.service.get_active_enrollments_for_lead", return_value=enrollments),
            patch("app.campaigns.service.list_nodes", return_value=TRIGGER_CANCEL),
            patch("app.campaigns.worker.cancel_enrollment",
                  side_effect=[RuntimeError("boom"), None]) as mock_cancel,
            patch("app.campaigns.worker.pause_enrollment"),
        ):
            handle_campaign_reply("lead-1")
        assert [c.args[0] for c in mock_cancel.call_args_list] == ["e-quebrado", "e-ok"]

    def test_sem_enrollment_ativo_nao_faz_nada(self):
        cancel, pause = _roda([])
        cancel.assert_not_called()
        pause.assert_not_called()
