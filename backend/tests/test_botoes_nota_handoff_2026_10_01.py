"""A nota do handoff não pode mentir: `_silenciar_ia` cala a IA, não inventa motivo.

Defeito lido em produção (01/10/2026): TODO handoff da ValerIA de botões gravava
TRÊS notas no mesmo transbordo, e uma delas era falsa —

    🙋 [ATENDIMENTO HUMANO] Lead insistiu em texto livre no bot de botões da
    ValerIA; IA desligada, conversa entregue ao vendedor.

Inclusive na conversa dd221643, cujo `flow_state` tem `nudges=0`: aquele lead tocou
todos os botões e nunca digitou uma linha. Quem lê a nota é o vendedor, antes de
abordar — é a mesma classe de mentira de auditoria que o relabel de 09/09 corrigiu
nos rótulos aposentados e que 30/09 corrigiu no "bot de recuperação".

Causa: `T_HANDOFF`, `T_HANDOFF_PL` e `T_HANDOFF_ARTHUR` declaram `silenciar_ia=True`
JUNTO de `handoff=True`, e `_silenciar_ia` tinha embutido o texto do `T_HUMANO` — o
bloqueio depois de 3 nudges, o ÚNICO caminho onde a frase é verdade.

O que este arquivo trava:
  • no handoff, a lista COMPLETA de notas é só a das duas verdadeiras (o marcador
    `[encaminhar_humano]` que o KPI do dashboard conta e a `[TRANSBORDO p/ …]`);
  • no `T_HUMANO` (sem handoff) a nota CONTINUA saindo — lá ela descreve o fato;
  • `ai_enabled=False` nos dois caminhos: calar a IA nunca foi o que estava errado,
    só a anotação;
  • a Recuperação, que está em PRODUÇÃO neste mesmo módulo, grava a lista completa
    de notas que gravava antes — por IGUALDADE, não pela ausência de uma delas — e
    a razão estrutural de ela não poder mudar (lá os dois efeitos nunca saem juntos).

Dublês reusados de test_button_flow_effects_2026_08_20.py e do padrão de
test_valeria_handoff_2026_09_30.py — nenhum CRM novo inventado aqui.
"""
import pytest

from app.agent.tools import SUPERVISOR_NAME
from app.button_flow import effects, engine, flows
from app.button_flow import valeria_engine as motor
from app.button_flow import valeria_registry as reg
from app.button_flow.engine import Classificado, Clique, Efeitos, Texto
from tests.test_button_flow_effects_2026_08_20 import (  # dublês já estabelecidos
    MARCADOR_DO_DASHBOARD,
    _crm_mockado,
    _mensagens_de_sistema,
    _stages_movidos,
)
from tests.test_button_flow_engine_2026_08_20 import CTX, estado

# ── Emoji por chr(), e não colado no literal ────────────────────────────────
# O ➡️ é U+27A1 seguido de U+FE0F (VARIATION SELECTOR-16), que é INVISÍVEL: um
# literal onde o seletor se perdesse — ou onde entrasse um invisível a mais —
# pareceria idêntico aos olhos e diferente para o `==`, e este arquivo existe
# justamente para comparar texto caractere a caractere. Já os acentos ficam
# literais de propósito: eles são visíveis, e se virarem '?' o teste fica VERMELHO
# contra o que o módulo de verdade grava.
MAO = chr(0x1F64B)                 # 🙋 HAPPY PERSON RAISING ONE HAND
SETA = chr(0x27A1) + chr(0xFE0F)   # ➡️ BLACK RIGHTWARDS ARROW + VARIATION SELECTOR-16

# O pedaço que NÃO pode aparecer num handoff. Trecho, e não a frase inteira: o texto
# segue editável e o que se proíbe é a AFIRMAÇÃO, não a redação.
AFIRMACAO_FALSA = "insistiu em texto livre"

MOTIVO_VALERIA = f"{effects.FLUXO_VALERIA}: lead pediu atendimento do vendedor"
MOTIVO_RECUPERACAO = f"{effects.FLUXO_RECUPERACAO}: lead pediu atendimento do vendedor"


def _lead() -> dict:
    """Lead NOVO por teste: `aplicar` MUTA `lead["metadata"]` de propósito."""
    return {"id": "lead-1", "phone": "5534988861441", "name": "Roner",
            "metadata": {}}


def _notas(crm) -> tuple[list[str], list[str]]:
    """(observações no lead, mensagens de sistema) — tudo que um humano lê depois.

    `append_lead_observation(lead_id, texto)` → args[1]; as mensagens de sistema vêm
    do helper do arquivo de efeitos, que já filtra role='system'.
    """
    return ([c.args[1] for c in crm.obs.call_args_list],
            _mensagens_de_sistema(crm.save))


def _colunas(crm) -> list[dict]:
    """Os updates de COLUNA (sem o de `metadata`), na ordem — mesmo helper da ponte."""
    return [c.kwargs for c in crm.upd.call_args_list if "metadata" not in c.kwargs]


def _nota_transbordo(vendedor: str, motivo: str) -> str:
    return (f"{SETA} [TRANSBORDO p/ {vendedor}] {motivo}. "
            "Nenhuma qualificação por conversa — abordar direto.")


def _marcador(vendedor: str, motivo: str) -> str:
    """O que o KPI de transbordos do dashboard conta. Prefixo do dublê de efeitos."""
    return f"{MARCADOR_DO_DASHBOARD} para {vendedor}: {motivo}"


def _nota_silencio(fluxo: str) -> str:
    return (f"{MAO} [ATENDIMENTO HUMANO] Lead insistiu em texto livre no {fluxo}; "
            "IA desligada, conversa entregue ao vendedor.")


# ═══════════════════════════════════════════════════════════════════════════
# 1. O handoff: as duas notas verdadeiras, e só elas
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("terminal_id",
                         ["T_HANDOFF", "T_HANDOFF_PL", "T_HANDOFF_ARTHUR"])
def test_handoff_grava_exatamente_as_duas_notas_verdadeiras(terminal_id):
    """Os três terminais de handoff pedem `silenciar_ia` E `handoff` no mesmo turno.

    A lista é afirmada por igualdade: "não contém a frase falsa" passaria também no
    dia em que alguém acrescentasse uma QUARTA nota.
    """
    terminal = reg.TERMINAIS[terminal_id]
    assert terminal.handoff and terminal.silenciar_ia, (
        f"{terminal_id} deixou de pedir os dois efeitos — este teste cobre a "
        "combinação que produziu a nota falsa em produção"
    )

    # `deal=None`: o lead da ValerIA não tem card no funil da Reativação Bling, que é
    # o padrão do dublê (é a coorte do outro fluxo).
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
    for texto in obs + sistema:
        assert AFIRMACAO_FALSA not in texto, texto


@pytest.mark.parametrize("terminal_id",
                         ["T_HANDOFF", "T_HANDOFF_PL", "T_HANDOFF_ARTHUR"])
def test_handoff_continua_desligando_a_ia_nos_dois_caminhos(terminal_id):
    """Só a anotação mudou. `_silenciar_ia` segue gravando `ai_enabled=False`, e o
    handoff segue gravando a dupla que a ponte pós-handoff exige — nessa ordem."""
    terminal = reg.TERMINAIS[terminal_id]
    with _crm_mockado(deal=None) as crm:
        effects.aplicar(
            Efeitos(tags=terminal.tags, handoff=True, silenciar_ia=True,
                    vendedor=terminal.vendedor),
            lead=_lead(), conversation_id="c1", fluxo=effects.FLUXO_VALERIA,
        )

    assert _colunas(crm) == [
        {"ai_enabled": False},
        {"ai_enabled": False, "human_control": True},
    ]


# ═══════════════════════════════════════════════════════════════════════════
# 2. O REPRO: a conversa dd221643, com nudges=0
# ═══════════════════════════════════════════════════════════════════════════
def test_handoff_pl_alcancado_com_nudges_zero_nao_recebe_a_nota_de_texto_livre():
    """O caso real: `nudges=0` e o lead recebia "insistiu em texto livre".

    O `Efeitos` não é escrito à mão — sai do motor, a partir do clique real no ramo
    de marca própria (P4 → `T_HANDOFF_PL`). É o que torna o repro honesto: se o
    terminal mudar de efeitos, este teste muda de assunto junto.
    """
    est = {"flow": reg.FLOW_ID, "node": "P4", "nudges": 0}
    decisao = motor.decidir("P4", Clique(payload="sim", titulo="Sim, quero falar"),
                            est, reg.NOS, reg.TERMINAIS)

    assert decisao.proximo_no == "T_HANDOFF_PL"
    assert est.get("nudges") == 0, "o repro perde o sentido se o estado tiver nudge"
    assert decisao.efeitos.handoff is True
    assert decisao.efeitos.silenciar_ia is True

    with _crm_mockado(deal=None) as crm:
        ok = effects.aplicar(decisao.efeitos, lead=_lead(),
                             conversation_id="dd221643",
                             fluxo=effects.FLUXO_VALERIA)

    assert ok is True
    obs, sistema = _notas(crm)
    for texto in obs + sistema:
        assert AFIRMACAO_FALSA not in texto, (
            "lead com nudges=0 tocou todos os botões e nunca digitou: " + texto
        )
    # E o transbordo verdadeiro continua registrado — a correção REMOVE uma mentira,
    # não o rastro do handoff.
    nota = _nota_transbordo(reg.VENDEDOR_ATACADO, MOTIVO_VALERIA)
    assert sistema == [_marcador(reg.VENDEDOR_ATACADO, MOTIVO_VALERIA),
                       f"[button_flow] {nota}"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. O T_HUMANO (3 nudges, sem handoff): lá a nota é VERDADE e continua saindo
# ═══════════════════════════════════════════════════════════════════════════
def test_t_humano_sem_handoff_continua_gravando_a_nota():
    """Supressão larga ("nunca mais escreva a nota") apagaria o único registro do
    bloqueio por insistência — o turno em que a frase descreve exatamente o fato."""
    terminal = reg.TERMINAIS["T_HUMANO"]
    assert terminal.silenciar_ia and not terminal.handoff

    with _crm_mockado(deal=None) as crm:
        ok = effects.aplicar(Efeitos(tags=terminal.tags, silenciar_ia=True),
                             lead=_lead(), conversation_id="c1",
                             fluxo=effects.FLUXO_VALERIA)

    assert ok is True
    nota = _nota_silencio(effects.FLUXO_VALERIA)
    obs, sistema = _notas(crm)
    assert obs == [nota]
    assert sistema == [f"[button_flow] {nota}"]
    assert _colunas(crm) == [{"ai_enabled": False}], "a IA é desligada aqui também"
    assert not _stages_movidos(crm), "insistir em digitar não é desfecho de card"


def test_o_bloqueio_por_3_nudges_do_motor_cai_nesse_caminho():
    """Amarra o teste acima ao motor: é o 4º texto livre que leva ao `T_HUMANO`, e é
    por ele que a nota tem de sobreviver."""
    decisao = motor.decidir("N1", Texto("quanto custa o kg?"),
                            {"nudges": reg.TETO_NUDGES}, reg.NOS, reg.TERMINAIS)

    assert decisao.proximo_no == "T_HUMANO"
    assert decisao.efeitos.silenciar_ia is True
    assert decisao.efeitos.handoff is False, (
        "se o T_HUMANO passar a pedir handoff, a nota deixa de ser escrita — e é "
        "este assert que avisa"
    )

    with _crm_mockado(deal=None) as crm:
        effects.aplicar(decisao.efeitos, lead=_lead(), conversation_id="c1",
                        fluxo=effects.FLUXO_VALERIA)

    obs, _sistema = _notas(crm)
    assert obs == [_nota_silencio(effects.FLUXO_VALERIA)]


# ═══════════════════════════════════════════════════════════════════════════
# 4. REGRESSÃO DA RECUPERAÇÃO — o fluxo em produção grava o que já gravava
# ═══════════════════════════════════════════════════════════════════════════
# Listas COMPLETAS, não "não contém": `effects.py` é compartilhado com um bot que
# está em produção, e o que importa é que nada do que ele escreve mude.
class TestARecuperacaoNaoMuda:
    def test_handoff_grava_as_mesmas_duas_notas_de_sempre(self):
        """`_decidir_quente` (botão "Preciso repor" / classe QUENTE) e a trilha C."""
        with _crm_mockado() as crm:  # com card no funil da Reativação, o caso real
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

    def test_nenhuma_decisao_dela_pede_os_dois_efeitos_juntos(self):
        """A razão ESTRUTURAL de nada acima poder mudar.

        No motor da Recuperação `silenciar_ia` e `handoff` nunca saem no MESMO
        `Efeitos` — a supressão da nota é, para ela, código que não executa. No dia
        em que um caminho novo combinar os dois, a nota dela deixa de ser escrita em
        silêncio; é este teste que avisa antes.
        """
        eventos: list[object] = [Classificado(c) for c in engine.CLASSES]
        eventos += [Clique(b.id, b.titulo) for b in flows.TODOS_BOTOES_NIVEL1]
        eventos += [Clique(b.id, b.titulo) for b in flows.BOTOES_PRAZO]
        eventos.append(Texto("me manda a tabela"))

        for no in (flows.NO_INTERESSE, flows.NO_PRAZO, flows.NO_ENCERRADO):
            for nudged in (False, True):
                for trilha in flows.BOTOES_POR_TRILHA:
                    for evento in eventos:
                        d = engine.decidir(estado(no, nudged=nudged, trilha=trilha),
                                           evento, canal_do_vendedor=False,
                                           contexto=CTX)
                        assert not (d.efeitos.silenciar_ia and d.efeitos.handoff), (
                            f"{no}/{trilha}/nudged={nudged}/{evento!r} passou a pedir "
                            "os dois efeitos: a nota de silêncio da Recuperação "
                            "deixaria de ser gravada"
                        )
