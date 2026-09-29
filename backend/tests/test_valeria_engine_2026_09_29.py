"""Matriz nó × evento do fluxo da ValerIA, sem um único mock.

O motor é um INTÉRPRETE do registry: acha o nó, casa o clique com um botão
declarado, devolve o destino declarado. Como a estrutura é dado, esta matriz
cobre o comportamento inteiro sem tocar em banco, rede ou relógio.
"""
import pytest

from app.button_flow import valeria_registry as reg
from app.button_flow import valeria_engine as motor
from app.button_flow.engine import Clique, Texto

VAZIO: dict = {}


def _clique(botao_id: str) -> Clique:
    return Clique(payload=botao_id, titulo="")


# ── Caminhos felizes ───────────────────────────────────────────────────────
def test_clique_vai_para_o_destino_declarado():
    d = motor.decidir("N0", _clique("negocio"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "N1"
    assert d.mensagem is not None
    assert d.mensagem.corpo == reg.NOS["N1"].corpo


def test_clique_grava_o_campo_do_score():
    d = motor.decidir("N1", _clique("cafeteria"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.criterios == {"segment": "cafeteria"}


def test_clique_em_terminal_de_handoff():
    d = motor.decidir("N5", _clique("sim"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_HANDOFF"
    assert d.efeitos.handoff is True
    assert reg.TAG_QUALIFICADO in d.efeitos.tags


def test_ramo_pl_vai_para_o_handoff_proprio_dele():
    """A maquete tem duas redações de handoff; são dois terminais."""
    d = motor.decidir("P4", _clique("sim"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_HANDOFF_PL"
    assert d.efeitos.handoff is True


def test_clique_de_rotulo_antigo_ainda_resolve():
    """Editar o rótulo na tela não pode matar quem recebeu a tela antiga."""
    estado = {"rotulos_antigos": {"N1": {"Cafeteria": "cafeteria"}}}
    d = motor.decidir("N1", Clique(payload="Cafeteria", titulo="Cafeteria"),
                      estado, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "N2"


# ── A trava de insistência ─────────────────────────────────────────────────
@pytest.mark.parametrize("nudges_antes,espera_bloqueio",
                         [(0, False), (1, False), (2, False), (3, True)])
def test_texto_livre_reenvia_ate_3_e_bloqueia_no_4o(nudges_antes, espera_bloqueio):
    estado = {"nudges": nudges_antes}
    d = motor.decidir("N1", Texto("quanto custa o kg?"), estado, reg.NOS, reg.TERMINAIS)
    if espera_bloqueio:
        assert d.proximo_no == "T_HUMANO"
        assert d.efeitos.silenciar_ia is True
        assert d.mensagem is None, "BLOCK não gasta mensagem"
    else:
        assert d.proximo_no == "N1", "nudge reenvia o MESMO nó"
        assert d.marcar_nudge is True
        assert d.mensagem is not None
        assert d.mensagem.corpo == reg.CORPO_NUDGE
        assert d.mensagem.botoes == reg.NOS["N1"].botoes, "mesmos botões do nó"


def test_contador_de_nudge_e_por_atendimento_nao_por_no():
    """Por nó, 17 nós dariam 51 nudges em vez de 3."""
    estado = {"nudges": 3}
    for no in ("N1", "N2", "P1", "E2"):
        d = motor.decidir(no, Texto("oi"), estado, reg.NOS, reg.TERMINAIS)
        assert d.proximo_no == "T_HUMANO", f"{no} deu nudge com o teto estourado"


def test_clique_valido_nao_gasta_nudge():
    estado = {"nudges": 2}
    d = motor.decidir("N1", _clique("cafeteria"), estado, reg.NOS, reg.TERMINAIS)
    assert d.marcar_nudge is False


# ── Opt-out sem IA ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("frase", ["pare", "PARAR", "parar", "sair",
                                   "me tira", "descadastrar", "não quero mais"])
def test_optout_por_lista_fechada_antes_do_contador(frase):
    d = motor.decidir("N2", Texto(frase), {"nudges": 0}, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_OPTOUT"
    assert d.efeitos.optout is True
    assert d.marcar_nudge is False, "opt-out não gasta nudge"


@pytest.mark.parametrize("frase", ["não quero trocar de fornecedor",
                                   "quero parar de comprar do meu fornecedor atual",
                                   "onde vocês ficam?"])
def test_frase_que_contem_a_palavra_nao_e_optout(frase):
    """Casamento por IGUALDADE normalizada, nunca substring."""
    d = motor.decidir("N2", Texto(frase), {"nudges": 0}, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "N2"
    assert d.efeitos.optout is False


def test_optout_vale_mesmo_com_o_teto_estourado():
    """Quem pede para sair sai, mesmo já tendo gasto os 3 nudges."""
    d = motor.decidir("N2", Texto("pare"), {"nudges": 3}, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_OPTOUT"


# ── "Ver outras opções": a topologia garante uma vez só ────────────────────
def test_ver_outras_vai_para_n5b_e_n5b_nao_reoferece():
    d = motor.decidir("N5", _clique("ver_outras"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "N5b"
    assert "ver_outras" not in {b.id for b in reg.NOS["N5b"].botoes}


# ── T_ADIAR pergunta QUANDO, nunca SE ──────────────────────────────────────
def test_nao_agora_vai_para_t_adiar_e_PERGUNTA_o_prazo():
    """Medido: 'ainda tenho estoque' não é um não — 4 de 9 voltaram e um fechou
    R$ 5.500. O terminal de adiamento tem mensagem e botões."""
    d = motor.decidir("N5", _clique("nao_agora"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_ADIAR"
    assert d.mensagem is not None, "T_ADIAR encerrou em vez de perguntar"
    assert len(d.mensagem.botoes) == 3, "os 30/60/90 de flows.PRAZOS"
    assert d.efeitos.optout is False, "adiar NÃO descarta o lead"


@pytest.mark.parametrize("prazo_id,dias", [("snooze30", 30), ("snooze60", 60),
                                            ("snooze90", 90)])
def test_clique_no_prazo_agenda_recontato(prazo_id, dias):
    d = motor.decidir("T_ADIAR", _clique(prazo_id), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.efeitos.recontato_dias == dias
    assert d.efeitos.optout is False


# ── Invariantes de segurança ───────────────────────────────────────────────
def test_clique_desconhecido_cai_no_nudge_nao_em_erro():
    d = motor.decidir("N1", _clique("id_que_nao_existe"), {"nudges": 0},
                      reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "N1"
    assert d.marcar_nudge is True


def test_no_desconhecido_entrega_ao_humano_em_vez_de_estourar():
    """flow_state corrompido não pode virar exceção no caminho do inbound."""
    d = motor.decidir("NAO_EXISTE", _clique("x"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_HUMANO"
    assert d.mensagem is None


def test_consumo_sem_clique_encerra_sem_descartar():
    """consumo.py: 'Consumo não é encerramento definitivo'. opt_out fica FALSE."""
    terminal = reg.TERMINAIS["T_FIM"]
    assert terminal.optout is False
    assert terminal.corpo == "", "T_FIM não gasta mensagem"
