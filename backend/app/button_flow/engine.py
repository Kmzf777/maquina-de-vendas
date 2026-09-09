"""Motor de decisão do bot de botões. Núcleo puro: sem banco, sem rede, sem relógio.

Recebe o estado do fluxo e um evento (clique ou texto) e devolve uma Decisao —
o que responder, o que mudar no CRM e para qual nó ir. Todo I/O fica no runner.

Mesmo contrato de app/agent/persona.py: função pura em cima de dicts, testável
com a matriz completa de casos sem nenhum mock.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from app.button_flow import flows
from app.button_flow.flows import Botao, Prazo


# ── Eventos de entrada ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class Clique:
    """Clique num botão. `payload` é o id (interativa) ou o texto (template)."""
    payload: str
    titulo: str


@dataclass(frozen=True)
class Texto:
    conteudo: str


Evento = Clique | Texto


# ── Saída ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Mensagem:
    corpo: str
    botoes: tuple[Botao, ...] = ()
    enviar_cartao_vendedor: bool = False


@dataclass(frozen=True)
class Efeitos:
    tags: tuple[str, ...] = ()
    optout: bool = False
    handoff: bool = False
    recontato_meses: int | None = None
    # Desliga lead.ai_enabled sem carimbar handoff. Necessário porque "encerrado"
    # só tira o bot do caminho: no número da ValerIA o LLM assumiria a conversa
    # logo em seguida, que é o contrário de entregar ao vendedor.
    silenciar_ia: bool = False


@dataclass(frozen=True)
class Decisao:
    proximo_no: str
    mensagem: Mensagem | None = None
    efeitos: Efeitos = field(default_factory=Efeitos)
    marcar_nudge: bool = False
    ignorar: bool = False


def normalizar(texto: str | None) -> str:
    """Minúsculas, sem acento, sem espaço nas pontas — para casar rótulo de template.

    Necessário porque quick reply de template devolve o payload igual ao TEXTO do
    botão, e o teclado do lead (ou o próprio WhatsApp) pode devolver sem acento.

    Aceita None porque o payload do webhook é opcional em vários formatos da Meta;
    o chamador não deve precisar tratar isso antes de comparar.
    """
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.strip().lower()


# Índices de casamento, montados uma vez no import.
_POR_ID: dict[str, tuple[str, Botao]] = {
    b.id: (no, b) for no, botoes in flows.BOTOES_POR_NO.items() for b in botoes
}
# Todos os rótulos aceitos de cada botão entram no índice: um clique vindo do
# template traz o rótulo longo, um vindo do nudge traz o curto — os dois são o
# mesmo botão (ver Botao.titulos_aceitos).
_POR_TITULO: dict[str, tuple[str, Botao]] = {
    normalizar(titulo): (no, b)
    for no, botoes in flows.BOTOES_POR_NO.items()
    for b in botoes
    for titulo in b.titulos_aceitos
}
_PRAZO_POR_ID: dict[str, Prazo] = {p.id: p for p in flows.PRAZOS}


def _casar(clique: Clique) -> tuple[str, Botao] | None:
    """Resolve (nó dono, botão) de um clique. None = botão não é deste fluxo."""
    achado = _POR_ID.get(clique.payload)
    if achado:
        return achado
    achado = _POR_TITULO.get(normalizar(clique.payload))
    if achado:
        return achado
    return _POR_TITULO.get(normalizar(clique.titulo))


def _estado_valido(estado: dict | None) -> str | None:
    """Nó atual, ou None se o estado for incompatível/corrompido.

    Estado ausente (None/{}) é legítimo: é o primeiro inbound de uma conversa que
    o disparo semeou e ainda não passou pelo bot. Já um `flow` de outra versão ou
    um `node` que não existe são incompatíveis — o fluxo mudou debaixo do lead e a
    única resposta segura é devolver ao humano.

    Um flow_state que não é objeto é corrompido, não "não iniciado": jsonb aceita
    escalar e array, e tratar `[]` como ausente reiniciaria o lead do zero e o
    renudgearia, enquanto uma string quebraria no .get() logo abaixo.
    """
    if estado is not None and not isinstance(estado, dict):
        return None
    if not estado:
        return flows.NO_INTERESSE
    if estado.get("flow") != flows.FLOW_ID:
        return None
    no = estado.get("node")
    if no not in (flows.NO_INTERESSE, flows.NO_PRAZO, flows.NO_ENCERRADO):
        return None
    return no


def _nudge(no: str) -> Decisao:
    return Decisao(
        proximo_no=no,
        mensagem=Mensagem(
            corpo=flows.CORPO_NUDGE_POR_NO[no],
            botoes=flows.BOTOES_POR_NO[no],
        ),
        marcar_nudge=True,
    )


_ENTREGAR_AO_HUMANO = Decisao(
    proximo_no=flows.NO_ENCERRADO,
    efeitos=Efeitos(tags=(flows.TAG_HUMANO,), silenciar_ia=True),
)


def decidir(estado: dict | None, evento: Evento, *, canal_do_vendedor: bool) -> Decisao:
    """Decide o próximo passo do fluxo. Pura: mesma entrada, mesma saída, sempre.

    `canal_do_vendedor` distingue o número do João do número da ValerIA: no número
    do próprio vendedor não faz sentido mandar o cartão de contato dele.
    """
    no = _estado_valido(estado)
    if no is None:
        return _ENTREGAR_AO_HUMANO
    if no == flows.NO_ENCERRADO:
        return Decisao(proximo_no=flows.NO_ENCERRADO, ignorar=True)

    if isinstance(evento, Clique):
        casado = _casar(evento)
        if casado:
            no_dono, botao = casado
            if no_dono != no:
                # Botão do fluxo, mas de outro nó — lead tocou duas vezes ou rolou a
                # conversa e clicou no template de novo. Ignorar é o certo: não é
                # recusa a usar botões, e reprocessar o efeito seria duplicar CRM.
                return Decisao(proximo_no=no, ignorar=True)
            return _decidir_botao(no, botao, canal_do_vendedor=canal_do_vendedor)
        # Botão que não é deste fluxo: trata como texto livre.

    nudge_ja_dado = bool((estado or {}).get("nudged"))
    return _ENTREGAR_AO_HUMANO if nudge_ja_dado else _nudge(no)


def _decidir_botao(no: str, botao: Botao, *, canal_do_vendedor: bool) -> Decisao:
    if no == flows.NO_INTERESSE:
        if botao.id == flows.BTN_QUENTE.id:
            corpo = flows.MSG_QUENTE_VENDEDOR if canal_do_vendedor else flows.MSG_QUENTE_VALERIA
            return Decisao(
                proximo_no=flows.NO_ENCERRADO,
                mensagem=Mensagem(corpo=corpo, enviar_cartao_vendedor=not canal_do_vendedor),
                efeitos=Efeitos(tags=(flows.TAG_QUENTE,), handoff=True),
            )
        if botao.id == flows.BTN_TALVEZ.id:
            return Decisao(
                proximo_no=flows.NO_PRAZO,
                mensagem=Mensagem(corpo=flows.CORPO_PRAZO, botoes=flows.BOTOES_PRAZO),
            )
        if botao.id == flows.BTN_SAIR.id:
            return Decisao(
                proximo_no=flows.NO_ENCERRADO,
                mensagem=Mensagem(corpo=flows.MSG_OPTOUT),
                efeitos=Efeitos(tags=(flows.TAG_RECUSOU,), optout=True),
            )
        # Um botão novo no nível 1 cai no retorno inerte do fim. Isso é deliberado:
        # antes o opt-out era o fall-through, e um botão novo desligaria o lead da
        # base sem ninguém pedir — o pior default possível.
    elif no == flows.NO_PRAZO:
        prazo = _PRAZO_POR_ID.get(botao.id)
        if prazo is not None:
            return Decisao(
                proximo_no=flows.NO_ENCERRADO,
                mensagem=Mensagem(corpo=flows.MSG_PRAZO_FECHAMENTO.format(prazo=prazo.rotulo_humano)),
                efeitos=Efeitos(tags=(prazo.tag,), recontato_meses=prazo.meses),
            )

    # Nó ou botão sem tratamento aqui: inerte, nunca destrutivo. Hoje inalcançável,
    # mas um nó novo no fluxo não pode produzir efeito de CRM por acidente — nem
    # estourar StopIteration, que o runner engoliria como silêncio permanente.
    return Decisao(proximo_no=no, ignorar=True)
