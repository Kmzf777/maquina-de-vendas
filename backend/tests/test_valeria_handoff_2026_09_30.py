"""O handoff da ValerIA de botões: cartão de contato, vendedor certo e overrides.

Cinco defeitos medidos em 30/09/2026, todos no mesmo turno — o de entregar o lead
a uma pessoa. É o turno mais caro do fluxo: a auditoria do funil
(Diagnostico-Funil-Canastra-2026-09-01) mediu que a TROCA DE NÚMERO no handoff
perde 26% dos leads (131 de 500), e o cartão de contato é o único degrau que o
lead tem para alcançar o vendedor quando ele não está no número da conversa.

  1. Todo handoff de EXPORTAÇÃO era gravado como do João. `reg.TERMINAIS`
     declarava `vendedor="Arthur"` e `effects._aplicar_handoff` carimbava
     `agent.tools.SUPERVISOR_NAME` — no `metadata.handoff` E no marcador
     `[encaminhar_humano]` que o KPI de transbordos do dashboard conta.
  2. As notas de auditoria diziam "bot de recuperação" num lead que nunca esteve
     numa onda de recuperação. Quem as lê é o vendedor, antes de abordar.
  3. O handoff não mandava cartão de contato. O corpo promete "ele te responde em
     instantes" e o João está em OUTRO número (553491461669): sem cartão o lead
     é informado e fica sem como chamar — os 26% de novo.
  4. `valeria_content.aplicar_terminais` existia e o runner tinha de usá-la: sem
     isso, editar o texto do handoff na tela não mudava nada para o lead.
  5. O rótulo do botão que abre a lista ("Ver opções") não pertencia a nó nenhum
     e por isso nenhuma chave de `valeria_flow_content` o alcançava.

Dublês de provedor e de CRM, como test_valeria_runner_2026_09_29.py e
test_button_flow_effects_2026_08_20.py já fazem. O que se verifica aqui é
CONTRATO de envio (que chamada do provedor sai, com que argumentos) e o que fica
gravado no CRM — nunca texto de copy, que é editável na tela por desenho.
"""
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.agent import tools
from app.button_flow import effects, valeria_registry as reg
from app.button_flow import valeria_engine as motor
from app.button_flow import valeria_runner as runner
from app.button_flow.engine import Clique, Efeitos


class ProvedorFalso:
    """Registra a ORDEM das chamadas: corpo primeiro, cartão depois."""

    def __init__(self):
        self.chamadas = []

    async def send_interactive_buttons(self, to, body, buttons, image_url=None):
        self.chamadas.append(("botoes", body, buttons, image_url))
        return {"messages": [{"id": "wamid.1"}]}

    async def send_interactive_list(self, to, body, button, rows, header=None):
        self.chamadas.append(("lista", body, button, rows))
        return {"messages": [{"id": "wamid.2"}]}

    async def send_text(self, to, text):
        self.chamadas.append(("texto", text))
        return {"messages": [{"id": "wamid.3"}]}

    async def send_contact(self, to, contact_name, contact_phone):
        self.chamadas.append(("cartao", contact_name, contact_phone))
        return {"messages": [{"id": "wamid.4"}]}


def _cartoes(provedor) -> list[tuple[str, str]]:
    return [(c[1], c[2]) for c in provedor.chamadas if c[0] == "cartao"]


@pytest.fixture
def turno(monkeypatch):
    """Dirige `processar_inbound` com banco e CRM dublados.

    `no=` semeia o `flow_state` direto no nó desejado em vez de caminhar os 6-7
    cliques até ele: o que está sob teste é o TURNO do handoff, e uma caminhada
    completa por nó tornaria cada teste dependente de rótulos que a tela pode
    editar.
    """
    from app.button_flow import runner as runner_irmao
    from app.button_flow import valeria_content

    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    estado = {"valor": None}
    registro = {"efeitos": [], "kwargs": [], "mensagens": [], "notas": []}
    conversa = {"id": "C1", "stage": "atacado", "flow_state": None}
    lead = {"id": "L1", "phone": "5534988861441", "wa_id": "5534988861441",
            "name": "Roner", "human_control": False, "metadata": {}}

    def _gravar_estado(_cid, **kw):
        estado["valor"] = kw["flow_state"]
        conversa["flow_state"] = kw["flow_state"]

    monkeypatch.setattr(runner, "_reler_estado", lambda c: c.get("flow_state"))
    monkeypatch.setattr(runner, "get_open_deal", lambda _l: None)
    monkeypatch.setattr(runner, "update_conversation", _gravar_estado)
    monkeypatch.setattr(runner, "save_message",
                        lambda *a, **k: registro["mensagens"].append(a[3]))
    monkeypatch.setattr(runner, "url_publica_da_foto", lambda _c: None)
    monkeypatch.setattr(runner, "preco_do_no", lambda _no: "R$ 28,70")
    monkeypatch.setattr(runner, "save_score_evidence", lambda **_kw: None)
    # `_motivo_para_nao_rodar` é reusado do irmão e vai ao banco na terceira
    # checagem; contra a URL fake do conftest isso é só lentidão.
    monkeypatch.setattr(runner_irmao, "is_lead_blacklisted", lambda _l: False)
    monkeypatch.setattr(valeria_content, "carregar", lambda _f: {})
    monkeypatch.setattr(effects, "anotar",
                        lambda *a: registro["notas"].append(a[2]))

    def _aplicar(efeitos, **kw):
        registro["efeitos"].append(efeitos)
        registro["kwargs"].append(kw)
        return True
    monkeypatch.setattr(effects, "aplicar", _aplicar)

    provedor = ProvedorFalso()

    async def _rodar(texto, *, payload=None, titulo="", no=None, channel=None,
                     overrides=None):
        if no is not None:
            conversa["flow_state"] = {"flow": reg.FLOW_ID, "node": no, "nudges": 0}
        if overrides is not None:
            monkeypatch.setattr(valeria_content, "carregar", lambda _f: overrides)
        meta = {"payload": payload, "title": titulo} if payload else None
        await runner.processar_inbound(
            lead=lead, conversation=conversa, channel=channel or {"mode": "ai"},
            provider=provedor, texto=texto, metadata=meta, wamid="wamid.in",
        )
        return estado["valor"]

    _rodar.provedor = provedor
    _rodar.registro = registro
    _rodar.lead = lead
    return _rodar


# ═══════════════════════════════════════════════════════════════════════════
# Defeito 3 — o cartão de contato
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("no_de_origem,botao,terminal", [
    ("N5", "sim", "T_HANDOFF"),
    ("P1", "tenho_graos", "T_HANDOFF_PL"),
])
@pytest.mark.asyncio
async def test_handoff_do_joao_manda_corpo_e_cartao(turno, no_de_origem, botao,
                                                   terminal):
    """Os dois handoffs do João mandam o cartão DELE, depois do corpo.

    `tools.py:2012` declara o contrato de produção: "O sistema envia a mensagem e,
    em seguida, o cartão do João — NÃO cole telefone, link ou wa.me". O corpo do
    terminal promete "ele te responde em instantes" e o João atende em
    553491461669, não no número da ValerIA: sem o cartão o lead recebe a promessa
    e nenhum caminho até a pessoa.
    """
    estado = await turno("Sim, quero", payload=botao, no=no_de_origem)

    assert estado["node"] == terminal
    tipos = [c[0] for c in turno.provedor.chamadas]
    assert tipos == ["texto", "cartao"], "corpo primeiro, cartão em seguida"
    assert _cartoes(turno.provedor) == [(tools.SUPERVISOR_NAME,
                                         tools.SUPERVISOR_PHONE)]


@pytest.mark.asyncio
async def test_handoff_do_arthur_manda_o_cartao_do_arthur(turno):
    """Exportação é do Arthur, e o cartão tem de ser o DELE.

    Mandar o do João aqui entregaria o lead de exportação à pessoa errada — o
    ramo E existe justamente porque quem atende mercado externo é o Arthur
    (`reg.VENDEDOR_EXPORTACAO`).
    """
    estado = await turno("Sim, quero falar", payload="sim", no="E4")

    assert estado["node"] == "T_HANDOFF_ARTHUR"
    cartoes = _cartoes(turno.provedor)
    assert len(cartoes) == 1, f"um cartão, e só um: {turno.provedor.chamadas}"
    _nome, telefone = cartoes[0]
    assert telefone == tools.EXPORTACAO_PHONE
    assert telefone != tools.SUPERVISOR_PHONE, "mandou o número do João"


def test_numero_do_arthur_tem_o_mesmo_formato_do_do_joao():
    """+55 34 3226-2600 normalizado: só dígitos, mesma contagem do João.

    Fornecido pelo dono em 30/09/2026. É prefixo de FIXO em WhatsApp Business (sem
    o 9 do celular), e é por isso que a contagem bate com a do João apesar de ser
    outro tipo de linha. Um cartão com número mal normalizado é um cartão que não
    abre conversa — e cai no mesmo buraco de 26% que ele existe para tapar.
    """
    assert tools.EXPORTACAO_PHONE.isdigit()
    assert tools.EXPORTACAO_PHONE.startswith("55")
    assert len(tools.EXPORTACAO_PHONE) == len(tools.SUPERVISOR_PHONE)


@pytest.mark.asyncio
async def test_no_canal_do_proprio_vendedor_o_cartao_nao_vai(turno):
    """A regra `canal_do_vendedor` (engine.py:317), preservada.

    No número do próprio João o cartão dele seria absurdo: o lead JÁ está falando
    com ele. O corpo continua saindo — é a confirmação do encaminhamento.
    """
    canal = {"mode": "human", "phone": tools.SUPERVISOR_PHONE}
    await turno("Sim, quero", payload="sim", no="N5", channel=canal)

    assert [c[0] for c in turno.provedor.chamadas] == ["texto"]
    assert _cartoes(turno.provedor) == []


@pytest.mark.asyncio
async def test_canal_de_um_vendedor_ainda_manda_o_cartao_do_outro(turno):
    """Estar no número do João não é motivo para esconder o cartão do Arthur.

    A regra é "não mande o cartão de quem já está na conversa", não "não mande
    cartão em canal humano": o lead de exportação atendido no número do João
    precisa do caminho até o Arthur.
    """
    canal = {"mode": "human", "phone": tools.SUPERVISOR_PHONE}
    await turno("Sim, quero falar", payload="sim", no="E4", channel=canal)

    assert _cartoes(turno.provedor) == [(tools.EXPORTACAO_NAME,
                                         tools.EXPORTACAO_PHONE)]


@pytest.mark.asyncio
async def test_canal_humano_de_numero_desconhecido_nao_manda_cartao(turno):
    """Sem o número do canal não há como provar que ele não é o do vendedor.

    Único caso em que o silêncio ganha: é a regra do irmão (`mode == "human"`,
    engine.py:317) aplicada como degradação, e ela não acontece no número da
    ValerIA — onde 100% deste fluxo roda — porque lá o `mode` é 'ai'.
    """
    await turno("Sim, quero", payload="sim", no="N5", channel={"mode": "human"})
    assert _cartoes(turno.provedor) == []


def test_todo_vendedor_de_handoff_do_registry_tem_cartao():
    """Terminal que entrega a alguém sem cartão declarado = lead sem caminho.

    O runner loga ERROR e segue (o handoff não pode ser perdido por isso), mas o
    lead fica com a promessa e sem a pessoa — os 26%. Este teste falha no dia em
    que alguém acrescentar um terceiro vendedor no registry e esquecer o número.
    """
    declarados = {t.vendedor for t in reg.TERMINAIS.values() if t.handoff}
    assert declarados, "nenhum terminal de handoff no registry?"
    assert declarados <= set(runner.CARTOES), \
        f"vendedor sem cartão: {declarados - set(runner.CARTOES)}"


@pytest.mark.asyncio
async def test_falha_do_cartao_nao_desfaz_o_handoff(turno):
    """Cartão é a SEGUNDA mensagem: perdê-la não pode perder o turno.

    O corpo já saiu, os efeitos de CRM já foram aplicados (eles rodam ANTES do
    envio, de propósito) e o nó já avançou. Deixar a exceção subir aqui faria o
    lead reviver o nó anterior no turno seguinte e receber o handoff duas vezes.
    """
    async def explode(*_a, **_k):
        raise RuntimeError("Meta 131047")
    turno.provedor.send_contact = explode

    estado = await turno("Sim, quero", payload="sim", no="N5")

    assert estado["node"] == "T_HANDOFF"
    assert [c[0] for c in turno.provedor.chamadas] == ["texto"], "o corpo saiu"
    assert turno.registro["efeitos"][0].handoff is True, "efeitos aplicados"


@pytest.mark.asyncio
async def test_terminal_sem_handoff_nao_manda_cartao(turno):
    """`T_ADIAR` não entrega ninguém: cartão ali seria mensagem faturada a mais."""
    await turno("Não agora", payload="nao_agora", no="N5")
    assert _cartoes(turno.provedor) == []


# ═══════════════════════════════════════════════════════════════════════════
# Defeito 1 — o vendedor do terminal chega ao CRM
# ═══════════════════════════════════════════════════════════════════════════
def test_vendedor_declarado_no_terminal_chega_aos_efeitos():
    """O motor põe `terminal.vendedor` em `Efeitos`, senão o CRM nunca o vê."""
    clique = Clique(payload="sim", titulo="Sim, quero falar")
    decisao = motor.decidir("E4", clique, {}, reg.NOS, reg.TERMINAIS)
    assert decisao.proximo_no == "T_HANDOFF_ARTHUR"
    assert decisao.efeitos.vendedor == reg.VENDEDOR_EXPORTACAO

    clique_pl = Clique(payload="tenho_graos", titulo="Já tenho os grãos")
    decisao_pl = motor.decidir("P1", clique_pl, {}, reg.NOS, reg.TERMINAIS)
    assert decisao_pl.efeitos.vendedor == reg.VENDEDOR_ATACADO


# Portas de escrita/leitura de `effects`, todas de uma vez — mesmo padrão de
# `_crm_mockado` em test_button_flow_effects_2026_08_20.py. Sem o conjunto
# completo, um efeito não patcheado bateria no Supabase de verdade.
@contextmanager
def _crm_mockado():
    with patch("app.button_flow.effects.add_tags_to_lead") as add, \
         patch("app.button_flow.effects.update_lead") as upd, \
         patch("app.button_flow.effects.apply_optout_side_effects") as side, \
         patch("app.button_flow.effects.append_lead_observation") as obs, \
         patch("app.button_flow.effects.save_message") as save, \
         patch("app.button_flow.effects.get_open_deal", return_value=None) as aberto, \
         patch("app.button_flow.effects.move_deal_to_stage_key",
               return_value=True) as mover:
        yield SimpleNamespace(add=add, upd=upd, side=side, obs=obs, save=save,
                             deal=aberto, mover=mover)


def _lead() -> dict:
    """Lead NOVO por teste: `aplicar` MUTA `lead["metadata"]` de propósito."""
    return {"id": "lead-1", "phone": "5534988861441", "name": "Roner",
            "metadata": {}}


def _carimbo(crm) -> dict:
    gravados = [c.kwargs["metadata"] for c in crm.upd.call_args_list
                if "metadata" in c.kwargs]
    assert gravados, "handoff sem `metadata.handoff` (cascata de qualificados)"
    return gravados[-1]["handoff"]


def _marcador(crm) -> str:
    marcadores = [c.args[2] for c in crm.save.call_args_list
                  if c.args[1] == "system"
                  and c.args[2].startswith("[encaminhar_humano] Lead encaminhado")]
    assert len(marcadores) == 1, f"marcador do dashboard: {marcadores!r}"
    return marcadores[0]


def test_efeitos_com_vendedor_carimbam_esse_vendedor():
    """REPRO do defeito 1: era o João em 100% dos handoffs de exportação.

    Os dois registros — `metadata.handoff` (que `follow_up.should_proactive_handoff`
    lê) e o marcador que o KPI de transbordos conta — precisam dizer a MESMA
    pessoa, e ela tem de ser a do terminal.
    """
    lead = _lead()
    with _crm_mockado() as crm:
        ok = effects.aplicar(Efeitos(handoff=True, vendedor=reg.VENDEDOR_EXPORTACAO),
                             lead=lead, conversation_id="c1")

    assert ok is True
    assert _carimbo(crm)["vendedor"] == reg.VENDEDOR_EXPORTACAO
    assert reg.VENDEDOR_EXPORTACAO in _marcador(crm)
    assert tools.SUPERVISOR_NAME not in _marcador(crm)


def test_efeitos_sem_vendedor_mantem_o_padrao_de_hoje():
    """A Recuperação não passa vendedor — e continua carimbando o João.

    É a prova de que o campo é ADITIVO: o fluxo em produção grava exatamente o
    que gravava antes desta mudança.
    """
    lead = _lead()
    with _crm_mockado() as crm:
        effects.aplicar(Efeitos(handoff=True), lead=lead, conversation_id="c1")

    assert _carimbo(crm)["vendedor"] == tools.SUPERVISOR_NAME
    assert tools.SUPERVISOR_NAME in _marcador(crm)


# ═══════════════════════════════════════════════════════════════════════════
# Defeito 2 — a nota não pode dizer "recuperação" num lead da ValerIA
# ═══════════════════════════════════════════════════════════════════════════
def _todos_os_registros(crm) -> list[str]:
    """Tudo que um humano vai ler depois: observação, system message, metadata."""
    textos = [c.args[1] for c in crm.obs.call_args_list]
    textos += [c.args[2] for c in crm.save.call_args_list]
    textos += [json.dumps(c.kwargs["metadata"], ensure_ascii=False)
               for c in crm.upd.call_args_list if "metadata" in c.kwargs]
    return textos


def test_nenhum_registro_da_valeria_diz_recuperacao():
    """Quem lê a nota é o vendedor, antes de abordar o lead.

    "bot de recuperação" num lead que chegou pela ValerIA descreve uma onda de
    recuperação que nunca existiu — a mesma classe de mentira de auditoria que o
    relabel de 09/09 já corrigiu nos rótulos aposentados.
    """
    with _crm_mockado() as crm:
        for efeitos in (
            Efeitos(handoff=True, vendedor=reg.VENDEDOR_EXPORTACAO),
            Efeitos(optout=True),
            Efeitos(silenciar_ia=True),
            Efeitos(recontato_dias=30),
        ):
            effects.aplicar(efeitos, lead=_lead(), conversation_id="c1",
                            fluxo=effects.FLUXO_VALERIA)

    textos = _todos_os_registros(crm)
    assert textos, "nenhum registro gravado — o fluxo ficaria sem rastro"
    for texto in textos:
        assert "recuperação" not in texto.lower(), texto
        assert "recuperacao" not in texto.lower(), texto


def test_a_recuperacao_continua_dizendo_recuperacao():
    """O outro lado da mesma moeda: o fluxo em produção não muda de texto."""
    with _crm_mockado() as crm:
        effects.aplicar(Efeitos(handoff=True), lead=_lead(), conversation_id="c1")

    assert any("bot de recuperação" in t for t in _todos_os_registros(crm))


@pytest.mark.asyncio
async def test_o_runner_da_valeria_declara_o_proprio_fluxo(turno):
    """O rótulo do fluxo é do CHAMADOR: só ele sabe qual bot está rodando."""
    await turno("Sim, quero", payload="sim", no="N5")
    assert turno.registro["kwargs"][0]["fluxo"] == effects.FLUXO_VALERIA


# ═══════════════════════════════════════════════════════════════════════════
# Defeitos 4 e 5 — o que a tela edita tem de chegar ao lead
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_corpo_de_terminal_editado_na_tela_chega_ao_lead(turno):
    """O handoff é "o momento mais frágil" da conversa (auditoria 08/07).

    Sem `aplicar_terminais` no runner, o operador editava o texto do handoff na
    tela, salvava, e o lead continuava recebendo o do registry — override morto e
    invisível, o problema que `valeria_content` existe para não ter.
    """
    editado = "combinado, o João já vai te chamar por aqui"
    await turno("Sim, quero", payload="sim", no="N5",
                overrides={"T_HANDOFF": {"corpo": editado}})

    corpos = [c[1] for c in turno.provedor.chamadas if c[0] == "texto"]
    assert corpos == [editado]


@pytest.mark.asyncio
async def test_rotulo_do_botao_de_lista_editado_na_tela_chega_ao_lead(turno):
    """"Ver opções" é texto que o lead LÊ em toda tela de lista.

    Ele não pertence a nó nenhum, e `valeria_flow_content` é chaveada por
    `node_id`: sem chave reservada (como a do nudge) nenhuma linha da tabela o
    alcança e a tela não tem como editá-lo.
    """
    await turno("oi", overrides={reg.CHAVE_ROTULO_LISTA: {"corpo": "Escolher"}})

    listas = [c for c in turno.provedor.chamadas if c[0] == "lista"]
    assert listas, f"a tela de entrada é lista: {turno.provedor.chamadas}"
    assert listas[0][2] == "Escolher"


@pytest.mark.asyncio
async def test_sem_override_o_rotulo_da_lista_e_o_do_registry(turno):
    await turno("oi")
    listas = [c for c in turno.provedor.chamadas if c[0] == "lista"]
    assert listas[0][2] == reg.ROTULO_BOTAO_LISTA


def test_validar_aceita_a_chave_reservada_do_rotulo_da_lista():
    """`validar` é o portão de GRAVAÇÃO: sem esta chave a tela não salva.

    E o limite de 20 caracteres é da Meta, não preferência: acima dele o envio da
    lista é RECUSADO — a ValerIA ficaria muda em N0 e E1 depois de o operador
    achar que salvou.
    """
    from app.button_flow import valeria_content

    assert valeria_content.validar(reg.CHAVE_ROTULO_LISTA, {"corpo": "Escolher"}) is None
    assert valeria_content.validar(reg.CHAVE_ROTULO_LISTA, {"corpo": "   "}), \
        "rótulo em branco deixaria a folha de opções sem botão de abrir"
    assert valeria_content.validar(
        reg.CHAVE_ROTULO_LISTA, {"corpo": "x" * (reg.LIMITE_ROTULO_BOTAO + 1)})
