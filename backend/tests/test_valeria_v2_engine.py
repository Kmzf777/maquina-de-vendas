"""Matriz nó × evento do motor v2 da ValerIA de botões, sem um único mock.

Cada teste cobre uma regra numerada do Task 5 do plano
(docs/superpowers/plans/2026-10-08-valeria-botoes-v2-vitrine.md), contra o
registry v2 real.
"""
import pytest

from app.button_flow import valeria_registry_v2 as r
from app.button_flow import valeria_engine_v2 as motor
from app.button_flow.engine import Clique, Texto
from app.button_flow.valeria_engine_v2 import DecisaoV2, TextoClassificado

NOS, TERM = r.NOS, r.TERMINAIS

MSG_ATACADO = "Olá! Tenho um comércio e quero revender café especial."
MSG_ATACADO_2 = "Olá! Quero saber mais sobre compra por atacado."
MSG_PL = "Olá! Quero café com a minha marca — já tenho CNPJ"
MSG_PL_2 = "Olá! Quero saber mais sobre ter a Marca Própria de Café."


def _est(node: str, ramo: str | None = "atacado", **extra) -> dict:
    e = {"flow": r.FLOW_ID, "node": node, "nudges": 0}
    if ramo:
        e["ramo"] = ramo
    e.update(extra)
    return e


def _clique(botao_id: str, titulo: str = "") -> Clique:
    return Clique(payload=botao_id, titulo=titulo)


def _tc(classe: str, conteudo: str = "texto", **kw) -> TextoClassificado:
    return TextoClassificado(conteudo=conteudo, classe=classe, **kw)


def _decidir(no, evento, estado=None, **kw) -> DecisaoV2:
    d = motor.decidir(no, evento, estado, NOS, TERM, **kw)
    assert isinstance(d, DecisaoV2)
    return d


# ── 1. primeira_tela ────────────────────────────────────────────────────────
@pytest.mark.parametrize("texto,tela", [
    (MSG_ATACADO, "QA_USO"), (MSG_ATACADO_2, "QA_USO"), (MSG_PL, "VP"), (MSG_PL_2, "VP"),
    ("oi", "N0"), ("", "N0"),
])
def test_primeira_tela_mensagens_prontas(texto, tela):
    assert motor.primeira_tela(texto) == tela


@pytest.mark.parametrize("texto", [
    "Olá! Tenho um comércio e quero revender café especial",   # sem o ponto final
    "Olá Tenho um comércio e quero revender café especial.",   # sem a exclamação
    "ola tenho um comercio e quero revender cafe especial",
    "  OLÁ!  Tenho um comércio,  e quero revender café especial!! ",
])
def test_primeira_tela_ignora_pontuacao_e_espacos(texto):
    assert motor.primeira_tela(texto) == "QA_USO"


def test_primeira_tela_pl_sem_travessao():
    assert motor.primeira_tela("Olá! Quero café com a minha marca já tenho CNPJ") == "VP"


def test_primeira_tela_variacao_editada_vai_para_n0():
    assert motor.primeira_tela("Olá! Tenho um comércio e quero revender café") == "N0"


# ── 2. Primeiro contato ─────────────────────────────────────────────────────
def test_primeiro_contato_mensagem_pronta_atacado_vai_para_as_perguntas():
    """F3: a mensagem pronta do atacado abre o "para quê", sem vitrine nem preço."""
    d = _decidir(None, Texto(MSG_ATACADO))
    assert d.proximo_no == "QA_USO"
    assert d.vitrine == "nenhuma"
    assert d.memoria == {"ramo": "atacado"}
    assert d.mensagem.botoes == NOS["QA_USO"].botoes
    assert "R$" not in d.mensagem.corpo


def test_primeiro_contato_mensagem_pronta_pl_vai_para_vp():
    d = _decidir(None, Texto(MSG_PL_2))
    assert d.proximo_no == "VP"
    assert d.vitrine == "completa"
    assert d.memoria == {"ramo": "private_label"}


def test_primeiro_contato_texto_qualquer_vai_para_n0():
    d = _decidir(None, Texto("oi, bom dia"))
    assert d.proximo_no == "N0"
    assert d.vitrine == "nenhuma"
    assert d.mensagem.corpo == NOS["N0"].corpo
    assert d.mensagem.botoes == NOS["N0"].botoes
    assert d.memoria == {}


@pytest.mark.parametrize("texto", ["pare", "  PARE ", "não quero mais", "me tira"])
def test_primeiro_contato_pare_vai_para_optout(texto):
    d = _decidir(None, Texto(texto))
    assert d.proximo_no == "T_OPTOUT"
    assert d.efeitos.optout is True


def test_primeiro_contato_clique_vai_para_n0():
    d = _decidir(None, _clique("qualquer"))
    assert d.proximo_no == "N0"


# ── 3. Nó desconhecido ──────────────────────────────────────────────────────
def test_no_desconhecido_vai_para_humano():
    d = _decidir("N_INEXISTENTE", _clique("x"), _est("N_INEXISTENTE"))
    assert d.proximo_no == "T_HUMANO"
    assert r.TAG_HUMANO in d.efeitos.tags


# ── 4. Opt-out ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("evento", [
    Texto("pare"),
    Texto("Não quero mais"),
    TextoClassificado(conteudo="pare", classe="RUIDO"),
    TextoClassificado(conteudo="tchau", classe="SAIR"),
])
@pytest.mark.parametrize("no", ["N0", "VA", "QA1", "QP2", "VO", "T_HANDOFF", "T_ADIAR"])
def test_optout_vence_tudo(evento, no):
    d = _decidir(no, evento, _est(no, ruidos=1))
    assert d.proximo_no == "T_OPTOUT"
    assert d.efeitos.optout is True


def test_optout_ja_registrado_nao_reenvia():
    d = _decidir("T_OPTOUT", Texto("pare"), _est("T_OPTOUT"))
    assert d.ignorar is True
    assert d.proximo_no == "T_OPTOUT"


@pytest.mark.parametrize("texto", [
    "não quero receber o kit", "cancela o envio da amostra", "me tira dessa lista",
])
def test_motor_so_casa_optout_por_igualdade(texto):
    """A rede ampla (gramática de parada) é do classificador, chamado ANTES do motor.

    No motor, só a lista fixa por igualdade: frases de venda da v2 como "não quero
    receber o kit" não podem virar opt-out irreversível aqui.
    """
    d = _decidir("VK", Texto(texto), _est("VK"))
    assert d.proximo_no != "T_OPTOUT"
    assert d.efeitos.optout is False


def test_nao_quero_trocar_de_fornecedor_nao_e_optout():
    d = _decidir("QA1", Texto("não quero trocar de fornecedor"), _est("QA1"))
    assert d.proximo_no != "T_OPTOUT"


# ── 5. Encerrado ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("terminal", ["T_HANDOFF", "T_HANDOFF_PL", "T_KIT"])
def test_terminal_encerrado_ignora(terminal):
    d = _decidir(terminal, _tc("PERGUNTA", "e o frete?"), _est(terminal))
    assert d.ignorar is True
    assert d.proximo_no == terminal
    assert d.mensagem is None


def test_t_adiar_nao_encerra_e_aceita_prazo():
    d = _decidir("T_ADIAR", _clique("snooze30"), _est("T_ADIAR", ramo="private_label"))
    assert d.proximo_no == "T_ADIADO"
    assert d.efeitos.recontato_dias == 30


# ── 6. Clique ───────────────────────────────────────────────────────────────
def test_clique_no_card_grava_interesse_e_vai_para_qa1_com_intencao():
    d = _decidir("VA", _clique("card:classico", "Quero esse"), _est("VA"))
    assert d.proximo_no == "QA1"
    assert d.memoria == {"interesse": "classico", "ruidos": 0}
    assert d.criterios == {"purchase_intent": "clear"}
    assert d.repasse_motivo is None
    assert d.mensagem.corpo == NOS["QA1"].corpo


def test_clique_no_card_pl_vai_para_qp1_sem_purchase_intent():
    d = _decidir("VP", _clique("card:embalagem_cliente"), _est("VP", ramo="private_label"))
    assert d.proximo_no == "QP1"
    assert d.memoria["interesse"] == "embalagem_cliente"
    assert d.criterios == {}


def test_clique_em_card_inexistente_e_ruido():
    d = _decidir("VA", _clique("card:nao_existe"), _est("VA"))
    assert d.proximo_no == "VA"
    assert d.marcar_nudge is True


def test_clique_pedido_vai_para_qa1_com_purchase_intent():
    d = _decidir("VA", _clique("pedido"), _est("VA", ruidos=1))
    assert d.proximo_no == "QA1"
    assert d.criterios == {"purchase_intent": "clear"}
    assert d.memoria["respostas"] == {"VA": "pedido"}
    assert d.memoria["ruidos"] == 0


def test_clique_grava_criterio_do_botao_e_acumula_respostas():
    est = _est("QA1", respostas={"VA": "pedido"})
    d = _decidir("QA1", _clique("cafeteria"), est)
    assert d.proximo_no == "QA2"
    assert d.criterios == {"segment": "cafeteria"}
    assert d.memoria["respostas"] == {"VA": "pedido", "QA1": "cafeteria"}


def test_qa2_vai_para_t_handoff_com_motivo():
    d = _decidir("QA2", _clique("ate100", "30 a 100 kg"), _est("QA2"))
    assert d.proximo_no == "T_HANDOFF"
    assert d.efeitos.handoff is True
    assert d.criterios == {"monthly_volume_kg": 65}
    assert d.repasse_motivo == 'clicou "30 a 100 kg"'


def test_qp1_tenho_graos_vai_para_handoff_pl_com_motivo():
    d = _decidir("QP1", _clique("tenho_graos"), _est("QP1", ramo="private_label"))
    assert d.proximo_no == "T_HANDOFF_PL"
    assert d.repasse_motivo == 'clicou "Já tenho os grãos"'


def test_qp2_criar_zero_menos100_vai_para_pl_abaixo():
    est = _est("QP2", ramo="private_label", respostas={"QP1": "criar_zero"})
    d = _decidir("QP2", _clique("menos100"), est)
    assert d.proximo_no == "PL_ABAIXO"
    assert d.mensagem.corpo == NOS["PL_ABAIXO"].corpo
    assert d.memoria["respostas"] == {"QP1": "criar_zero", "QP2": "menos100"}
    assert d.efeitos.handoff is False


def test_qp2_tenho_marca_menos100_vai_para_handoff_pl():
    est = _est("QP2", ramo="private_label", respostas={"QP1": "tenho_marca"})
    d = _decidir("QP2", _clique("menos100"), est)
    assert d.proximo_no == "T_HANDOFF_PL"
    assert d.repasse_motivo == 'clicou "Menos de 100"'


def test_qp2_sem_resposta_de_qp1_vai_para_handoff_pl():
    d = _decidir("QP2", _clique("mais500"), _est("QP2", ramo="private_label"))
    assert d.proximo_no == "T_HANDOFF_PL"


def test_pl_abaixo_kit_e_adiar():
    est = _est("PL_ABAIXO", ramo="private_label")
    assert _decidir("PL_ABAIXO", _clique("quero_kit"), est).proximo_no == "T_KIT"
    d = _decidir("PL_ABAIXO", _clique("depois"), est)
    assert d.proximo_no == "T_ADIAR"
    assert d.mensagem.botoes == r.BOTOES_PRAZO


def test_duvida_grava_retorno_e_faq_volta_com_acoes():
    d = _decidir("VA", _clique("duvida"), _est("VA"))
    assert d.proximo_no == "VD_A"
    assert d.memoria["retorno"] == "VA"
    assert d.mensagem.botoes == NOS["VD_A"].botoes

    d2 = _decidir("VD_A", _clique("faq_frete"), _est("VD_A", retorno="VA"))
    assert d2.faq == "frete"
    assert d2.proximo_no == "VA"
    assert d2.vitrine == "acoes"
    assert d2.mensagem.corpo == r.CORPO_ACOES
    assert d2.mensagem.botoes == NOS["VA"].botoes
    assert d2.marcar_nudge is False


def test_faq_sem_retorno_volta_a_vitrine_do_ramo():
    d = _decidir("VD_P", _clique("faq_prazo_pl"), _est("VD_P", ramo="private_label"))
    assert d.faq == "prazo_pl"
    assert d.proximo_no == "VP"
    assert d.vitrine == "acoes"


def test_faq_com_retorno_em_no_comum_reenvia_a_tela_normal():
    d = _decidir("VD_A", _clique("faq_minimo"), _est("VD_A", retorno="QA1"))
    assert d.proximo_no == "QA1"
    assert d.vitrine == "nenhuma"
    assert d.mensagem.corpo == NOS["QA1"].corpo
    assert d.marcar_nudge is False


def test_faq_outra_vai_para_vo():
    d = _decidir("VD_A", _clique("faq_outra"), _est("VD_A", retorno="VA"))
    assert d.proximo_no == "VO"
    assert d.mensagem.corpo == NOS["VO"].corpo


def test_faq_vendedor_vai_para_handoff_com_motivo():
    d = _decidir("VD_P", _clique("faq_vendedor", "Falar com vendedor"),
                 _est("VD_P", ramo="private_label"))
    assert d.proximo_no == "T_HANDOFF_PL"
    assert d.repasse_motivo == 'clicou "Falar com vendedor"'


def test_vk_ver_precos_reenvia_tabela():
    d = _decidir("VK", _clique("ver_precos"), _est("VK", ramo="private_label"))
    assert d.proximo_no == "VP"
    assert d.vitrine == "tabela"
    assert d.mensagem.botoes == NOS["VP"].botoes


@pytest.mark.parametrize("ramo,terminal", [("atacado", "T_HANDOFF"),
                                           ("private_label", "T_HANDOFF_PL")])
def test_vk_vendedor_handoff_do_ramo(ramo, terminal):
    d = _decidir("VK", _clique("vendedor"), _est("VK", ramo=ramo))
    assert d.proximo_no == terminal
    assert d.efeitos.handoff is True
    assert d.repasse_motivo == 'clicou "Falar com vendedor"'


def test_vk_sem_ramo_no_estado_vai_para_o_joao():
    """VK tem ramo "entrada" no registry: sem ramo no estado, não há handoff de ramo,
    e quem pediu vendedor vai ao João (T_HUMANO não manda nada nem atribui ninguém)."""
    d = _decidir("VK", _clique("vendedor"), _est("VK", ramo=None))
    assert d.proximo_no == "T_HANDOFF"
    assert d.repasse_motivo == 'clicou "Falar com vendedor"'


def test_vk_quero_kit_vai_para_t_kit_com_motivo():
    d = _decidir("VK", _clique("quero_kit", "Quero o kit"), _est("VK"))
    assert d.proximo_no == "T_KIT"
    assert d.efeitos.handoff is True
    assert d.repasse_motivo == 'clicou "Quero o kit"'


@pytest.mark.parametrize("no,botao,vitrine,ramo", [
    ("N0", "marca", "VP", "private_label"),
    ("QA_CNPJ", "cnpj", "VA", "atacado"),
    ("QA_CNPJ", "mei", "VA", "atacado"),
])
def test_clique_que_entra_na_vitrine_mostra_completa_e_grava_ramo(no, botao, vitrine, ramo):
    d = _decidir(no, _clique(botao), _est(no, ramo=None))
    assert d.proximo_no == vitrine
    assert d.vitrine == "completa"
    assert d.memoria["ramo"] == ramo


def test_ruido_zera_apos_clique():
    d = _decidir("QA1", _clique("loja"), _est("QA1", ruidos=1))
    assert d.memoria["ruidos"] == 0


def test_clique_nao_casado_e_ruido():
    d = _decidir("QA1", _clique("botao_antigo"), _est("QA1"))
    assert d.proximo_no == "QA1"
    assert d.marcar_nudge is True
    assert d.memoria == {"ruidos": 1}


def test_clique_de_rotulo_antigo_ainda_resolve():
    est = _est("QA1", rotulos_antigos={"QA1": {"Cafeteria": "cafeteria"}})
    d = _decidir("QA1", Clique(payload="Cafeteria", titulo="Cafeteria"), est)
    assert d.proximo_no == "QA2"


# ── 7. TextoClassificado ────────────────────────────────────────────────────
def test_classificado_botao_equivale_a_clique():
    est = _est("QA1", ruidos=1)
    d_txt = _decidir("QA1", _tc("BOTAO", "tenho uma cafeteria", botao_id="cafeteria"), est)
    d_clk = _decidir("QA1", _clique("cafeteria"), est)
    assert d_txt == d_clk
    assert d_txt.proximo_no == "QA2"


def test_classificado_botao_de_card_equivale_ao_toque_no_card():
    est = _est("VA")
    for bid in ("card:suave", "suave"):
        d = _decidir("VA", _tc("BOTAO", "quero o suave", botao_id=bid), est)
        assert d.proximo_no == "QA1"
        assert d.memoria["interesse"] == "suave"


def test_classificado_botao_de_outra_tela_e_ruido():
    d = _decidir("QA1", _tc("BOTAO", "uns 200 kg", botao_id="mais100"), _est("QA1"))
    assert d.proximo_no == "QA1"
    assert d.marcar_nudge is True


@pytest.mark.parametrize("no,ramo", [("QA1", "atacado"), ("QA2", "atacado"),
                                      ("QP1", "private_label"), ("QP2", "private_label")])
def test_classificado_preco_na_qualificacao_manda_tabela_e_fica_no_no(no, ramo):
    """Preço no meio da qualificação: tabela do ramo + a MESMA tela; o nó não volta
    à vitrine (senão o lead perde a elegibilidade do repasse automático)."""
    d = _decidir(no, _tc("FAQ", "qual o valor do quilo?", faq_id="preco"),
                 _est(no, ramo=ramo, ruidos=1))
    assert d.proximo_no == no
    assert d.tabela_antes is True
    assert d.vitrine == "nenhuma"
    assert d.faq is None
    assert d.mensagem.corpo == NOS[no].corpo
    assert d.mensagem.botoes == NOS[no].botoes
    assert d.memoria == {"ruidos": 0}
    assert d.efeitos.handoff is False


@pytest.mark.parametrize("no,vitrine", [("VD_A", "VA"), ("PL_ABAIXO", "VP"), ("VA", "VA")])
def test_classificado_preco_fora_da_qualificacao_reenvia_tabela_da_vitrine(no, vitrine):
    ramo = r.RAMO_DO_NO[vitrine]
    d = _decidir(no, _tc("FAQ", "quanto é?", faq_id="preco"), _est(no, ramo=ramo, ruidos=1))
    assert d.proximo_no == vitrine
    assert d.vitrine == "tabela"
    assert d.tabela_antes is False
    assert d.memoria["ruidos"] == 0


def test_classificado_preco_sem_ramo_vai_para_n0_com_corpo_de_preco():
    """Não reenvia a saudação idêntica: explica que o preço depende do caso."""
    d = _decidir("N0", _tc("FAQ", "quanto custa?", faq_id="preco"), _est("N0", ramo=None))
    assert d.proximo_no == "N0"
    assert d.vitrine == "nenhuma"
    assert d.mensagem.corpo == r.CORPO_N0_PRECO
    assert d.mensagem.botoes == NOS["N0"].botoes
    assert d.memoria == {"ruidos": 0}


def test_vo_preco_sem_ramo_usa_corpo_de_preco_do_n0():
    d = _decidir("VO", _tc("FAQ", "quanto custa?", faq_id="preco"), _est("VO", ramo=None))
    assert d.proximo_no == "N0"
    assert d.mensagem.corpo == r.CORPO_N0_PRECO


def test_faq_em_qa1_responde_e_reapresenta_qa1():
    d = _decidir("QA1", _tc("FAQ", "tem frete grátis?", faq_id="frete"),
                 _est("QA1", ruidos=1))
    assert d.faq == "frete"
    assert d.proximo_no == "QA1"
    assert d.mensagem.corpo == NOS["QA1"].corpo
    assert d.mensagem.botoes == NOS["QA1"].botoes
    assert d.vitrine == "nenhuma"
    assert d.memoria == {"ruidos": 0}


def test_faq_na_vitrine_responde_e_reapresenta_acoes():
    d = _decidir("VP", _tc("FAQ", "qual o prazo?", faq_id="prazo_pl"),
                 _est("VP", ramo="private_label"))
    assert d.faq == "prazo_pl"
    assert d.proximo_no == "VP"
    assert d.vitrine == "acoes"


def test_faq_invalida_para_o_ramo_e_ruido():
    d = _decidir("QA1", _tc("FAQ", "e o fotolito?", faq_id="fotolito"), _est("QA1"))
    assert d.faq is None
    assert d.marcar_nudge is True


def test_pergunta_com_ramo_vai_para_handoff_do_ramo_com_texto():
    texto = "vocês fazem café com açaí?"
    d = _decidir("QA2", _tc("PERGUNTA", texto), _est("QA2"))
    assert d.proximo_no == "T_HANDOFF"
    assert d.efeitos.handoff is True
    assert d.repasse_motivo == f"PERGUNTA: {texto}"


def test_pergunta_corta_o_texto_em_200():
    d = _decidir("QP1", _tc("PERGUNTA", "x" * 500), _est("QP1", ramo="private_label"))
    assert d.proximo_no == "T_HANDOFF_PL"
    assert d.repasse_motivo == "PERGUNTA: " + "x" * 200


def test_vendedor_com_ramo_vai_para_handoff():
    d = _decidir("VP", _tc("VENDEDOR", "quero falar com alguém"), _est("VP", ramo="private_label"))
    assert d.proximo_no == "T_HANDOFF_PL"
    assert d.repasse_motivo == "VENDEDOR: quero falar com alguém"


def test_pergunta_na_exportacao_vai_para_arthur():
    d = _decidir("E2", _tc("PERGUNTA", "precisa de certificado?"), _est("E2", ramo=None))
    assert d.proximo_no == "T_HANDOFF_ARTHUR"


def test_pergunta_sem_ramo_vai_para_o_joao():
    """Sem ramo, a pergunta real vai ao João (atende tudo menos exportação):
    T_HUMANO não manda mensagem nem atribui vendedor — o lead ficava no silêncio."""
    d = _decidir("N0", _tc("PERGUNTA", "vocês têm loja física?"), _est("N0", ramo=None))
    assert d.proximo_no == "T_HANDOFF"
    assert d.efeitos.handoff is True
    assert d.repasse_motivo == "PERGUNTA: vocês têm loja física?"


def test_vendedor_sem_ramo_vai_para_o_joao():
    d = _decidir("N0", _tc("VENDEDOR", "quero um atendente"), _est("N0", ramo=None))
    assert d.proximo_no == "T_HANDOFF"
    assert d.repasse_motivo == "VENDEDOR: quero um atendente"


@pytest.mark.parametrize("classe", ["PERGUNTA", "VENDEDOR"])
def test_pergunta_e_vendedor_em_consumo_vao_para_o_joao(classe):
    d = _decidir("C1", _tc(classe, "dá pra comprar 1 pacote?"), _est("C1", ramo=None))
    assert d.proximo_no == "T_HANDOFF"
    assert d.repasse_motivo == f"{classe}: dá pra comprar 1 pacote?"


def test_segundo_ruido_em_consumo_vai_ao_joao():
    """F3: era T_HUMANO, que não avisava ninguém ("Valéria muda" da F2)."""
    d = _decidir("C1", _tc("RUIDO", "?"), _est("C1", ramo=None, ruidos=1))
    assert d.proximo_no == "T_HANDOFF" and d.efeitos.handoff is True
    assert d.repasse_motivo == motor.MOTIVO_RUIDO


def test_vk_pergunta_usa_ramo_do_estado():
    d = _decidir("VK", _tc("PERGUNTA", "o kit tem quantos cafés?"),
                 _est("VK", ramo="private_label"))
    assert d.proximo_no == "T_HANDOFF_PL"


def test_ruido_primeiro_nudge_segundo_handoff():
    d1 = _decidir("QA1", _tc("RUIDO", "bom dia"), _est("QA1"))
    assert d1.proximo_no == "QA1"
    assert d1.marcar_nudge is True
    assert d1.mensagem.corpo == r.CORPO_NUDGE
    assert d1.mensagem.botoes == NOS["QA1"].botoes
    assert d1.memoria == {"ruidos": 1}

    d2 = _decidir("QA1", _tc("RUIDO", "ok"), _est("QA1", ruidos=1))
    assert d2.proximo_no == "T_HANDOFF"
    assert d2.repasse_motivo == "sem resposta a botões (2 mensagens não entendidas)"


def test_ruido_usa_corpo_nudge_da_tela():
    d = _decidir("QA1", _tc("RUIDO", "bom dia"), _est("QA1"), corpo_nudge="toca aí 👇")
    assert d.mensagem.corpo == "toca aí 👇"


def test_ruido_na_vitrine_reenvia_acoes():
    d = _decidir("VA", _tc("RUIDO", "hmm"), _est("VA"))
    assert d.proximo_no == "VA"
    assert d.vitrine == "acoes"
    assert d.marcar_nudge is True
    assert d.mensagem.botoes == NOS["VA"].botoes


def test_segundo_ruido_sem_ramo_vai_ao_joao():
    d = _decidir("N0", _tc("RUIDO", "?"), _est("N0", ramo=None, ruidos=1))
    assert d.proximo_no == "T_HANDOFF"
    assert d.repasse_motivo == motor.MOTIVO_RUIDO


def test_classe_desconhecida_e_ruido():
    d = _decidir("QA1", _tc("INVENTADA", "x"), _est("QA1"))
    assert d.marcar_nudge is True


# ── 7 (VO) ──────────────────────────────────────────────────────────────────
def test_vo_pergunta_vai_para_handoff():
    d = _decidir("VO", _tc("PERGUNTA", "vocês entregam em Manaus?"), _est("VO", retorno="VA"))
    assert d.proximo_no == "T_HANDOFF"
    assert d.repasse_motivo == "PERGUNTA: vocês entregam em Manaus?"


@pytest.mark.parametrize("classe", ["RUIDO", "VENDEDOR", "BOTAO"])
def test_vo_qualquer_outra_classe_vai_para_handoff_com_texto(classe):
    d = _decidir("VO", _tc(classe, "minha dúvida", botao_id="x" if classe == "BOTAO" else None),
                 _est("VO", ramo="private_label", retorno="VP"))
    assert d.proximo_no == "T_HANDOFF_PL"
    assert d.repasse_motivo == "PERGUNTA: minha dúvida"


def test_vo_texto_sem_classificar_vai_para_handoff():
    d = _decidir("VO", Texto("minha dúvida"), _est("VO", retorno="VA"))
    assert d.proximo_no == "T_HANDOFF"
    assert d.repasse_motivo == "PERGUNTA: minha dúvida"


def test_vo_faq_responde_e_volta_ao_retorno():
    d = _decidir("VO", _tc("FAQ", "aceita boleto?", faq_id="pagamento"),
                 _est("VO", retorno="VA"))
    assert d.faq == "pagamento"
    assert d.proximo_no == "VA"
    assert d.vitrine == "acoes"


def test_vo_faq_preco_reenvia_tabela():
    d = _decidir("VO", _tc("FAQ", "quanto é?", faq_id="preco"),
                 _est("VO", ramo="private_label", retorno="VP"))
    assert d.proximo_no == "VP"
    assert d.vitrine == "tabela"


def test_vo_sem_ramo_vai_para_o_joao():
    d = _decidir("VO", _tc("PERGUNTA", "oi?"), _est("VO", ramo=None))
    assert d.proximo_no == "T_HANDOFF"


# ── 8. Texto puro (classificador não rodou) ─────────────────────────────────
def test_texto_puro_e_ruido():
    d1 = _decidir("QP1", Texto("hmm"), _est("QP1", ramo="private_label"))
    assert d1.proximo_no == "QP1"
    assert d1.marcar_nudge is True
    d2 = _decidir("QP1", Texto("hmm"), _est("QP1", ramo="private_label", ruidos=1))
    assert d2.proximo_no == "T_HANDOFF_PL"


# ── Pureza ──────────────────────────────────────────────────────────────────
def test_estado_none_ou_lixo_nao_estoura():
    for estado in (None, {}, {"ruidos": "x", "respostas": "lixo", "ramo": 3}):
        d = _decidir("QA1", _tc("RUIDO", "a"), estado)
        assert d.proximo_no == "QA1"


def test_mesma_entrada_mesma_saida():
    est = _est("VA")
    ev = _clique("card:microlote")
    assert _decidir("VA", ev, est) == _decidir("VA", ev, est)


# ── Follow-ups da revisão ───────────────────────────────────────────────────
def test_faq_em_t_adiar_responde_e_reoferece_os_prazos():
    d = _decidir("T_ADIAR", _tc("FAQ", "e o frete?", faq_id="frete"),
                 _est("T_ADIAR", ramo="private_label"))
    assert d.faq == "frete"
    assert d.proximo_no == "T_ADIAR"
    assert d.mensagem.botoes == r.BOTOES_PRAZO
    assert d.efeitos.tags == ()          # o terminal não é reaplicado
    assert d.efeitos.recontato_dias is None


def test_preco_em_consumo_vai_para_o_joao():
    d = _decidir("C1", _tc("FAQ", "quanto custa?", faq_id="preco"), _est("C1", ramo=None))
    assert d.proximo_no == "T_HANDOFF"
    assert d.repasse_motivo == "PERGUNTA: quanto custa?"


def test_preco_em_exportacao_vai_para_arthur():
    d = _decidir("E3", _tc("FAQ", "qual o preço FOB?", faq_id="preco"), _est("E3", ramo=None))
    assert d.proximo_no == "T_HANDOFF_ARTHUR"
    assert d.repasse_motivo == "PERGUNTA: qual o preço FOB?"


def test_retorno_corrompido_vai_para_humano():
    d = _decidir("VD_A", _clique("faq_frete"), _est("VD_A", retorno="NO_QUE_SUMIU"))
    assert d.proximo_no == "T_HUMANO"


def test_retorno_nao_texto_cai_na_vitrine_do_ramo():
    d = _decidir("VD_A", _clique("faq_frete"), _est("VD_A", retorno=["VA"]))
    assert d.proximo_no == "VA"
    assert d.faq == "frete"


def test_botao_classificado_em_t_adiar_mantem_dias():
    d = _decidir("T_ADIAR", _tc("BOTAO", "daqui uns 2 meses", botao_id="snooze60"),
                 _est("T_ADIAR", ramo="private_label"))
    assert d.proximo_no == "T_ADIADO"
    assert d.efeitos.recontato_dias == 60


@pytest.mark.parametrize("qp1", [["criar_zero"], {"x": 1}, 7, None])
def test_respostas_qp1_corrompida_nao_estoura(qp1):
    est = _est("QP2", ramo="private_label", respostas={"QP1": qp1})
    d = _decidir("QP2", _clique("menos100"), est)
    assert d.proximo_no == "T_HANDOFF_PL"


def test_botao_classificado_que_repassa_usa_o_texto_no_motivo():
    d = _decidir("QA2", _tc("BOTAO", "uns 200 kg por mês", botao_id="mais100"), _est("QA2"))
    assert d.proximo_no == "T_HANDOFF"
    assert d.repasse_motivo == 'escreveu "uns 200 kg por mês"'


def test_botao_classificado_handoff_especial_usa_o_texto_no_motivo():
    d = _decidir("VK", _tc("BOTAO", "x" * 300, botao_id="vendedor"), _est("VK"))
    assert d.proximo_no == "T_HANDOFF"
    assert d.repasse_motivo == f'escreveu "{"x" * 200}"'


def test_clique_que_repassa_continua_com_rotulo_no_motivo():
    d = _decidir("QA2", _clique("mais100"), _est("QA2"))
    assert d.repasse_motivo == 'clicou "Mais de 100 kg"'


# ── Card tocado fora da vitrine (carrossel antigo ainda na tela do lead) ───
@pytest.mark.parametrize("no", ["VD_A", "VK", "QA1", "QA2", "VO"])
def test_card_atacado_tocado_em_outro_no_do_ramo_vale(no):
    d = _decidir(no, _clique("card:suave", "Quero esse"), _est(no, ramo="atacado", ruidos=1))
    assert d.proximo_no == "QA1"
    assert d.memoria == {"interesse": "suave", "ruidos": 0}
    assert d.criterios == {"purchase_intent": "clear"}
    assert d.marcar_nudge is False


@pytest.mark.parametrize("no", ["VD_P", "VK", "QP1", "QP2", "PL_ABAIXO", "VO"])
def test_card_pl_tocado_em_outro_no_do_ramo_vale(no):
    d = _decidir(no, _clique("card:embalagem_canastra"), _est(no, ramo="private_label"))
    assert d.proximo_no == "QP1"
    assert d.memoria["interesse"] == "embalagem_canastra"
    assert d.criterios == {}


def test_card_de_outro_ramo_e_ruido():
    d = _decidir("QP1", _clique("card:suave"), _est("QP1", ramo="private_label"))
    assert d.proximo_no == "QP1"
    assert d.marcar_nudge is True


def test_card_sem_ramo_e_ruido():
    d = _decidir("VK", _clique("card:suave"), _est("VK", ramo=None))
    assert d.proximo_no == "VK"
    assert d.marcar_nudge is True


def test_card_inexistente_em_outro_no_e_ruido():
    d = _decidir("QA1", _clique("card:nao_existe"), _est("QA1"))
    assert d.proximo_no == "QA1"
    assert d.marcar_nudge is True


# ── Mensagem pronta do anúncio reenviada no meio do fluxo ──────────────────
@pytest.mark.parametrize("evento", [
    Texto(MSG_PL),
    TextoClassificado(conteudo=MSG_PL_2, classe="RUIDO"),
    TextoClassificado(conteudo=MSG_PL_2 + "!", classe="PERGUNTA"),
])
@pytest.mark.parametrize("no", ["N0", "QA1", "VD_A", "VO", "C1", "E2"])
def test_mensagem_pronta_no_meio_do_fluxo_reabre_a_vitrine(evento, no):
    d = _decidir(no, evento, _est(no, ramo="atacado", ruidos=1))
    assert d.proximo_no == "VP"
    assert d.vitrine == "completa"
    assert d.memoria == {"ramo": "private_label", "ruidos": 0}
    assert d.marcar_nudge is False


def test_mensagem_pronta_em_t_adiar_nao_reabre_vitrine():
    d = _decidir("T_ADIAR", Texto(MSG_ATACADO), _est("T_ADIAR"))
    assert d.proximo_no != "VA"


def test_mensagem_pronta_em_terminal_encerrado_ignora():
    d = _decidir("T_HANDOFF", Texto(MSG_ATACADO), _est("T_HANDOFF"))
    assert d.ignorar is True


# ── F3 (06/11/2026): perguntas antes da vitrine e desqualificação ───────────
@pytest.mark.parametrize("no,botao", [("N0", "negocio"), ("C1", "quantidade")])
def test_quem_ja_disse_que_revende_vai_ao_volume(no, botao):
    d = _decidir(no, _clique(botao), _est(no, ramo=None))
    assert d.proximo_no == "QA_VOL"
    assert d.memoria["ramo"] == "atacado"
    assert d.vitrine == "nenhuma"


def test_caminho_feliz_uso_volume_cnpj_vitrine_pedido_handoff():
    est = _est("QA_USO")
    d = _decidir("QA_USO", _clique("revender"), est)
    assert d.proximo_no == "QA_VOL" and d.desqualificacao is None
    est = {**est, **d.memoria, "node": "QA_VOL"}
    d = _decidir("QA_VOL", _clique("ate100"), est)
    assert d.proximo_no == "QA_CNPJ" and d.criterios == {"monthly_volume_kg": 65}
    est = {**est, **d.memoria, "node": "QA_CNPJ"}
    d = _decidir("QA_CNPJ", _clique("mei"), est)
    assert d.proximo_no == "VA" and d.vitrine == "completa"
    est = {**est, **d.memoria, "node": "VA"}
    d = _decidir("VA", _clique("pedido"), est)
    assert d.proximo_no == "QA1"
    est = {**est, **d.memoria, "node": "QA1"}
    # Volume já veio do QA_VOL: QA1 vai direto ao João, sem perguntar de novo.
    d = _decidir("QA1", _clique("cafeteria", "Cafeteria"), est)
    assert d.proximo_no == "T_HANDOFF" and d.efeitos.handoff is True
    assert d.repasse_motivo == 'clicou "Cafeteria"'


def test_qa1_sem_volume_anterior_ainda_pergunta_o_qa2():
    d = _decidir("QA1", _clique("cafeteria"), _est("QA1"))
    assert d.proximo_no == "QA2"


def test_consumo_proprio_vai_a_loja_desqualificado_sem_repasse():
    d = _decidir("QA_USO", _clique("consumo"), _est("QA_USO"))
    assert d.proximo_no == "C1"
    assert d.desqualificacao == "consumidor_final"
    assert d.efeitos.handoff is False
    assert d.memoria["ramo"] == "consumo"


def test_n0_consumo_tambem_e_consumidor_final():
    d = _decidir("N0", _clique("consumo"), _est("N0", ramo=None))
    assert d.proximo_no == "C1" and d.desqualificacao == "consumidor_final"


def test_sem_cnpj_vai_ao_terminal_com_tag_e_sem_repasse():
    d = _decidir("QA_CNPJ", _clique("sem_cnpj"), _est("QA_CNPJ"))
    assert d.proximo_no == "T_SEM_CNPJ"
    assert d.desqualificacao == "sem_cnpj"
    assert d.efeitos.handoff is False
    assert d.efeitos.tags == ("Atacado sem CNPJ",)
    assert d.repasse_motivo is None


def test_t_sem_cnpj_encerra():
    d = _decidir("T_SEM_CNPJ", Texto("abri o mei"), _est("T_SEM_CNPJ"))
    assert d.ignorar is True


@pytest.mark.parametrize("no", ["QA_USO", "QA_VOL", "QA_CNPJ"])
def test_preco_antes_da_vitrine_primeira_vez_repete_a_pergunta(no):
    d = _decidir(no, _tc("FAQ", "quanto custa?", faq_id="preco"), _est(no))
    assert d.proximo_no == no
    assert d.vitrine == "nenhuma" and d.tabela_antes is False
    assert d.mensagem.corpo.startswith(r.PREFIXO_PRECO_ANTES)
    assert d.mensagem.corpo.endswith(NOS[no].corpo)
    assert d.mensagem.botoes == NOS[no].botoes
    assert d.memoria["preco_antes"] == 1


def test_preco_antes_da_vitrine_segunda_vez_manda_a_tabela():
    d = _decidir("QA_VOL", _tc("FAQ", "me passa o preço", faq_id="preco"),
                 _est("QA_VOL", preco_antes=1))
    assert d.proximo_no == "VA" and d.vitrine == "tabela"


def test_faq_antes_da_vitrine_responde_e_volta_a_pergunta():
    d = _decidir("QA_CNPJ", _tc("FAQ", "qual o mínimo?", faq_id="minimo"), _est("QA_CNPJ"))
    assert d.faq == "minimo" and d.proximo_no == "QA_CNPJ"


def test_mensagem_pronta_no_meio_volta_as_perguntas_se_nao_passou_do_cnpj():
    d = _decidir("QA_VOL", Texto(MSG_ATACADO), _est("QA_VOL"))
    assert d.proximo_no == "QA_USO" and d.vitrine == "nenhuma"


def test_mensagem_pronta_no_meio_volta_a_vitrine_se_ja_passou_do_cnpj():
    d = _decidir("QA1", Texto(MSG_ATACADO), _est("QA1", respostas={"QA_CNPJ": "cnpj"}))
    assert d.proximo_no == "VA" and d.vitrine == "completa"


# ── F3 (11/11/2026): terminal sem repasse reabre quando o lead pede gente ────
@pytest.mark.parametrize("terminal", sorted(r.TERMINAIS_QUE_REABREM))
def test_reabre_com_pergunta(terminal):
    d = _decidir(terminal, _tc("PERGUNTA", "como faço pra comprar?"), _est(terminal))
    assert d.ignorar is False and d.efeitos.handoff is True
    assert d.proximo_no == "T_HANDOFF"
    assert d.repasse_motivo == "PERGUNTA: como faço pra comprar?"


@pytest.mark.parametrize("terminal", sorted(r.TERMINAIS_QUE_REABREM))
@pytest.mark.parametrize("evento", [_tc("RUIDO", "obrigado"), Texto("obrigado"),
                                    _clique("botao_que_nao_existe")])
def test_reaberto_ignora_obrigado_e_lixo(terminal, evento):
    assert _decidir(terminal, evento, _est(terminal)).ignorar is True


def test_faq_depois_do_terminal_tambem_e_pergunta():
    d = _decidir("T_HUMANO", _tc("FAQ", "quanto custa o saco de café cru?", faq_id="preco"),
                 _est("T_HUMANO", ramo=None))
    assert d.proximo_no == "T_HANDOFF"


def test_vendedor_depois_do_adiamento_vai_ao_vendedor_do_ramo():
    d = _decidir("T_ADIADO", _tc("VENDEDOR", "quero falar"), _est("T_ADIADO", ramo="private_label"))
    assert d.proximo_no == "T_HANDOFF_PL"
    assert d.repasse_motivo == "VENDEDOR: quero falar"


def test_sim_quero_falar_depois_do_adiamento_vai_ao_arthur():
    """Tel. final 5468: tocou "Sim, quero falar" (E4) depois do "te chamo em 90 dias"."""
    d = _decidir("T_ADIADO", _clique("sim", "Sim, quero falar"), _est("T_ADIADO", ramo="exportacao"))
    assert d.proximo_no == "T_HANDOFF_ARTHUR" and d.efeitos.handoff is True
    assert d.repasse_motivo == 'clicou "Sim, quero falar" depois de T_ADIADO'


def test_sim_quero_falar_no_ramo_pl_vai_ao_joao_pl():
    d = _decidir("T_ADIADO", _clique("sim"), _est("T_ADIADO", ramo="private_label"))
    assert d.proximo_no == "T_HANDOFF_PL"


def test_t_optout_continua_ignorando_tudo():
    d = _decidir("T_OPTOUT", _tc("PERGUNTA", "oi?"), _est("T_OPTOUT"))
    assert d.ignorar is True


def test_c1_tenho_duvida_pede_a_pergunta():
    d = _decidir("C1", _clique("duvida"), _est("C1", ramo="consumo"))
    assert d.proximo_no == "VO"
