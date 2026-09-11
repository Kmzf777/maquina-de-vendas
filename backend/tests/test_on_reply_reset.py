"""`on_reply='reset'`: a resposta do lead rebobina a esteira em vez de encerra-la.

Decisao da reuniao de 10/09/2026 para a esteira "Em conversa": 7 toques em 30 dias, e
qualquer resposta do lead volta o relogio para D+0. O motor so sabia `cancel` e `pause`.

Por que nao bastava `cancel` + reinscrever: o cancelamento tranca o card para fora pelo
cooldown de 90 dias da RPC (`get_deals_stage_stagnant`), e `pause` conta como matricula
viva em `is_already_enrolled` sem que ninguem a retome. Com `reset` a matricula fica
ACTIVE e nunca passa pelo caminho de reinscricao — o cooldown deixa de ser obstaculo.

NOTA (ajuste ao teste-espec): `_trigger_on_reply` resolve `list_nodes` com um import
LOCAL de `app.campaigns.service.list_nodes` (dentro da propria funcao), nao um import de
topo de modulo em `worker.py` — e `test_esteiras_on_reply.py` /
`test_esteiras_reply_todos_enrollments_2026_09_04.py` ja patcham exatamente
`app.campaigns.service.list_nodes`. A nova `_trigger_first_node` espelha essa mesma
convencao (import local) para nao duplicar o alvo de patch. Por isso os testes abaixo
patcham `app.campaigns.service.list_nodes` em vez de `worker.list_nodes` — promover
`list_nodes` a import de topo em `worker.py` desacoplaria `worker.list_nodes` do patch
que os dois arquivos de teste acima usam, e eles quebrariam silenciosamente (a chamada
real ao Supabase, sem credenciais em ambiente de teste, cairia no fail-safe e trocaria
`cancel` por `pause` em varios casos).
"""
from unittest.mock import MagicMock, patch

import pytest

from app.campaigns import worker


TRIGGER = {"id": "no-gatilho", "type": "trigger", "config": {"on_reply": "reset"},
           "next_node_id": "no-primeiro-toque"}
ENVIO = {"id": "no-envio-3", "type": "send", "config": {}, "next_node_id": "no-wait-3"}

ENROLLMENT = {
    "id": "matricula-1",
    "campaign_id": "camp-1",
    "lead_id": "lead-1",
    "current_node_id": "no-envio-3",
    "step_count": 6,
    "campaign_nodes": ENVIO,
}


class TestPoliticaReset:
    def test_resposta_rebobina_para_o_primeiro_no(self):
        with patch("app.campaigns.service.list_nodes", return_value=[TRIGGER, ENVIO]), \
             patch.object(worker, "reset_enrollment") as mock_reset, \
             patch.object(worker, "cancel_enrollment") as mock_cancel, \
             patch.object(worker, "pause_enrollment") as mock_pause:
            worker._apply_reply_policy(dict(ENROLLMENT))
        mock_reset.assert_called_once_with("matricula-1", "no-primeiro-toque")
        mock_cancel.assert_not_called()
        mock_pause.assert_not_called()

    def test_sem_primeiro_no_cai_em_pause_em_vez_de_quebrar(self):
        """FAIL-SAFE, mesma doutrina de `_trigger_on_reply`: pausar por engano e
        recuperavel; perder a esteira nao e."""
        gatilho_sem_saida = {**TRIGGER, "next_node_id": None}
        with patch("app.campaigns.service.list_nodes", return_value=[gatilho_sem_saida, ENVIO]), \
             patch.object(worker, "reset_enrollment") as mock_reset, \
             patch.object(worker, "pause_enrollment") as mock_pause:
            worker._apply_reply_policy(dict(ENROLLMENT))
        mock_reset.assert_not_called()
        mock_pause.assert_called_once_with("matricula-1")

    def test_politica_do_no_vence_a_do_gatilho(self):
        """Precedencia existente preservada: o no descreve um toque, o gatilho descreve
        a esteira — e o no, quando opina, vence."""
        envio_que_pausa = {**ENVIO, "config": {"on_reply": "pause"}}
        enrollment = {**ENROLLMENT, "campaign_nodes": envio_que_pausa}
        with patch("app.campaigns.service.list_nodes", return_value=[TRIGGER, envio_que_pausa]), \
             patch.object(worker, "reset_enrollment") as mock_reset, \
             patch.object(worker, "pause_enrollment") as mock_pause:
            worker._apply_reply_policy(enrollment)
        mock_reset.assert_not_called()
        mock_pause.assert_called_once_with("matricula-1")


class TestPrimitivoReset:
    def test_reset_mantem_a_matricula_ativa(self):
        """O ponto do desenho: ficando ACTIVE, ela nunca passa por reinscricao e o
        cooldown de 90 dias da RPC deixa de tranca-la para fora."""
        from app.campaigns.service import reset_enrollment
        mock_sb = MagicMock()
        with patch("app.campaigns.service.get_supabase", return_value=mock_sb):
            reset_enrollment("matricula-1", "no-primeiro-toque")
        payload = mock_sb.table.return_value.update.call_args[0][0]
        assert payload["status"] == "active"
        assert payload["current_node_id"] == "no-primeiro-toque"
        assert payload["step_count"] == 0
        assert payload["last_sent_node_id"] is None
        assert payload["paused_at"] is None
