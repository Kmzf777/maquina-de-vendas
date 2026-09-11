"""A colisao entre os DOIS caminhos de opt-out, que o merge das esteiras criou.

O agente de botoes (producao, desligado pelo kill switch) e as esteiras do vendedor
(nao publicadas) foram escritos em branches separadas e cada um ganhou o seu proprio
caminho de opt-out. Com as duas mergeadas, um unico clique passava pelos dois:

    processor.py  gate deterministico  -> handle_optout_reply
                                       -> apply_optout_side_effects
                                       -> move_lead_deals_to_blacklist
                                          (UPDATE deals SET pipeline_id = BLACKLIST,
                                           em TODOS os deals do lead, sem fechar card)
    processor.py  gate do button flow  -> run_button_flow -> _aplicar_optout
                                       -> effects._mover_deal
                                          (if pipeline_id != PIPELINE_RECUPERACAO:
                                              return False)   <- agora recusa

Resultado: a etapa "Descadastrado" nunca recebia ninguem — exatamente a regressao que
`button_flow/effects.py:147-158` declara ter consertado. Nenhum teste cobria a
coexistencia, porque em cada branch isolada ela nao existia.

O rotulo do botao de saida do bot e literalmente "Parar mensagens"
(`button_flow/flows.py:95`), e `is_optout_reply` casa com ele por igualdade
normalizada — entao a colisao nao era teorica, era o caminho feliz do bot.
"""
from unittest.mock import patch

import pytest

from app.buffer.processor import _optout_deterministico_cabe


CANAL_HUMANO = {"id": "ch-joao", "mode": "human"}
CANAL_IA = {"id": "ch-valeria", "mode": "ai"}
CONVERSA = {"id": "conv-1", "channel_id": "ch-joao"}


def _cabe(channel, lead, *, button_flow: bool, valeria: bool = True) -> bool:
    """Chama o predicado com os dois colaboradores externos sob controle."""
    with patch("app.buffer.processor.is_button_flow_conversation", return_value=button_flow), \
         patch("app.buffer.processor.VALERIA_ENABLED", valeria):
        return _optout_deterministico_cabe(channel, lead, CONVERSA)


class TestAColisaoQueEsteArquivoTrava:
    def test_conversa_do_bot_de_botoes_NAO_roda_o_caminho_deterministico(self):
        """O conserto. Sem isto, um clique em "Parar mensagens" roda os dois caminhos e
        a etapa "Descadastrado" fica vazia para sempre."""
        assert _cabe(CANAL_HUMANO, {"ai_enabled": False}, button_flow=True) is False

    def test_fora_do_bot_o_caminho_deterministico_continua_valendo(self):
        """O publico das esteiras — numero do vendedor, sem bot — nao pode perder a
        unica saida digna que tem."""
        assert _cabe(CANAL_HUMANO, {"ai_enabled": False}, button_flow=False) is True


class TestQuemArbitraOTurno:
    def test_canal_humano_sem_bot_arbitra_deterministicamente(self):
        assert _cabe(CANAL_HUMANO, {"ai_enabled": True}, button_flow=False) is True

    def test_lead_com_ia_desligada_arbitra_deterministicamente(self):
        assert _cabe(CANAL_IA, {"ai_enabled": False}, button_flow=False) is True

    def test_valeria_desligada_arbitra_deterministicamente(self):
        assert _cabe(CANAL_IA, {"ai_enabled": True}, button_flow=False, valeria=False) is True

    def test_publico_da_IA_fica_com_o_LLM(self):
        """Para quem a ValerIA atende valem a escada do prompt e o guardrail
        anti-falso-positivo de 22/06 — o parser achata clique de botao em texto comum,
        entao blacklistar aqui viraria banimento por negativa reflexa digitada."""
        assert _cabe(CANAL_IA, {"ai_enabled": True}, button_flow=False) is False

    def test_ai_enabled_ausente_nao_conta_como_desligado(self):
        """A checagem e `is False`, nao falsy: lead sem a chave e publico da IA."""
        assert _cabe(CANAL_IA, {}, button_flow=False) is False


class TestOrdemDasChecagens:
    def test_publico_da_IA_nem_consulta_o_button_flow(self):
        """`is_button_flow_conversation` le o banco. Para o publico da IA a resposta ja
        esta decidida, entao a consulta nao deve acontecer."""
        with patch("app.buffer.processor.is_button_flow_conversation") as m, \
             patch("app.buffer.processor.VALERIA_ENABLED", True):
            assert _optout_deterministico_cabe(CANAL_IA, {"ai_enabled": True}, CONVERSA) is False
            m.assert_not_called()

    @pytest.mark.parametrize("mode", ["human", "ai"])
    def test_kill_switch_do_bot_devolve_o_turno_ao_caminho_deterministico(self, mode):
        """`is_button_flow_conversation` sai em False com RECUPERACAO_ENABLED desligado,
        sem tocar no banco. Com o bot off, ninguem fica sem saida."""
        assert _cabe({"id": "c", "mode": mode}, {"ai_enabled": False}, button_flow=False) is True
