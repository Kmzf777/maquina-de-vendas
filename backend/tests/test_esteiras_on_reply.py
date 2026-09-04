"""`on_reply` no no de GATILHO: politica de resposta da esteira INTEIRA.

O furo que estes testes fecham: `handle_campaign_reply` so honrava `on_reply='cancel'`
quando o enrollment estava parado num no `send`. Uma esteira passa a maior parte da
vida parada num no `wait` — e e ali que a maioria das respostas chega. O enrollment ia
para `paused`, estado que `is_already_enrolled` conta como ativo e que ninguem retoma:
o lead ficava inelegivel para reentrar na esteira PARA SEMPRE.

Regra nova: o no com `on_reply` proprio vence; sem ele, vale o `on_reply` do no de
gatilho, que descreve a cadeia toda. Fail-safe em qualquer duvida: PAUSA.
"""
from unittest.mock import patch

from app.campaigns.worker import handle_campaign_reply


def _roda(node, trigger_nodes=None, list_nodes_side_effect=None):
    """Executa handle_campaign_reply e devolve (mock_cancel, mock_pause, mock_list)."""
    enrollment = {"id": "e1", "campaign_id": "camp1", "campaign_nodes": node}
    list_kwargs = {}
    if list_nodes_side_effect is not None:
        list_kwargs["side_effect"] = list_nodes_side_effect
    else:
        list_kwargs["return_value"] = trigger_nodes if trigger_nodes is not None else []
    with (
        patch("app.campaigns.service.get_active_enrollment_for_lead", return_value=enrollment),
        patch("app.campaigns.service.list_nodes", **list_kwargs) as mock_list,
        patch("app.campaigns.worker.cancel_enrollment") as mock_cancel,
        patch("app.campaigns.worker.pause_enrollment") as mock_pause,
    ):
        handle_campaign_reply("lead-1")
    return mock_cancel, mock_pause, mock_list


TRIGGER_CANCEL = [{"type": "trigger", "config": {"on_reply": "cancel"}}]
TRIGGER_SEM_REGRA = [{"type": "trigger", "config": {}}]


class TestComportamentoDeHojeNaoRegride:
    def test_1_send_com_on_reply_cancel_cancela(self):
        cancel, pause, _ = _roda({"type": "send", "config": {"on_reply": "cancel"}})
        cancel.assert_called_once_with("e1")
        pause.assert_not_called()

    def test_2_send_sem_on_reply_e_gatilho_sem_on_reply_pausa(self):
        cancel, pause, _ = _roda({"type": "send", "config": {}}, TRIGGER_SEM_REGRA)
        pause.assert_called_once_with("e1")
        cancel.assert_not_called()


class TestGatilhoDescreveAEsteira:
    def test_3_wait_com_gatilho_cancel_cancela(self):
        """O furo: resposta que chega no `wait` tem de encerrar a esteira, nao pausar."""
        cancel, pause, _ = _roda({"type": "wait", "config": {}}, TRIGGER_CANCEL)
        cancel.assert_called_once_with("e1")
        pause.assert_not_called()

    def test_4_wait_com_gatilho_sem_on_reply_pausa(self):
        cancel, pause, _ = _roda({"type": "wait", "config": {}}, TRIGGER_SEM_REGRA)
        pause.assert_called_once_with("e1")
        cancel.assert_not_called()


class TestNoVenceGatilho:
    def test_5_send_com_pause_explicito_ignora_gatilho_cancel(self):
        cancel, pause, mock_list = _roda(
            {"type": "send", "config": {"on_reply": "pause"}}, TRIGGER_CANCEL
        )
        pause.assert_called_once_with("e1")
        cancel.assert_not_called()
        # O no ja decidiu — nao ha por que ir ao banco ler o gatilho.
        mock_list.assert_not_called()


class TestFailSafe:
    def test_6a_campanha_sem_no_de_gatilho_pausa(self):
        cancel, pause, _ = _roda({"type": "wait", "config": {}}, [])
        pause.assert_called_once_with("e1")
        cancel.assert_not_called()

    def test_6b_erro_ao_ler_o_gatilho_pausa(self):
        cancel, pause, _ = _roda(
            {"type": "wait", "config": {}}, list_nodes_side_effect=RuntimeError("boom")
        )
        pause.assert_called_once_with("e1")
        cancel.assert_not_called()

    def test_6c_enrollment_sem_campaign_id_pausa_sem_ir_ao_banco(self):
        """Enrollments antigos/parciais nao podem cancelar por acidente."""
        enrollment = {"id": "e1", "campaign_nodes": {"type": "wait", "config": {}}}
        with (
            patch("app.campaigns.service.get_active_enrollment_for_lead", return_value=enrollment),
            patch("app.campaigns.service.list_nodes") as mock_list,
            patch("app.campaigns.worker.cancel_enrollment") as mock_cancel,
            patch("app.campaigns.worker.pause_enrollment") as mock_pause,
        ):
            handle_campaign_reply("lead-1")
        mock_pause.assert_called_once_with("e1")
        mock_cancel.assert_not_called()
        mock_list.assert_not_called()

    def test_6d_send_text_com_cancel_do_no_continua_pausando(self):
        """system_cadence grava on_reply='cancel' em nos send_text que HOJE pausam.
        A regra de `cancel` no nivel do no segue restrita a `send`."""
        cancel, pause, _ = _roda({"type": "send_text", "config": {"on_reply": "cancel"}})
        pause.assert_called_once_with("e1")
        cancel.assert_not_called()
