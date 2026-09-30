"""O lead que toca "Em 30 dias" recebe resposta — e a estrutura mora no registry.

Três defeitos achados na implementação, todos no mesmo turno do fluxo:

1. SILÊNCIO. `T_ADIAR` pergunta "quando faz sentido eu te chamar de novo?" e
   oferece 30/60/90, mas nada declarava o que o lead vê DEPOIS do toque: o
   clique ia para `T_FIM`, cujo `corpo` vazio é o contrato de "não manda
   mensagem". O lead adiava e levava silêncio — no turno em que ele acabou de
   dizer que quer ser chamado de novo. A frase já existe em produção
   (`flows.MSG_PRAZO_FECHAMENTO`) e é REUSADA, não recopiada: segunda cópia de
   uma string é segundo dono.
2. ESTRUTURA NO MOTOR. Os três botões de prazo eram declarados em
   `valeria_engine.py`. Botão é estrutura, e estrutura mora no registry — é o
   invariante em que este fluxo inteiro se apoia.
3. DOIS TIPOS `Botao` no mesmo campo. `Mensagem.botoes` é anotado
   `tuple[flows.Botao, ...]` e recebe `reg.Botao`; um expõe `.titulo`, o outro
   `.rotulo`. Sem type checker no CI, isso só falharia em produção, num lead
   real. O alias `titulo` fecha o buraco.
"""
from dataclasses import fields, replace

import pytest

from app.button_flow import flows
from app.button_flow import valeria_engine as motor
from app.button_flow import valeria_registry as reg
from app.button_flow.engine import Clique, Texto

VAZIO: dict = {}


def _clique(botao_id: str) -> Clique:
    return Clique(payload=botao_id, titulo="")


# ── Defeito 1 · o toque no prazo responde ──────────────────────────────────
@pytest.mark.parametrize("prazo_id,dias", [("snooze30", 30), ("snooze60", 60),
                                           ("snooze90", 90)])
def test_clique_no_prazo_responde_ao_lead(prazo_id, dias):
    """Antes deste teste o lead adiava e recebia NADA (destino era T_FIM)."""
    d = motor.decidir("T_ADIAR", _clique(prazo_id), VAZIO, reg.NOS, reg.TERMINAIS)

    assert d.mensagem is not None, "o lead adiou e levou silêncio"
    assert d.mensagem.corpo == flows.MSG_PRAZO_FECHAMENTO
    assert d.efeitos.recontato_dias == dias
    assert d.efeitos.optout is False, "adiar NÃO descarta o lead"
    assert d.efeitos.handoff is False, "adiar não é entrega ao vendedor"


@pytest.mark.parametrize("prazo_id", ["snooze30", "snooze60", "snooze90"])
def test_clique_no_prazo_vai_para_o_terminal_de_adiamento(prazo_id):
    d = motor.decidir("T_ADIAR", _clique(prazo_id), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_ADIADO"
    assert d.proximo_no != "T_FIM", "T_FIM tem corpo vazio: seria silêncio"


def test_corpo_do_adiamento_e_o_template_nao_a_frase_resolvida():
    """O `{prazo}` é resolvido pelo RUNNER no envio; o terminal guarda o molde."""
    d = motor.decidir("T_ADIAR", _clique("snooze30"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert "{prazo}" in d.mensagem.corpo
    assert flows.render(d.mensagem.corpo, {"prazo": "em 30 dias"}).startswith(
        "combinado, em 30 dias."
    )


def test_a_frase_do_adiamento_e_reusada_nao_recopiada():
    """Mesma string, mesmo objeto: uma cópia teria um segundo dono."""
    assert reg.TERMINAIS["T_ADIADO"].corpo is flows.MSG_PRAZO_FECHAMENTO


def test_terminal_de_adiamento_declarado_com_os_efeitos_certos():
    terminal = reg.TERMINAIS["T_ADIADO"]
    assert reg.TAG_ADIADO in terminal.tags
    assert terminal.optout is False
    assert terminal.handoff is False
    assert terminal.vendedor is None
    assert terminal.prazos is False, "reoferecer a folha de prazos seria loop"


def test_a_folha_de_prazos_nao_volta_depois_de_escolhida():
    """Chegou ao T_ADIADO: nada mais para tocar, então nem nudge nem prazo de novo.

    ATUALIZADO em 30/09/2026, e a mudança é o conserto do encerramento
    (tests/test_valeria_encerramento_2026_09_30.py). A INTENÇÃO deste teste — "nada
    mais para tocar" — é a mesma e continua verificada; o que mudou é o destino: a
    versão anterior afirmava `proximo_no == "T_HUMANO"`, e aquele `T_HUMANO` era o
    DEFEITO, não o contrato. Ele vinha da última linha de `decidir` (`_ir_para
    (ID_HUMANO)`, alcançada porque a tupla de botões do terminal é vazia) e era
    REAPLICADO a cada mensagem seguinte do lead, para sempre: tag regravada,
    observação de CRM e mensagem de sistema novas em cada rodada. Agora o fluxo
    encerrado devolve `ignorar`, como o motor da Recuperação já faz no nó
    `flows.NO_ENCERRADO`.
    """
    d = motor.decidir("T_ADIADO", Texto("ok"), {"nudges": 0}, reg.NOS, reg.TERMINAIS)
    assert d.ignorar is True
    assert d.proximo_no == "T_ADIADO", "o adiamento confirmado não se move"
    assert d.marcar_nudge is False
    assert d.mensagem is None, "reperguntaria o que o lead acabou de responder"


def test_nenhum_desfecho_da_valeria_usa_o_vocabulario_da_recuperacao():
    """`flows.Prazo.tag` diz "Recuperação: 30 dias" — é o desfecho do OUTRO fluxo."""
    for terminal in reg.TERMINAIS.values():
        for tag in terminal.tags:
            assert "Recupera" not in tag, f"{terminal.id} carrega {tag!r}"

    botoes = [b for no in reg.NOS.values() for b in no.botoes]
    botoes += list(reg.BOTOES_PRAZO)
    for botao in botoes:
        for campo in fields(botao):
            valor = getattr(botao, campo.name)
            assert "Recupera" not in str(valor), f"{botao.id}.{campo.name}={valor!r}"


# ── Defeito 2 · os botões de prazo moram no registry ───────────────────────
def test_botoes_de_prazo_declarados_no_registry():
    assert len(reg.BOTOES_PRAZO) == 3
    assert tuple(b.id for b in reg.BOTOES_PRAZO) == tuple(p.id for p in flows.PRAZOS)
    assert tuple(b.rotulo for b in reg.BOTOES_PRAZO) == tuple(
        p.titulo for p in flows.PRAZOS
    )


def test_dias_de_cada_prazo_vem_de_flows_prazos():
    """30/60/90 são calibrados no intervalo real entre compras (78-122 dias)."""
    assert reg.DIAS_POR_PRAZO == {p.id: p.dias for p in flows.PRAZOS}


def test_destino_dos_botoes_de_prazo_existe():
    conhecidos = set(reg.NOS) | set(reg.TERMINAIS)
    for botao in reg.BOTOES_PRAZO:
        assert botao.destino == "T_ADIADO"
        assert botao.destino in conhecidos


def test_rotulo_de_prazo_cabe_no_limite_da_meta():
    """Rótulo > 20 chars = a Meta RECUSA o envio e a ValerIA fica muda."""
    for botao in reg.BOTOES_PRAZO:
        assert len(botao.rotulo) <= reg.LIMITE_ROTULO_BOTAO


def test_o_motor_nao_declara_mais_botao_nenhum():
    """Se voltar a declarar, volta a divergir da tela que edita o registry."""
    assert not hasattr(motor, "BOTOES_PRAZO")


def test_t_adiar_oferece_exatamente_a_folha_declarada():
    d = motor.decidir("N5", _clique("nao_agora"), VAZIO, reg.NOS, reg.TERMINAIS)
    assert d.proximo_no == "T_ADIAR"
    assert d.mensagem is not None
    assert d.mensagem.botoes == reg.BOTOES_PRAZO


# ── Defeito 3 · um renderizador, dois tipos de botão ───────────────────────
def test_botao_do_registry_responde_a_titulo():
    """`Mensagem.botoes` é anotado `flows.Botao` e recebe `reg.Botao`."""
    assert reg.Botao("x", "Rotulo", "N1").titulo == "Rotulo"


def test_titulo_acompanha_o_rotulo_editado_na_tela():
    """`rotulos` do override troca `rotulo`; o alias não pode congelar o antigo."""
    botao = reg.Botao("x", "Rotulo", "N1")
    assert replace(botao, rotulo="Outro").titulo == "Outro"


def test_titulo_nao_e_campo_editavel():
    """Alias de leitura: dois campos graváveis para o mesmo texto divergiriam."""
    assert "titulo" not in {c.name for c in fields(reg.Botao)}
    with pytest.raises(AttributeError):
        reg.Botao("x", "Rotulo", "N1").titulo = "Outro"


def test_os_dois_tipos_de_botao_sao_intercambiaveis_para_o_renderizador():
    todos = list(reg.BOTOES_PRAZO) + list(flows.BOTOES_PRAZO)
    todos += [b for no in reg.NOS.values() for b in no.botoes]
    for botao in todos:
        assert botao.titulo, f"{botao!r} não expõe titulo"
