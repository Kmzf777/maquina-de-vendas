"""A mesma nota falsa no OPT-OUT: quem pediu para sair não foi "entregue ao vendedor".

Irmão de test_botoes_nota_handoff_2026_10_01.py. `T_OPTOUT` declara `silenciar_ia=True`
JUNTO de `optout=True`, então o lead que pede para parar recebia DUAS notas:

    🚫 [OPT-OUT] Lead pediu para parar de receber mensagens no bot de botões da ValerIA.
    🙋 [ATENDIMENTO HUMANO] Lead insistiu em texto livre no bot de botões da ValerIA;
       IA desligada, conversa entregue ao vendedor.

As duas metades da segunda são falsas AQUI:
  • "insistiu em texto livre" — quem chega a `T_OPTOUT` escreveu UMA frase da lista
    fechada (`valeria_engine.FRASES_OPTOUT`), e o motor a atende ACIMA do contador de
    nudges e acima da guarda de encerramento; no primeiro contato, até acima da tela
    de entrada (`valeria_runner._decidir`). O caso normal é `nudges=0`: uma mensagem,
    zero insistência. "Insistiu" descreve o `T_HUMANO`, o 4º texto livre;
  • "conversa entregue ao vendedor" — falso em TODO opt-out: a conversa foi ENCERRADA
    porque a pessoa pediu para sair. O vendedor que lê a nota é mandado abordar quem
    pediu para ser deixado em paz, e contato depois do opt-out é o que a Meta e a ANPD
    cobram.

ONDE ESTE ARQUIVO NARROWA O PLANO: o plano pedia um teste de `T_OPTOUT` "alcançado por
um CLIQUE", porque o lead podia ter tocado um botão. Na ValerIA de botões isso NÃO
existe: nenhum botão do registry aponta para `T_OPTOUT` (o motor declara os dois
terminais que escolhe sozinho) e `destino` NÃO é editável na tela — o PUT de
`/api/valeria-flow` descarta a chave (test_valeria_flow_router_2026_09_30.py::
test_put_com_destino_ou_grava_nao_muda_o_registry). O opt-out por BOTÃO existe no outro
fluxo ("Parar mensagens", flows.py), e lá `Efeitos` não pede `silenciar_ia` — é por isso
que o defeito é só da ValerIA. Os dois testes de reachability abaixo provam as duas
coisas, e o contrato das notas é afirmado no nível de `effects.aplicar`, que é onde ele
vale independentemente de como `T_OPTOUT` for alcançado — inclusive no dia em que um
botão passar a apontar para lá (há um teste para esse caso hipotético também).

O QUE SE ESCOLHEU: SUPRIMIR a nota de silêncio no opt-out, não reescrevê-la. No handoff
sobravam DUAS notas verdadeiras; aqui sobra UMA, e ela já é o registro completo (fato,
motivo e qual bot). Uma segunda nota verdadeira não acrescentaria fato nenhum:
`_aplicar_optout` grava `ai_enabled=False` no MESMO update obrigatório do `opt_out`,
ou seja, a coluna que ela explicaria é escrita pelo próprio opt-out. Acrescentaria só um
cabeçalho de atendimento humano na conversa de quem pediu silêncio.

Dublês reusados de test_button_flow_effects_2026_08_20.py e de
test_botoes_nota_handoff_2026_10_01.py — nenhum CRM novo inventado aqui.
"""
import dataclasses

import pytest

from app.agent.tools import SUPERVISOR_NAME
from app.button_flow import effects, engine, flows
from app.button_flow import valeria_engine as motor
from app.button_flow import valeria_registry as reg
from app.button_flow.engine import Classificado, Clique, Efeitos, Texto
from tests.test_botoes_nota_handoff_2026_10_01 import (  # helpers já estabelecidos
    AFIRMACAO_FALSA,
    MOTIVO_RECUPERACAO,
    MOTIVO_VALERIA,
    _colunas,
    _lead,
    _marcador,
    _nota_silencio,
    _nota_transbordo,
    _notas,
)
from tests.test_button_flow_effects_2026_08_20 import (  # dublês do CRM
    CLIQUE_PARAR,
    MARCADOR_DO_DASHBOARD,
    _campos_do_optout,
    _crm_mockado,
    _stages_movidos,
)
from tests.test_button_flow_engine_2026_08_20 import CTX, estado

# ── Emoji por chr(), e não colado no literal ────────────────────────────────
# Mesma razão do arquivo irmão: comparação caractere a caractere não pode depender de
# um invisível. O 🚫 é U+1F6AB SEM VARIATION SELECTOR — ao contrário do ⚠️ e do ➡️,
# que carregam U+FE0F. `effects.py` tem exatamente DOIS U+FE0F, e nenhum deles é este.
PROIBIDO = chr(0x1F6AB)            # 🚫 NO ENTRY SIGN

# A segunda metade falsa. Trecho e não frase inteira: o que se proíbe é a AFIRMAÇÃO —
# "foi entregue a alguém" — e não uma redação específica, que segue editável.
AFIRMACAO_ENTREGUE = "conversa entregue ao vendedor"

# Evidência de um opt-out da ValerIA, no contrato de `valeria_runner._evidencia_do_turno`
# para um evento de TEXTO (o único que chega ao `T_OPTOUT` hoje).
EVIDENCIA_TEXTO = {"origem": "classe", "texto": "pare", "wamid": "wamid.OPTOUT"}


def _nota_optout(fluxo: str) -> str:
    return (f"{PROIBIDO} [OPT-OUT] Lead pediu para parar de receber mensagens "
            f"no {fluxo}.")


def _aplicar_optout_da_valeria(crm_deal=None, *, efeitos: Efeitos | None = None,
                               evidencia: dict | None = None):
    """`aplicar` no terminal de opt-out da ValerIA. Devolve (ok, crm).

    `deal=None` porque o lead da ValerIA não tem card no funil da Reativação Bling —
    a coorte dos 1.208 é do outro fluxo.
    """
    terminal = reg.TERMINAIS["T_OPTOUT"]
    with _crm_mockado(deal=crm_deal) as crm:
        ok = effects.aplicar(
            efeitos or Efeitos(tags=terminal.tags, optout=True, silenciar_ia=True),
            lead=_lead(), conversation_id="c-optout",
            evidencia=EVIDENCIA_TEXTO if evidencia is None else evidencia,
            fluxo=effects.FLUXO_VALERIA,
        )
    return ok, crm


def _nada_de_handoff(obs: list[str], sistema: list[str]) -> None:
    """Nenhum registro do turno pode dizer que alguém recebeu este lead."""
    for texto in obs + sistema:
        assert AFIRMACAO_ENTREGUE not in texto, texto
        assert AFIRMACAO_FALSA not in texto, texto
    assert not any(t.startswith(MARCADOR_DO_DASHBOARD) for t in sistema), (
        "opt-out contado como transbordo infla o KPI de handoffs do dashboard"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. O terminal de opt-out: UMA nota, e é a verdadeira
# ═══════════════════════════════════════════════════════════════════════════
def test_o_terminal_de_optout_declara_os_dois_efeitos():
    """A combinação que produziu a nota falsa. Se o registry mudar, o teste avisa."""
    terminal = reg.TERMINAIS["T_OPTOUT"]
    assert terminal.optout is True
    assert terminal.silenciar_ia is True
    assert terminal.handoff is False, (
        "opt-out com handoff seria contraditório: entregar ao vendedor quem pediu "
        "para sair"
    )


def test_optout_grava_exatamente_a_nota_de_optout():
    """Lista COMPLETA por igualdade: "não contém a frase falsa" passaria também no dia
    em que alguém acrescentasse uma TERCEIRA nota."""
    ok, crm = _aplicar_optout_da_valeria()

    assert ok is True
    nota = _nota_optout(effects.FLUXO_VALERIA)
    obs, sistema = _notas(crm)
    assert obs == [nota]
    assert sistema == [f"[button_flow] {nota}"]
    _nada_de_handoff(obs, sistema)


def test_optout_nao_escreve_a_nota_de_atendimento_humano():
    """O defeito, na forma mais direta: a nota de silêncio não sai aqui."""
    _ok, crm = _aplicar_optout_da_valeria()

    obs, sistema = _notas(crm)
    proibida = _nota_silencio(effects.FLUXO_VALERIA)
    assert proibida not in obs
    assert f"[button_flow] {proibida}" not in sistema


# ═══════════════════════════════════════════════════════════════════════════
# 2. O REPRO pelo MOTOR: nudges=0 — uma mensagem, zero insistência
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("frase", sorted(motor.FRASES_OPTOUT))
def test_cada_frase_da_lista_fechada_leva_ao_optout_sem_gastar_nudge(frase):
    """Varredura da lista fechada inteira: o `Efeitos` sai do MOTOR, não da mão.

    `nudges` não se move — é a prova de que "insistiu em texto livre" descreve outro
    turno. O lead digitou UMA frase e o motor a atendeu na hora.
    """
    est = {"flow": reg.FLOW_ID, "node": "N1", "nudges": 0}
    decisao = motor.decidir("N1", Texto(frase), est, reg.NOS, reg.TERMINAIS)

    assert decisao.proximo_no == "T_OPTOUT"
    assert est.get("nudges") == 0, "o repro perde o sentido se o estado gastar nudge"
    assert decisao.efeitos.optout is True
    assert decisao.efeitos.silenciar_ia is True

    with _crm_mockado(deal=None) as crm:
        ok = effects.aplicar(decisao.efeitos, lead=_lead(),
                             conversation_id="c-optout",
                             evidencia=EVIDENCIA_TEXTO,
                             fluxo=effects.FLUXO_VALERIA)

    assert ok is True
    nota = _nota_optout(effects.FLUXO_VALERIA)
    obs, sistema = _notas(crm)
    assert obs == [nota]
    assert sistema == [f"[button_flow] {nota}"]
    _nada_de_handoff(obs, sistema)


def test_pedido_de_saida_no_primeiro_contato_tambem_grava_so_a_nota_de_optout():
    """O caminho de `valeria_runner._decidir`: "pare" como PRIMEIRA mensagem.

    Estado vazio, nó de entrada, nenhuma tela vista — o lead não tinha nem botão para
    tocar. É o turno em que "insistiu em texto livre" é mais obviamente falso.
    """
    decisao = motor.decidir(reg.NO_ENTRADA, Texto("pare"), {},
                            reg.NOS, reg.TERMINAIS)

    assert decisao.proximo_no == "T_OPTOUT"

    with _crm_mockado(deal=None) as crm:
        ok = effects.aplicar(decisao.efeitos, lead=_lead(),
                             conversation_id="c-optout",
                             evidencia=EVIDENCIA_TEXTO,
                             fluxo=effects.FLUXO_VALERIA)

    assert ok is True
    obs, sistema = _notas(crm)
    assert obs == [_nota_optout(effects.FLUXO_VALERIA)]
    _nada_de_handoff(obs, sistema)


# ═══════════════════════════════════════════════════════════════════════════
# 3. O "clique de opt-out" do plano: ele NÃO existe neste fluxo
# ═══════════════════════════════════════════════════════════════════════════
def test_nenhum_botao_declarado_aponta_para_o_optout():
    """Reachability declarada: `T_OPTOUT` e `T_HUMANO` são escolha do MOTOR.

    Varre TODOS os botões que o lead pode receber (nós, folha de prazos e os botões
    que um terminal oferece) — e `destino` não é editável na tela, então o registry é
    a lista completa de rotas possíveis.
    """
    destinos = [b.destino for no in reg.NOS.values() for b in no.botoes]
    destinos += [b.destino for b in reg.BOTOES_PRAZO]
    assert destinos, "varredura vazia não prova nada"
    assert motor.ID_OPTOUT not in destinos
    assert motor.ID_HUMANO in destinos, (
        "o T_HUMANO TEM botão (C1 → 'Tenho uma dúvida'), e é o contraste que mostra "
        "que a varredura acima enxerga destinos de verdade"
    )


def test_clique_nenhum_chega_ao_optout():
    """Nem um clique válido, nem um id de tela antiga, nem um rótulo que É um "pare".

    A guarda de opt-out do motor lê `isinstance(evento, Texto)` — clique que não casa
    com botão do nó é reoferecimento, não saída. Documenta por que o teste de "clique"
    do plano virou o teste de FRASE acima, e não um cenário inventado.

    ISTO É UM RETRATO, NÃO UM ELOGIO: um clique cujo RÓTULO é um pedido de saída (o
    botão de opt-out que a Meta exige nos templates de marketing) não vira opt-out
    neste motor, e para conversas de fluxo de botões o caminho determinístico do
    processor sai de cena de propósito (`_optout_deterministico_cabe`). Se um dia esse
    clique chegar como `Clique`, ninguém o honra — é um defeito SEPARADO deste, não
    coberto aqui, e a nota de `T_OPTOUT` já está correta para quando for consertado
    (ver o teste do botão hipotético).
    """
    ids = {b.id for no in reg.NOS.values() for b in no.botoes}
    ids |= {"id_de_tela_antiga", "pare", "sair"}

    for no_id in reg.NOS:
        for botao_id in sorted(ids):
            decisao = motor.decidir(no_id, Clique(botao_id, "Parar mensagens"),
                                    {"flow": reg.FLOW_ID, "node": no_id, "nudges": 0},
                                    reg.NOS, reg.TERMINAIS)
            assert decisao.proximo_no != motor.ID_OPTOUT, (
                f"{no_id} + clique {botao_id!r} chegou ao opt-out: o contrato de notas "
                "continua valendo (ver o teste do botão hipotético), mas a reachability "
                "deste fluxo mudou e a spec precisa ser relida"
            )


def test_o_contrato_vale_mesmo_se_um_botao_passar_a_apontar_para_o_optout():
    """O caso HIPOTÉTICO do plano, honesto: um registry em que o clique leva ao opt-out.

    Não é o fluxo de hoje (ver os dois testes acima) — é o seguro de que a supressão
    foi feita no lugar certo: ela lê `Efeitos`, não o tipo do evento. Um botão de saída
    declarado amanhã no registry nasce com a nota correta, sem passar por aqui de novo.
    """
    alvo = reg.NOS["N1"]
    botao = dataclasses.replace(alvo.botoes[0], destino="T_OPTOUT")
    nos = dict(reg.NOS)
    nos["N1"] = dataclasses.replace(alvo, botoes=(botao,) + alvo.botoes[1:])

    decisao = motor.decidir("N1", Clique(botao.id, botao.rotulo),
                            {"flow": reg.FLOW_ID, "node": "N1", "nudges": 0},
                            nos, reg.TERMINAIS)

    assert decisao.proximo_no == "T_OPTOUT"
    assert decisao.efeitos.optout and decisao.efeitos.silenciar_ia

    with _crm_mockado(deal=None) as crm:
        ok = effects.aplicar(decisao.efeitos, lead=_lead(),
                             conversation_id="c-optout",
                             evidencia={"origem": "clique",
                                        "button_payload": botao.id,
                                        "button_label": botao.rotulo,
                                        "wamid": "wamid.CLIQUE"},
                             fluxo=effects.FLUXO_VALERIA)

    assert ok is True
    nota = _nota_optout(effects.FLUXO_VALERIA)
    obs, sistema = _notas(crm)
    assert obs == [nota]
    assert sistema == [f"[button_flow] {nota}"]
    _nada_de_handoff(obs, sistema)
    assert _campos_do_optout(crm)["opt_out_channel"] == effects.CANAL_BOTAO


# ═══════════════════════════════════════════════════════════════════════════
# 4. O que a supressão NÃO pode encostar: o registro de conformidade
# ═══════════════════════════════════════════════════════════════════════════
def test_optout_e_evidencia_continuam_gravados():
    """`opt_out=true` + as 3 colunas de prova são o registro para a Meta/ANPD.

    Nada aqui é sobre nota: é o que a supressão não pode ter encostado.
    """
    ok, crm = _aplicar_optout_da_valeria()

    assert ok is True
    campos = _campos_do_optout(crm)
    assert campos["opt_out"] is True
    assert campos["ai_enabled"] is False
    assert campos["opt_out_channel"] == effects.CANAL_TEXTO
    assert campos["opt_out_evidence"]["texto"] == "pare"
    assert campos["opt_out_evidence"]["wamid"] == "wamid.OPTOUT"
    assert "opt_out_at" in campos
    crm.side.assert_called_once_with("lead-1", "5534988861441", reason="optout")


def test_ai_enabled_false_continua_sendo_gravado_pelo_silenciar_ia():
    """Só a anotação mudou: `_silenciar_ia` segue fazendo o update da coluna.

    DOIS updates de coluna, nessa ordem — o obrigatório do opt-out (que já traz
    `ai_enabled=False`) e o de `_silenciar_ia`. E nenhum `human_control`: opt-out não
    é transbordo, e carimbá-lo faria a ponte pós-handoff tratar o lead como entregue.
    """
    _ok, crm = _aplicar_optout_da_valeria()

    colunas = _colunas(crm)
    assert len(colunas) == 2, colunas
    assert colunas[0]["ai_enabled"] is False and colunas[0]["opt_out"] is True
    assert colunas[-1] == {"ai_enabled": False}
    assert all("human_control" not in c for c in colunas)


def test_falha_de_gravacao_do_optout_segue_bloqueando_o_avanco():
    """O fail-CLOSED é anterior à nota, e a supressão não pode tê-lo movido.

    E é ele que garante que NUNCA se fica sem nota nenhuma: `_silenciar_ia` só roda
    depois de `_aplicar_optout` devolver True, o que acontece DEPOIS do `anotar` dele.
    """
    terminal = reg.TERMINAIS["T_OPTOUT"]
    with _crm_mockado(deal=None) as crm:
        crm.upd.side_effect = RuntimeError("GOAWAY")
        ok = effects.aplicar(
            Efeitos(tags=terminal.tags, optout=True, silenciar_ia=True),
            lead=_lead(), conversation_id="c-optout", evidencia=EVIDENCIA_TEXTO,
            fluxo=effects.FLUXO_VALERIA,
        )

    assert ok is False
    obs, sistema = _notas(crm)
    assert obs == [] and sistema == [], (
        "sem opt-out gravado o turno não avança e nada é anotado — nem a nota de "
        "silêncio, que é justamente o que a supressão remove"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 5. Os outros desfechos da ValerIA não se movem
# ═══════════════════════════════════════════════════════════════════════════
def test_t_humano_continua_gravando_a_nota_de_silencio():
    """Supressão larga (ou aplicada por engano ao `T_HUMANO`) apagaria o único
    registro do bloqueio por insistência — ali a frase descreve o fato."""
    terminal = reg.TERMINAIS["T_HUMANO"]
    assert terminal.silenciar_ia and not terminal.handoff and not terminal.optout

    with _crm_mockado(deal=None) as crm:
        ok = effects.aplicar(Efeitos(tags=terminal.tags, silenciar_ia=True),
                             lead=_lead(), conversation_id="c1",
                             fluxo=effects.FLUXO_VALERIA)

    assert ok is True
    nota = _nota_silencio(effects.FLUXO_VALERIA)
    obs, sistema = _notas(crm)
    assert obs == [nota]
    assert sistema == [f"[button_flow] {nota}"]


@pytest.mark.parametrize("terminal_id",
                         ["T_HANDOFF", "T_HANDOFF_PL", "T_HANDOFF_ARTHUR"])
def test_os_tres_handoffs_seguem_com_as_duas_notas_verdadeiras(terminal_id):
    """A supressão de 01/10 que já estava no disco continua valendo — e continua
    sendo a dela, não a do opt-out: nenhum handoff pede `optout`."""
    terminal = reg.TERMINAIS[terminal_id]
    assert terminal.handoff and terminal.silenciar_ia and not terminal.optout

    with _crm_mockado(deal=None) as crm:
        ok = effects.aplicar(
            Efeitos(tags=terminal.tags, handoff=True, silenciar_ia=True,
                    vendedor=terminal.vendedor),
            lead=_lead(), conversation_id="c1", fluxo=effects.FLUXO_VALERIA,
        )

    assert ok is True
    nota = _nota_transbordo(terminal.vendedor, MOTIVO_VALERIA)
    obs, sistema = _notas(crm)
    assert obs == [nota]
    assert sistema == [_marcador(terminal.vendedor, MOTIVO_VALERIA),
                       f"[button_flow] {nota}"]


def test_so_o_t_optout_combina_optout_com_silenciar_ia():
    """Mapa dos terminais, para a supressão não pegar nenhum outro desfecho de carona."""
    com_optout = sorted(t.id for t in reg.TERMINAIS.values() if t.optout)
    assert com_optout == ["T_OPTOUT"]
    assert not [t.id for t in reg.TERMINAIS.values() if t.optout and t.handoff]


# ═══════════════════════════════════════════════════════════════════════════
# 6. REGRESSÃO DA RECUPERAÇÃO — o fluxo em PRODUÇÃO grava o que já gravava
# ═══════════════════════════════════════════════════════════════════════════
# Listas COMPLETAS, por igualdade: `effects.py` é compartilhado com um bot que está em
# produção neste minuto, e o que importa é que nada do que ele escreve mude.
class TestARecuperacaoNaoMuda:
    def test_o_optout_dela_grava_a_nota_de_optout_e_move_o_card(self):
        """O opt-out por BOTÃO ("Parar mensagens"): optout SEM silenciar_ia.

        É o caminho que a supressão nova não pode ter tocado — e a razão de o defeito
        ser só da ValerIA.
        """
        with _crm_mockado() as crm:  # com card no funil da Reativação, o caso real
            ok = effects.aplicar(Efeitos(tags=(flows.TAG_RECUSOU,), optout=True),
                                 lead=_lead(), conversation_id="c1",
                                 evidencia=CLIQUE_PARAR)

        assert ok is True
        nota = _nota_optout(effects.FLUXO_RECUPERACAO)
        obs, sistema = _notas(crm)
        assert obs == [nota]
        assert sistema == [f"[button_flow] {nota}"]
        assert _stages_movidos(crm) == [effects.STAGE_DESCADASTRADO[0]]
        crm.side.assert_called_once_with("lead-1", "5534988861441", reason="optout")
        assert _campos_do_optout(crm)["opt_out_channel"] == effects.CANAL_BOTAO

    def test_handoff_grava_as_mesmas_duas_notas_de_sempre(self):
        """`_decidir_quente` (botão "Preciso repor" / classe QUENTE) e a trilha C."""
        with _crm_mockado() as crm:
            ok = effects.aplicar(Efeitos(tags=(flows.TAG_QUENTE,), handoff=True),
                                 lead=_lead(), conversation_id="c1")

        assert ok is True
        nota = _nota_transbordo(SUPERVISOR_NAME, MOTIVO_RECUPERACAO)
        obs, sistema = _notas(crm)
        assert obs == [nota]
        assert sistema == [_marcador(SUPERVISOR_NAME, MOTIVO_RECUPERACAO),
                           f"[button_flow] {nota}"]
        assert _colunas(crm) == [{"ai_enabled": False}], (
            "a Recuperação roda no número do vendedor e NÃO carimba human_control"
        )
        assert _stages_movidos(crm) == [effects.STAGE_QUER_REPOR[0]]

    def test_o_caminho_de_silencio_dela_grava_a_nota_inteira(self):
        """`_ENTREGAR_AO_HUMANO` (ruído reoferecido uma vez e depois entregue)."""
        with _crm_mockado() as crm:
            ok = effects.aplicar(Efeitos(tags=(flows.TAG_HUMANO,), silenciar_ia=True),
                                 lead=_lead(), conversation_id="c1")

        assert ok is True
        nota = _nota_silencio(effects.FLUXO_RECUPERACAO)
        obs, sistema = _notas(crm)
        assert obs == [nota]
        assert sistema == [f"[button_flow] {nota}"]
        assert _colunas(crm) == [{"ai_enabled": False}]
        assert not _stages_movidos(crm)

    def test_o_outro_caminho_de_silencio_dela_tambem(self):
        """CLASSE_ENGANO ("não fiz pedido nenhum"): `pretexto_contestado` +
        `silenciar_ia` no mesmo `Efeitos`. Duas notas, nessa ordem."""
        with _crm_mockado() as crm:
            ok = effects.aplicar(
                Efeitos(tags=(flows.TAG_ENGANO,), silenciar_ia=True,
                        pretexto_contestado=True),
                lead=_lead(), conversation_id="c1",
            )

        assert ok is True
        pretexto = (f"{chr(0x26A0)}{chr(0xFE0F)} [PRETEXTO CONTESTADO] Lead negou o "
                    "motivo do disparo (diz não ter feito pedido / não conhecer a "
                    "compra). NÃO reenviar campanha para este contato.")
        nota = _nota_silencio(effects.FLUXO_RECUPERACAO)
        obs, sistema = _notas(crm)
        assert obs == [pretexto, nota]
        assert sistema == [f"[button_flow] {pretexto}", f"[button_flow] {nota}"]

    def test_nenhuma_decisao_dela_pede_optout_com_silenciar_ia(self):
        """A razão ESTRUTURAL de nada acima poder mudar — verificada, não herdada.

        Varredura de `engine.decidir`: no motor da Recuperação `optout` e
        `silenciar_ia` nunca saem no MESMO `Efeitos` (`_decidir_optout` pede só o
        primeiro). A supressão nova é, para ela, código que não executa. No dia em que
        um caminho novo combinar os dois, a nota de silêncio dela deixa de ser escrita
        em silêncio; é este teste que avisa antes.
        """
        eventos: list[object] = [Classificado(c) for c in engine.CLASSES]
        eventos += [Clique(b.id, b.titulo) for b in flows.TODOS_BOTOES_NIVEL1]
        eventos += [Clique(b.id, b.titulo) for b in flows.BOTOES_PRAZO]
        eventos.append(Texto("me tira dessa lista"))

        vistos = 0
        com_optout = 0
        for no in (flows.NO_INTERESSE, flows.NO_PRAZO, flows.NO_ENCERRADO):
            for nudged in (False, True):
                for canal_vendedor in (False, True):
                    for trilha in flows.BOTOES_POR_TRILHA:
                        for evento in eventos:
                            d = engine.decidir(
                                estado(no, nudged=nudged, trilha=trilha), evento,
                                canal_do_vendedor=canal_vendedor, contexto=CTX)
                            vistos += 1
                            com_optout += bool(d.efeitos.optout)
                            assert not (d.efeitos.silenciar_ia and d.efeitos.optout), (
                                f"{no}/{trilha}/nudged={nudged}/{evento!r} passou a "
                                "pedir os dois efeitos: a nota de silêncio da "
                                "Recuperação deixaria de ser gravada"
                            )

        assert vistos > 300, f"varredura rasa demais p/ provar a estrutura: {vistos}"
        assert com_optout > 0, "varredura que nunca chegou a um opt-out não prova nada"
