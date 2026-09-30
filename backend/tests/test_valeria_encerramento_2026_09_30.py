"""Chegar a um terminal ENCERRA o fluxo da ValerIA de botões — 30/09/2026.

O DEFEITO: terminal não carrega botão nenhum (só `T_ADIAR` carrega, e a folha dele
é declarada à parte, em `reg.BOTOES_PRAZO`). Então quando o fluxo já chegou ao
desfecho e o lead manda QUALQUER outra coisa, `valeria_engine.decidir` pula o ramo
do nudge — a guarda `if botoes and ...` é falsa numa tupla vazia — e cai na última
linha, `_ir_para(ID_HUMANO)`. Resultado medido na leitura do código: `T_HUMANO` é
REAPLICADO a cada mensagem seguinte, para sempre. Tag `TAG_HUMANO` regravada,
observação de CRM nova e mensagem de sistema nova em cada rodada, em cima da
conversa mais valiosa do funil — o mesmo ruído que `_notificar_sem_rodar` existe
para evitar, só que sem teto.

O conserto de 30/09 que carimbou `human_control` no handoff formal corta esse loop
para `T_HANDOFF`/`T_HANDOFF_PL`/`T_HANDOFF_ARTHUR`, via
`runner._motivo_para_nao_rodar` — mas SÓ para eles, e de propósito. Quem chega a
`T_HUMANO` sem transbordo formal (tocou "Tenho uma dúvida", ou digitou três vezes e
bateu no teto) corretamente NÃO recebe carimbo, porque não foi entregue a ninguém
(`tests/test_valeria_bridge_2026_09_30.py::test_silenciar_ia_sozinho_nao_assume_o_controle`
pina isso). Para esses o ruído continuava, uma rodada por mensagem, indefinidamente
— e o mesmo vale para `T_OPTOUT`, `T_FIM` e `T_ADIADO`, que também não carimbam nada.

O PADRÃO SEGUIDO é o do irmão, não um mecanismo novo: `engine.decidir` (o motor da
Recuperação, que já roda em produção) move o estado para o nó `encerrado` e devolve
`Decisao(ignorar=True)` nos turnos seguintes. Aqui o nó de destino JÁ é o terminal —
o runner grava `flow_state.node = "T_HUMANO"` —, então o que faltava era só a
guarda de leitura: terminal que não oferece botão é DESFECHO, não posição de espera.

── A exceção declarada: T_ADIAR ─────────────────────────────────────────────
`T_ADIAR` é terminal E posição de onde se clica (`prazos=True` faz o motor oferecer
os 30/60/90). Chegar nele não é o fim; clicar um prazo, que leva a `T_ADIADO`, é. A
guarda tem de ser derivada da DECLARAÇÃO (`Terminal.prazos`), nunca da tupla de
botões estar vazia — foi justamente ler "tupla vazia" como "nada a fazer" que
produziu o defeito.

── Onde o opt-out fica ──────────────────────────────────────────────────────
ACIMA da guarda de encerramento. A Meta EXIGE honrar o pedido de parar, e há 52
opt-outs perdidos em produção como prova do preço de não honrar; silenciar um "pare"
para economizar uma mensagem é o pior desfecho disponível. A ÚNICA exceção é quem já
está EM `T_OPTOUT`: ali o pedido está registrado (ver
`test_optout_repetido_no_proprio_t_optout_nao_reenvia_a_confirmacao`) e reaplicá-lo
não honra nada — só reenvia a confirmação, faturada, a quem pediu silêncio.
"""
import ast
from pathlib import Path

import pytest

from app.button_flow import flows
from app.button_flow import valeria_content, valeria_registry as reg
from app.button_flow import valeria_engine as motor
from app.button_flow import valeria_runner as runner
from app.button_flow.engine import Clique, Efeitos, Texto

VAZIO: dict = {}

# Os terminais de onde NÃO se clica — o fluxo acabou neles. Escritos à mão de
# propósito: derivar a lista de `Terminal.prazos` faria o teste concordar com
# qualquer coisa que o registry passasse a declarar, inclusive com um terminal novo
# que alguém esquecesse de encerrar. O cruzamento com o registry é feito UMA vez, em
# `test_a_lista_de_terminais_que_encerram_bate_com_o_registry`.
TERMINAIS_ENCERRADOS = (
    "T_HANDOFF", "T_HANDOFF_PL", "T_HANDOFF_ARTHUR",
    "T_ADIADO", "T_HUMANO", "T_FIM", "T_OPTOUT",
)

# O terminal que NÃO encerra: ele pergunta o prazo e espera o toque.
TERMINAL_QUE_PERGUNTA = "T_ADIAR"

# Texto humano de verdade, sem nenhum sinal de autoresponder (o detector do runner
# roda antes do motor e engoliria uma saudação de empresa).
TEXTO_DEPOIS = "e aí, tem novidade do meu pedido?"


def _clique(botao_id: str, titulo: str = "") -> Clique:
    return Clique(payload=botao_id, titulo=titulo)


# ═══════════════════════════════════════════════════════════════════════════════
# 1 · O motor: terminal alcançado devolve `ignorar`
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("terminal", TERMINAIS_ENCERRADOS)
def test_texto_depois_do_terminal_devolve_ignorar_sem_nenhum_efeito(terminal):
    """Nem mensagem, nem tag, nem opt-out, nem handoff, nem movimento de nó."""
    d = motor.decidir(terminal, Texto(TEXTO_DEPOIS), {"nudges": 0},
                      reg.NOS, reg.TERMINAIS)

    assert d.ignorar is True, f"{terminal} reprocessou o turno seguinte"
    assert d.mensagem is None, "gastou mensagem faturada num fluxo encerrado"
    assert d.efeitos == Efeitos(), f"efeitos de CRM reaplicados: {d.efeitos}"
    assert d.marcar_nudge is False
    assert d.criterios == {}
    assert d.proximo_no == terminal, "o nó se moveu depois do desfecho"


@pytest.mark.parametrize("terminal", TERMINAIS_ENCERRADOS)
def test_clique_atrasado_depois_do_terminal_tambem_e_ignorado(terminal):
    """O lead rola a conversa e toca num botão antigo. Reprocessar duplicaria CRM."""
    d = motor.decidir(terminal, _clique("sim", "Sim, quero falar"), {"nudges": 0},
                      reg.NOS, reg.TERMINAIS)

    assert d.ignorar is True
    assert d.mensagem is None
    assert d.efeitos == Efeitos()


def test_nem_o_teto_de_nudges_estourado_reabre_o_fluxo_encerrado():
    """A outra metade do defeito: com `nudges=3` a última linha também era
    `_ir_para(ID_HUMANO)`, então o loop existia nos dois lados da guarda."""
    d = motor.decidir("T_HUMANO", Texto(TEXTO_DEPOIS), {"nudges": reg.TETO_NUDGES},
                      reg.NOS, reg.TERMINAIS)
    assert d.ignorar is True
    assert d.proximo_no == "T_HUMANO"


def test_a_lista_de_terminais_que_encerram_bate_com_o_registry():
    """Terminal novo entra encerrando por default; só `prazos=True` escapa.

    Este é o teste que falha no dia em que alguém acrescentar um terminal — e é
    onde a decisão fica escrita, em vez de depender de o autor lembrar dela.
    """
    declarados = {t.id for t in reg.TERMINAIS.values() if not t.prazos}
    assert declarados == set(TERMINAIS_ENCERRADOS)

    perguntam = {t.id for t in reg.TERMINAIS.values() if t.prazos}
    assert perguntam == {TERMINAL_QUE_PERGUNTA}


def test_a_guarda_nao_pode_ser_lida_da_tupla_de_botoes_vazia():
    """Um NÓ sem botão (override de tela) não é fluxo encerrado — é nó quebrado.

    A distinção é o defeito original invertido: ler "tupla vazia" como "acabou"
    silenciaria um lead parado num nó que a tela esvaziou, quando o desfecho seguro
    daquele caso é justamente entregá-lo ao humano.
    """
    from dataclasses import replace
    nos = dict(reg.NOS)
    nos["N1"] = replace(reg.NOS["N1"], botoes=())

    d = motor.decidir("N1", Texto(TEXTO_DEPOIS), {"nudges": 0}, nos, reg.TERMINAIS)

    assert d.ignorar is False, "nó esvaziado pela tela foi tratado como desfecho"
    assert d.proximo_no == "T_HUMANO"


def test_no_vence_terminal_na_mesma_chave_como_no_casamento_de_botoes():
    """`_encerrado` e `_botoes_declarados` leem a MESMA posição: mesma precedência.

    Os dois dicionários são disjuntos hoje (`N*`/`P*`/`C*`/`E*` contra `T_*`) e nada
    garante isso por teste. Precedências diferentes entre as duas funções fariam a
    mesma string ser nó para uma e desfecho para a outra — a divergência que
    `campaigns/node_registry.py` documenta, dentro de um arquivo só.
    """
    from dataclasses import replace
    nos = dict(reg.NOS)
    nos["T_FIM"] = replace(reg.NOS["N1"], id="T_FIM")

    d = motor.decidir("T_FIM", Texto(TEXTO_DEPOIS), {"nudges": 0}, nos, reg.TERMINAIS)

    assert d.ignorar is False, "o nó homônimo foi lido como desfecho"
    assert d.marcar_nudge is True
    assert d.mensagem.botoes == reg.NOS["N1"].botoes


# ═══════════════════════════════════════════════════════════════════════════════
# 2 · A exceção: T_ADIAR continua sendo uma PERGUNTA
# ═══════════════════════════════════════════════════════════════════════════════
def test_t_adiar_continua_oferecendo_os_tres_prazos():
    """Chegar em `T_ADIAR` não é o fim: é a pergunta "quando te chamo de novo?"."""
    d = motor.decidir("N5", _clique("nao_agora"), VAZIO, reg.NOS, reg.TERMINAIS)

    assert d.ignorar is False
    assert d.mensagem is not None, "T_ADIAR encerrou em vez de perguntar"
    assert d.mensagem.botoes == reg.BOTOES_PRAZO
    assert len(d.mensagem.botoes) == 3


@pytest.mark.parametrize("prazo_id,dias", [("snooze30", 30), ("snooze60", 60),
                                           ("snooze90", 90)])
def test_o_toque_no_prazo_ainda_chega_ao_t_adiado_com_recontato(prazo_id, dias):
    """A aresta que a guarda de encerramento não pode cortar."""
    d = motor.decidir(TERMINAL_QUE_PERGUNTA, _clique(prazo_id), VAZIO,
                      reg.NOS, reg.TERMINAIS)

    assert d.ignorar is False
    assert d.proximo_no == "T_ADIADO"
    assert d.efeitos.recontato_dias == dias
    assert d.mensagem is not None
    assert d.mensagem.corpo == flows.MSG_PRAZO_FECHAMENTO


def test_texto_livre_no_t_adiar_ainda_reoferece_a_folha_de_prazos():
    """Quem digita em vez de tocar recebe os 30/60/90 de novo — ele foi PERGUNTADO."""
    d = motor.decidir(TERMINAL_QUE_PERGUNTA, Texto("depois eu vejo"), {"nudges": 0},
                      reg.NOS, reg.TERMINAIS)

    assert d.ignorar is False
    assert d.marcar_nudge is True
    assert d.mensagem is not None
    assert d.mensagem.botoes == reg.BOTOES_PRAZO


def test_o_teto_de_nudges_continua_valendo_no_t_adiar():
    """`T_ADIAR` não é encerrado, então o teto ainda é o que o protege do loop."""
    d = motor.decidir(TERMINAL_QUE_PERGUNTA, Texto("depois eu vejo"),
                      {"nudges": reg.TETO_NUDGES}, reg.NOS, reg.TERMINAIS)

    assert d.ignorar is False
    assert d.proximo_no == "T_HUMANO"


# ═══════════════════════════════════════════════════════════════════════════════
# 3 · O opt-out sobrevive ao encerramento
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("terminal",
                         [t for t in TERMINAIS_ENCERRADOS if t != "T_OPTOUT"])
@pytest.mark.parametrize("frase", ["pare", "PARAR", "descadastrar",
                                   "não quero mais"])
def test_pedido_de_saida_depois_do_fluxo_encerrado_registra_o_optout(terminal, frase):
    """A Meta EXIGE honrar. Silenciar isso é o pior desfecho disponível.

    52 pessoas em produção clicaram opt-out e seguiram elegíveis — é essa dívida
    que a ORDEM das duas guardas existe para não repetir.
    """
    d = motor.decidir(terminal, Texto(frase), {"nudges": reg.TETO_NUDGES},
                      reg.NOS, reg.TERMINAIS)

    assert d.ignorar is False, f"opt-out silenciado em {terminal}"
    assert d.proximo_no == "T_OPTOUT"
    assert d.efeitos.optout is True
    assert reg.TAG_OPTOUT in d.efeitos.tags
    assert d.marcar_nudge is False, "opt-out não gasta nudge"


def test_optout_repetido_no_proprio_t_optout_nao_reenvia_a_confirmacao():
    """A única exceção da ordem, e a razão dela é aritmética.

    O nó só vira `T_OPTOUT` depois de `effects.aplicar` devolver True — o runner
    aborta o turno e NÃO avança o estado quando a gravação do `opt_out` falha
    (`valeria_runner._executar_turno`: "Só o opt-out devolve False"). Ou seja,
    `node == "T_OPTOUT"` é prova de que o pedido está registrado: reaplicá-lo não
    honra nada que já não esteja honrado, e a confirmação ("não te mando mais
    mensagem por aqui") sai de novo, faturada, para quem acabou de pedir silêncio.
    """
    d = motor.decidir("T_OPTOUT", Texto("pare"), {"nudges": 0},
                      reg.NOS, reg.TERMINAIS)

    assert d.ignorar is True
    assert d.mensagem is None, "reenviou a confirmação de opt-out"
    assert d.efeitos == Efeitos()


def test_frase_que_apenas_contem_a_palavra_nao_reabre_o_fluxo_encerrado():
    """Casamento por IGUALDADE normalizada: "não quero trocar de fornecedor" não é
    pedido de saída — e num fluxo encerrado continua sendo silêncio, não um
    `T_OPTOUT` acidental nem um `T_HUMANO` reaplicado."""
    d = motor.decidir("T_HANDOFF", Texto("não quero trocar de fornecedor"),
                      {"nudges": 0}, reg.NOS, reg.TERMINAIS)

    assert d.ignorar is True
    assert d.efeitos.optout is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4 · O lead NO MEIO do fluxo não sente nada
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("nudges_antes,espera_bloqueio",
                         [(0, False), (1, False), (2, False), (3, True)])
def test_nudge_e_teto_no_meio_do_fluxo_continuam_identicos(nudges_antes,
                                                           espera_bloqueio):
    d = motor.decidir("N1", Texto("quanto custa o kg?"), {"nudges": nudges_antes},
                      reg.NOS, reg.TERMINAIS)

    assert d.ignorar is False
    if espera_bloqueio:
        assert d.proximo_no == "T_HUMANO"
        assert d.mensagem is None
        assert d.efeitos.silenciar_ia is True
    else:
        assert d.proximo_no == "N1"
        assert d.marcar_nudge is True
        assert d.mensagem.corpo == reg.CORPO_NUDGE
        assert d.mensagem.botoes == reg.NOS["N1"].botoes


def test_clique_no_meio_do_fluxo_continua_avancando_e_gravando_score():
    d = motor.decidir("N1", _clique("cafeteria", "Cafeteria"), {"nudges": 2},
                      reg.NOS, reg.TERMINAIS)

    assert d.ignorar is False
    assert d.proximo_no == "N2"
    assert d.criterios == {"segment": "cafeteria"}
    assert d.marcar_nudge is False


def test_no_desconhecido_continua_caindo_no_humano_em_vez_de_ignorar():
    """`flow_state` corrompido é erro, não desfecho: silenciá-lo perderia o lead."""
    d = motor.decidir("NAO_EXISTE", _clique("x"), VAZIO, reg.NOS, reg.TERMINAIS)

    assert d.ignorar is False
    assert d.proximo_no == "T_HUMANO"


# ═══════════════════════════════════════════════════════════════════════════════
# 5 · O runner: CINCO mensagens depois do terminal, UM efeito no total
#     (este é o defeito medido — a contagem, não a última decisão)
# ═══════════════════════════════════════════════════════════════════════════════
class ProvedorFalso:
    def __init__(self):
        self.chamadas = []

    async def send_interactive_buttons(self, to, body, buttons, image_url=None):
        self.chamadas.append(("botoes", body, buttons, image_url))
        return {"messages": [{"id": "wamid.1"}]}

    async def send_interactive_list(self, to, body, button, rows, header=None):
        self.chamadas.append(("lista", body, rows))
        return {"messages": [{"id": "wamid.2"}]}

    async def send_text(self, to, text):
        self.chamadas.append(("texto", text))
        return {"messages": [{"id": "wamid.3"}]}

    async def send_contact(self, to, contact_name, contact_phone):
        self.chamadas.append(("cartao", contact_name, contact_phone))
        return {"messages": [{"id": "wamid.4"}]}


@pytest.fixture
def turno(monkeypatch):
    """Dirige `processar_inbound` com banco, CRM e histórico dublados.

    Mesma forma das fixtures de `test_valeria_runner_2026_09_29.py` e
    `test_valeria_handoff_2026_09_30.py`, com `no=` para semear o `flow_state` e
    `_historico` dublado (o detector de autoresponder pede o lag da nossa última
    saída em todo texto livre; sem o dublê cada turno tentaria resolver DNS).

    `effects.aplicar` é contado e devolve True — o lead desta fixture nunca recebe
    `human_control`, e isso é deliberado: é exatamente o lead que o carimbo de
    handoff NÃO alcança, o que sobra do defeito depois do conserto de 30/09.
    """
    from app.button_flow import effects
    from app.button_flow import runner as irmao

    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.setattr(irmao, "is_lead_blacklisted", lambda _lead_id: False)

    registro = {"efeitos": [], "mensagens": [], "notas": [], "gravacoes": [],
                "metadata": []}
    conversa = {"id": "C1", "stage": "atacado", "flow_state": None}
    lead = {"id": "L1", "phone": "5534988861441", "wa_id": "5534988861441",
            "name": "Roner", "human_control": False, "metadata": {}}

    def _gravar_estado(_cid, **kw):
        registro["gravacoes"].append(kw["flow_state"])
        conversa["flow_state"] = kw["flow_state"]

    monkeypatch.setattr(runner, "_reler_estado", lambda c: c.get("flow_state"))
    monkeypatch.setattr(runner, "get_open_deal", lambda _l: None)
    monkeypatch.setattr(runner, "update_conversation", _gravar_estado)
    monkeypatch.setattr(runner, "save_message",
                        lambda *a, **k: registro["mensagens"].append(a[3]))
    monkeypatch.setattr(runner, "url_publica_da_foto", lambda _c: None)
    monkeypatch.setattr(runner, "preco_do_no", lambda _no: "R$ 28,70")
    monkeypatch.setattr(runner, "save_score_evidence", lambda **_kw: None)
    monkeypatch.setattr(runner, "_historico", lambda _cid: [])
    monkeypatch.setattr(valeria_content, "carregar", lambda _f: {})
    monkeypatch.setattr(effects, "anotar",
                        lambda *a: registro["notas"].append(a[2]))
    monkeypatch.setattr(effects, "atualizar_metadata",
                        lambda _l, campos, **_kw: registro["metadata"].append(campos))

    def _aplicar(efeitos, **_kw):
        registro["efeitos"].append(efeitos)
        return True
    monkeypatch.setattr(effects, "aplicar", _aplicar)

    provedor = ProvedorFalso()

    async def _rodar(texto, *, payload=None, titulo="", no=None):
        if no is not None:
            conversa["flow_state"] = {"flow": reg.FLOW_ID, "node": no, "nudges": 0}
        meta = {"payload": payload, "title": titulo} if payload else None
        await runner.processar_inbound(
            lead=lead, conversation=conversa, channel={"mode": "ai"},
            provider=provedor, texto=texto, metadata=meta, wamid="wamid.in",
        )
        return conversa["flow_state"]

    _rodar.provedor = provedor
    _rodar.registro = registro
    _rodar.conversa = conversa
    _rodar.lead = lead
    return _rodar


@pytest.mark.asyncio
async def test_cinco_mensagens_depois_do_t_humano_aplicam_o_efeito_UMA_vez(turno):
    """O defeito medido, na forma de contagem.

    O lead toca "Tenho uma dúvida" no C1 e vai para `T_HUMANO` — sem transbordo
    formal, porque não foi entregue a ninguém, e por isso sem `human_control` para o
    guarda `_motivo_para_nao_rodar` morder. Antes desta guarda, cada mensagem
    seguinte reaplicava `T_HUMANO`: seis rodadas de tag, observação e mensagem de
    sistema para um lead, e sem teto.
    """
    estado = await turno("Tenho uma dúvida", payload="duvida",
                         titulo="Tenho uma dúvida", no="C1")
    assert estado["node"] == "T_HUMANO"
    assert len(turno.registro["efeitos"]) == 1
    gravacoes_ate_aqui = len(turno.registro["gravacoes"])
    mensagens_ate_aqui = len(turno.registro["mensagens"])

    for _ in range(5):
        await turno(TEXTO_DEPOIS)

    assert len(turno.registro["efeitos"]) == 1, (
        f"efeitos do terminal reaplicados {len(turno.registro['efeitos'])}x")
    assert len(turno.registro["gravacoes"]) == gravacoes_ate_aqui, \
        "turno ignorado gravou flow_state"
    assert len(turno.registro["mensagens"]) == mensagens_ate_aqui, \
        "turno ignorado gastou mensagem faturada"
    assert turno.registro["notas"] == [], "turno ignorado escreveu observação"
    assert turno.conversa["flow_state"]["node"] == "T_HUMANO", "o nó se moveu"


@pytest.mark.parametrize("terminal", TERMINAIS_ENCERRADOS)
@pytest.mark.asyncio
async def test_cinco_mensagens_depois_de_cada_terminal_nao_aplicam_efeito_nenhum(
        turno, terminal):
    """Semeado direto no terminal: nenhum dos sete reprocessa o turno seguinte."""
    await turno(TEXTO_DEPOIS, no=terminal)
    for _ in range(4):
        await turno(TEXTO_DEPOIS)

    assert turno.registro["efeitos"] == []
    assert turno.registro["gravacoes"] == []
    assert turno.provedor.chamadas == []
    assert turno.registro["notas"] == []
    assert turno.conversa["flow_state"]["node"] == terminal


@pytest.mark.asyncio
async def test_pedido_de_saida_depois_do_terminal_chega_ao_crm_pelo_runner(turno):
    """Ponta a ponta: o lead transbordado que pede para sair é registrado.

    Aqui está a prova de que a ORDEM das guardas no motor sobrevive à travessia do
    runner — o `opt_out` é o único efeito que a Meta exige e o único que não pode
    depender de o fluxo ainda estar aberto.
    """
    await turno(TEXTO_DEPOIS, no="T_HANDOFF")
    assert turno.registro["efeitos"] == []

    estado = await turno("descadastrar")

    assert estado["node"] == "T_OPTOUT"
    assert len(turno.registro["efeitos"]) == 1
    assert turno.registro["efeitos"][0].optout is True
    assert [c[0] for c in turno.provedor.chamadas] == ["texto"], \
        "o lead não recebeu a confirmação de que foi atendido"

    # E daí em diante, silêncio: o segundo "pare" não reenvia a confirmação.
    await turno("pare")
    assert len(turno.registro["efeitos"]) == 1
    assert len(turno.provedor.chamadas) == 1


@pytest.mark.asyncio
async def test_o_que_a_guarda_de_encerramento_NAO_alcanca_no_transbordo_formal(turno):
    """A metade que este conserto não fecha, pinada para não ser esquecida.

    Depois de um transbordo FORMAL o lead carrega `human_control=true`, e
    `runner._motivo_para_nao_rodar` é o PRIMEIRO guarda do turno — antes de o evento
    ser montado, antes do motor. Então a ordem opt-out-acima-do-encerramento que este
    arquivo estabelece NO MOTOR não é sequer consultada nesse caso: um "pare" digitado
    depois de `T_HANDOFF` produz a nota de "bot saiu de cena" e NÃO grava `opt_out`.

    Isso é ANTERIOR a esta mudança (o guarda é de 30/09 e vale igual para o fluxo da
    Recuperação) e é um trade-off defensável — depois do transbordo há uma pessoa lendo
    a conversa, que pode honrar o pedido à mão. Mas a coluna `opt_out` fica false e o
    lead segue elegível à próxima onda, que é exatamente a forma dos 52 casos de
    produção. Fechá-lo é uma decisão de ORDEM DE GUARDAS no runner (deixar o pedido de
    saída atravessar `_motivo_para_nao_rodar`), não de motor — e se alguém a tomar,
    ESTE teste falha, que é onde a decisão fica escrita.
    """
    await turno(TEXTO_DEPOIS, no="T_HANDOFF")
    turno.lead["human_control"] = True

    await turno("pare")

    assert turno.registro["efeitos"] == [], "o guarda deixou de ser o primeiro"
    assert len(turno.registro["notas"]) == 1, "a nota de 'saiu de cena' não saiu"
    assert turno.provedor.chamadas == []


@pytest.mark.asyncio
async def test_o_lead_no_meio_do_fluxo_continua_recebendo_a_reoferta(turno):
    """Controle: a guarda nova não pode emudecer quem ainda está conversando."""
    estado = await turno("e quanto custa o quilo?", no="N1")

    assert estado["node"] == "N1"
    assert estado["nudges"] == 1
    assert len(turno.provedor.chamadas) == 1
    assert reg.CORPO_NUDGE in turno.provedor.chamadas[0][1]
    assert len(turno.registro["efeitos"]) == 1, "o nudge é um turno normal"


# ═══════════════════════════════════════════════════════════════════════════════
# 6 · As três armadilhas que já morderam esta feature
# ═══════════════════════════════════════════════════════════════════════════════
_TOCADOS = ("app/button_flow/valeria_engine.py", "app/button_flow/effects.py")


@pytest.mark.parametrize("caminho", _TOCADOS)
def test_arquivo_tocado_continua_sendo_python_valido(caminho):
    """Uma quebra de linha real dentro de um literal já derrubou um módulo aqui."""
    fonte = Path(__file__).resolve().parent.parent / caminho
    ast.parse(fonte.read_text(encoding="utf-8"), filename=str(fonte))


@pytest.mark.parametrize("caminho", _TOCADOS)
def test_arquivo_tocado_nao_carrega_caractere_invisivel(caminho):
    """Um `\\u200e` decodificado em caractere literal já inverteu um teste em
    silêncio. Codepoint não-ASCII em `app/` aqui só pode ser acento de prosa."""
    fonte = (Path(__file__).resolve().parent.parent / caminho).read_text(
        encoding="utf-8")
    proibidos = {chr(0x200E), chr(0x200F), chr(0x200B), chr(0xFEFF), chr(0x00A0)}
    achados = sorted({hex(ord(c)) for c in fonte if c in proibidos})
    assert achados == [], f"{caminho} carrega invisível: {achados}"


def test_os_acentos_do_motor_atravessaram_o_arquivo_intactos():
    """Acento virando '?' é modo de falha recorrente neste repo.

    Os dois lados que a guarda nova atravessa: a lista de opt-out (que o motor
    normaliza, então a entrada acentuada tem de colapsar na sem acento) e a tag de
    desfecho, resolvida por NOME EXATO — um acento perdido ali não levanta nada, só
    deixa de marcar o lead. O caractere esperado é montado com `chr()`, nunca colado.
    """
    assert motor.normalizar("Não quero mais") in motor.FRASES_OPTOUT
    assert reg.TAG_OPTOUT == "Bot" + chr(0x00F5) + "es: Opt-out"
