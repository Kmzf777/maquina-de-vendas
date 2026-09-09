"""Motor de decisão do bot de botões. Núcleo puro: sem banco, sem rede, sem relógio.

Recebe o estado do fluxo e um evento (clique, texto ou classe já apurada) e devolve
uma Decisao — o que responder, o que mudar no CRM e para qual nó ir. Todo I/O fica
no runner.

Mesmo contrato de app/agent/persona.py e app/agent/handoff.py: função pura em cima
de dicts, testável com a matriz completa de casos sem nenhum mock.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field, replace

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


@dataclass(frozen=True)
class Classificado:
    """Texto livre já classificado pela camada 2. `classe` é uma das CLASSES.

    Existe como evento separado — em vez de o runner traduzir classe em Decisao —
    para que a matriz classe x nó fique testável sem mock de LLM, no mesmo lugar
    onde a matriz botão x nó já vive.
    """
    classe: str


Evento = Clique | Texto | Classificado

# Classes da camada 2. O classificador nunca escreve para o cliente: ele devolve
# uma destas, e o efeito é o mesmo de um botão.
CLASSE_SAIR = "SAIR"
CLASSE_QUENTE = "QUENTE"
CLASSE_ADIAR = "ADIAR"
CLASSE_PERGUNTA = "PERGUNTA"
CLASSE_ENGANO = "ENGANO"
CLASSE_RUIDO = "RUIDO"

CLASSES: tuple[str, ...] = (
    CLASSE_SAIR, CLASSE_QUENTE, CLASSE_ADIAR,
    CLASSE_PERGUNTA, CLASSE_ENGANO, CLASSE_RUIDO,
)


# ── Contexto do lead (o que o motor precisa saber para montar a entrega) ────
@dataclass(frozen=True)
class Contexto:
    """Dados do lead usados nos textos. Tudo opcional: a coorte é irregular.

    `preco` só vem preenchido quando `produto` casou com um SKU ATIVO do catálogo.
    141 leads da coorte compravam outras marcas, 123 cápsula e 47 drip — nada disso
    existe nos 32 SKUs que o agente conhece, e cotar de memória foi exatamente o
    que perdeu as 500 unidades da Ritz (cotou drip a R$27,70 quando o real era
    R$2,49/sachê). Sem SKU, o motor reconhece o item pelo nome e NÃO cota.
    """
    primeiro_nome: str = ""
    produto: str = ""
    preco: str = ""


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
    recontato_dias: int | None = None
    # Desliga lead.ai_enabled sem carimbar handoff. Necessário porque "encerrado"
    # só tira o bot do caminho: no número da ValerIA o LLM assumiria a conversa
    # logo em seguida, que é o contrário de entregar ao vendedor.
    silenciar_ia: bool = False
    # Registra que o lead contestou o pretexto do template. Lido pelo operador
    # antes de qualquer nova onda — mandar de novo para quem já disse "não fiz
    # pedido nenhum" é o caminho mais curto para um report na Meta.
    pretexto_contestado: bool = False


@dataclass(frozen=True)
class Decisao:
    proximo_no: str
    mensagem: Mensagem | None = None
    efeitos: Efeitos = field(default_factory=Efeitos)
    marcar_nudge: bool = False
    ignorar: bool = False
    # Trilha inferida do clique, quando o clique revela qual template o lead
    # recebeu. O runner grava no estado para que o nudge seguinte use os rótulos
    # certos mesmo que o disparo não tenha semeado a trilha.
    trilha_inferida: str | None = None


def normalizar(texto: str | None) -> str:
    """Minúsculas, sem acento, sem espaço nas pontas — para casar rótulo de template.

    Necessário porque quick reply de template devolve o payload igual ao TEXTO do
    botão, e o teclado do lead (ou o próprio WhatsApp) pode devolver sem acento.
    Prova de produção: há 64 cliques gravados em "Nao tenho interesse" e ZERO em
    "Não tenho interesse".

    Aceita None porque o payload do webhook é opcional em vários formatos da Meta;
    o chamador não deve precisar tratar isso antes de comparar.
    """
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.strip().lower()


# ── Índices de casamento, montados uma vez no import ────────────────────────
# O casamento de nível 1 é GLOBAL (todas as trilhas), não por trilha: um clique
# precisa resolver mesmo que o estado não tenha trilha gravada — e ele próprio
# revela qual template o lead recebeu.
_NIVEL1_POR_ID: dict[str, Botao] = {b.id: b for b in flows.TODOS_BOTOES_NIVEL1}
_NIVEL1_POR_TITULO: dict[str, Botao] = {
    normalizar(titulo): b
    for b in flows.TODOS_BOTOES_NIVEL1
    for titulo in b.titulos_aceitos
}
_PRAZO_POR_ID: dict[str, Prazo] = {p.id: p for p in flows.PRAZOS}
_PRAZO_POR_TITULO: dict[str, Prazo] = {normalizar(p.titulo): p for p in flows.PRAZOS}

# Rótulo -> trilha, para inferir qual template o lead recebeu a partir do clique.
# "Parar mensagens" é comum às três e por isso não infere nada.
#
# Só o rótulo CANÔNICO de cada trilha entra aqui, nunca os `rotulos_extras`: eles
# existem para o casamento global (o mesmo id atendido por rótulos de trilhas
# diferentes) e, se entrassem, a última trilha iterada sobrescreveria as anteriores
# — "Retomar o pedido" passava a inferir `estoque` em vez de `pedido`, e o nudge
# seguinte oferecia os rótulos do template errado.
_TRILHA_POR_TITULO: dict[str, str] = {
    normalizar(_b.titulo): _trilha
    for _trilha, _botoes in flows.BOTOES_POR_TRILHA.items()
    for _b in _botoes
    if _b.id != flows.ID_OPTOUT
}


# Payload custom montado pelo disparo: `<flow>|<botao_id>|<trilha>|t<toque>`
# (broadcast/worker.py:montar_payload_botao). Ele carrega o que o clique sozinho
# não conta — a versão do fluxo e a TRILHA — e existe justamente para o casamento
# não depender do texto do rótulo. Sem esta função o payload seria emitido e nunca
# lido, e um rótulo reaprovado com uma vírgula a mais ("Preciso repor!") já bastaria
# para o clique virar texto livre.
_PAYLOAD_SEP = "|"


def _desmontar_payload(payload: str | None) -> tuple[str | None, str | None]:
    """(botao_id, trilha) de um payload custom, ou (None, None) se não for um.

    Só aceita payload da versão CORRENTE do fluxo: um payload de outra versão
    significa que o lead clicou num template disparado por um fluxo antigo, e
    ignorá-lo aqui faz o clique cair no caminho de estado incompatível, que devolve
    ao humano — o desfecho seguro. Função pura.
    """
    if not payload or _PAYLOAD_SEP not in payload:
        return None, None
    partes = payload.split(_PAYLOAD_SEP)
    if len(partes) < 3 or partes[0] != flows.FLOW_ID:
        return None, None
    botao_id = partes[1] or None
    trilha = partes[2] if partes[2] in flows.BOTOES_POR_TRILHA else None
    return botao_id, trilha


def _casar_nivel1(clique: Clique) -> Botao | None:
    botao_id, _ = _desmontar_payload(clique.payload)
    if botao_id:
        achado = _NIVEL1_POR_ID.get(botao_id)
        if achado:
            return achado
    achado = _NIVEL1_POR_ID.get(clique.payload)
    if achado:
        return achado
    achado = _NIVEL1_POR_TITULO.get(normalizar(clique.payload))
    if achado:
        return achado
    return _NIVEL1_POR_TITULO.get(normalizar(clique.titulo))


def _casar_prazo(clique: Clique) -> Prazo | None:
    botao_id, _ = _desmontar_payload(clique.payload)
    if botao_id:
        achado = _PRAZO_POR_ID.get(botao_id)
        if achado:
            return achado
    achado = _PRAZO_POR_ID.get(clique.payload)
    if achado:
        return achado
    achado = _PRAZO_POR_TITULO.get(normalizar(clique.payload))
    if achado:
        return achado
    return _PRAZO_POR_TITULO.get(normalizar(clique.titulo))


def _vocativo(primeiro_nome: str) -> str:
    """", Fulano" quando há nome; string vazia quando não há.

    O nome é opcional de propósito (`Contexto` documenta: "a coorte é irregular"),
    mas os textos traziam a vírgula colada no placeholder e um cadastro sem nome
    produzia "obrigado, ! deixei seu cadastro ativo" e "perfeito,\\n" — a primeira
    coisa que o cliente lê depois de até 7 anos sem contato. Na base do Bling o
    `leads.name` vem da razão social e às vezes é handle ou CPF ("RD Recepção",
    "@neimaraoliveirapsicotera", "ANA PAULA GAMA PEZZOT 40250877821"), então o campo
    vazio ou impróprio não é exceção rara.

    Manter a pontuação AQUI, e não no texto, é o que garante que nenhum texto novo
    de flows.py reintroduza o problema: quem escreve copy só escreve "{vocativo}".
    """
    nome = (primeiro_nome or "").strip()
    return f", {nome}" if nome else ""


def _e_optout(clique: Clique) -> bool:
    """True se este clique é o botão de saída, em qualquer trilha e qualquer nó."""
    botao = _casar_nivel1(clique)
    return botao is not None and botao.id == flows.ID_OPTOUT


def _trilha_do_clique(clique: Clique) -> str | None:
    _, trilha = _desmontar_payload(clique.payload)
    if trilha:
        return trilha
    for candidato in (clique.payload, clique.titulo):
        trilha = _TRILHA_POR_TITULO.get(normalizar(candidato))
        if trilha:
            return trilha
    return None


def trilha_de(estado: dict | None) -> str:
    """Trilha gravada no estado, ou o padrão. Usada para escolher os rótulos."""
    trilha = (estado or {}).get("trilha") if isinstance(estado, dict) else None
    return trilha if trilha in flows.BOTOES_POR_TRILHA else flows.TRILHA_PADRAO


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


def _botoes_do_no(no: str, trilha: str) -> tuple[Botao, ...]:
    if no == flows.NO_PRAZO:
        return flows.BOTOES_PRAZO
    return flows.BOTOES_POR_TRILHA[trilha]


def _nudge(no: str, trilha: str) -> Decisao:
    return Decisao(
        proximo_no=no,
        mensagem=Mensagem(
            corpo=flows.CORPO_NUDGE_POR_NO[no],
            botoes=_botoes_do_no(no, trilha),
        ),
        marcar_nudge=True,
    )


_ENTREGAR_AO_HUMANO = Decisao(
    proximo_no=flows.NO_ENCERRADO,
    efeitos=Efeitos(tags=(flows.TAG_HUMANO,), silenciar_ia=True),
)


def _decidir_quente(contexto: Contexto, *, canal_do_vendedor: bool) -> Decisao:
    """A entrega concreta + handoff. Zero perguntas depois disso."""
    dados = {
        "vocativo": _vocativo(contexto.primeiro_nome),
        "produto": contexto.produto,
        "preco": contexto.preco,
    }
    if contexto.produto and contexto.preco:
        corpo = flows.MSG_QUENTE_COM_PRODUTO
    elif contexto.produto:
        corpo = flows.MSG_QUENTE_SEM_PRECO
    else:
        corpo = flows.MSG_QUENTE_SEM_PRODUTO
    return Decisao(
        proximo_no=flows.NO_ENCERRADO,
        mensagem=Mensagem(
            corpo=flows.render(corpo, dados),
            # No número do próprio João, mandar o cartão de contato dele seria
            # absurdo — e é justamente o degrau que custa 26% dos leads.
            enviar_cartao_vendedor=not canal_do_vendedor,
        ),
        efeitos=Efeitos(tags=(flows.TAG_QUENTE,), handoff=True),
    )


def _decidir_optout() -> Decisao:
    return Decisao(
        proximo_no=flows.NO_ENCERRADO,
        mensagem=Mensagem(corpo=flows.MSG_OPTOUT),
        efeitos=Efeitos(tags=(flows.TAG_RECUSOU,), optout=True),
    )


def _decidir_adiar() -> Decisao:
    """Adiamento: sobe para o nó de prazo e pergunta QUANDO, nunca SE.

    Este é o slot mais valioso do menu. "Ainda tenho estoque" não é um não: em 9
    casos históricos no canal do João, 4 voltaram sozinhos e compraram (Roner, 12
    dias depois, R$ 5.500). E não existe um único "posso te chamar em X dias?" no
    dataset inteiro — o vendedor nunca agenda.
    """
    return Decisao(
        proximo_no=flows.NO_PRAZO,
        mensagem=Mensagem(corpo=flows.CORPO_PRAZO, botoes=flows.BOTOES_PRAZO),
    )


def decidir(
    estado: dict | None,
    evento: Evento,
    *,
    canal_do_vendedor: bool,
    contexto: Contexto | None = None,
) -> Decisao:
    """Decide o próximo passo do fluxo. Pura: mesma entrada, mesma saída, sempre.

    `canal_do_vendedor` distingue o número do João do número da ValerIA: no número
    do próprio vendedor não faz sentido mandar o cartão de contato dele.
    """
    contexto = contexto or Contexto()

    # O opt-out vence TUDO: nó, versão de estado e estado corrompido.
    #
    # Antes ele era só mais um botão do nível 1, e isso abria três buracos reais —
    # o lead que rola a conversa de volta até o template e toca "Parar mensagens"
    # estando no nó de prazo, o que toca depois do fluxo encerrado (pós-handoff), e
    # o que tem flow_state de outra versão. Nos três casos a resposta era silêncio,
    # e o lead seguia com opt_out=false, elegível ao toque D+4 e à próxima campanha.
    # É exatamente a dívida que já existe em produção: 52 pessoas clicaram opt-out e
    # continuam elegíveis. Reaplicar opt-out é idempotente e barato; perdê-lo é o
    # risco #1 da spec (LGPD + queda de qualidade do número).
    if isinstance(evento, Clique) and _e_optout(evento):
        return _decidir_optout()
    if isinstance(evento, Classificado) and evento.classe == CLASSE_SAIR:
        return _decidir_optout()

    no = _estado_valido(estado)
    if no is None:
        return _ENTREGAR_AO_HUMANO
    if no == flows.NO_ENCERRADO:
        return Decisao(proximo_no=flows.NO_ENCERRADO, ignorar=True)

    trilha = trilha_de(estado)

    if isinstance(evento, Clique):
        decisao = _decidir_clique(no, trilha, evento, canal_do_vendedor=canal_do_vendedor,
                                  contexto=contexto)
        if decisao is not None:
            return decisao
        # Botão que não é deste fluxo: cai na regra de texto livre.

    if isinstance(evento, Classificado):
        decisao = _decidir_classe(no, trilha, evento.classe,
                                  canal_do_vendedor=canal_do_vendedor, contexto=contexto)
        if decisao is not None:
            return decisao

    nudge_ja_dado = bool((estado or {}).get("nudged"))
    return _ENTREGAR_AO_HUMANO if nudge_ja_dado else _nudge(no, trilha)


def _decidir_clique(
    no: str, trilha: str, clique: Clique, *, canal_do_vendedor: bool, contexto: Contexto,
) -> Decisao | None:
    """Decisao para um clique, ou None se o botão não é deste fluxo."""
    if no == flows.NO_INTERESSE:
        botao = _casar_nivel1(clique)
        if botao is None:
            # Pode ser um clique de nível 2 chegando fora de hora: o lead tocou duas
            # vezes ou rolou a conversa. Ignorar é o certo — não é recusa a usar
            # botões, e reprocessar o efeito duplicaria CRM.
            if _casar_prazo(clique):
                return Decisao(proximo_no=no, ignorar=True)
            return None
        inferida = _trilha_do_clique(clique)
        decisao = _efeito_nivel1(botao, trilha, canal_do_vendedor=canal_do_vendedor,
                                 contexto=contexto)
        if decisao is None:
            return None
        # Um botão novo/desconhecido cai no retorno inerte de _efeito_nivel1, nunca
        # no opt-out. Antes o opt-out era o fall-through, e um botão novo desligaria
        # o lead da base sem ninguém pedir — o pior default possível.
        return replace(decisao, trilha_inferida=inferida) if inferida else decisao

    if no == flows.NO_PRAZO:
        prazo = _casar_prazo(clique)
        if prazo is not None:
            return Decisao(
                proximo_no=flows.NO_ENCERRADO,
                mensagem=Mensagem(
                    corpo=flows.render(flows.MSG_PRAZO_FECHAMENTO,
                                       {"prazo": prazo.rotulo_humano}),
                ),
                efeitos=Efeitos(tags=(prazo.tag,), recontato_dias=prazo.dias),
            )
        botao = _casar_nivel1(clique)
        if botao is not None:
            # Clique do nível 1 chegando no nível 2: o lead rolou a conversa e tocou
            # no template de novo. Em geral ignorar é o certo — não é recusa a usar
            # botões e reprocessar duplicaria efeito de CRM.
            #
            # Menos quando ele MUDA DE IDEIA PARA CIMA. "Ainda tenho estoque" seguido
            # de "Preciso repor" é o lead conferindo o estoque e voltando: engolir
            # isso perde a única intenção de compra explícita que o fluxo consegue
            # capturar — o clique positivo converteu 35,7% em venda, o melhor sinal do
            # CRM inteiro. (O opt-out já foi tratado antes, no topo de decidir.)
            if botao.id == flows.ID_REPOR:
                return _decidir_quente(contexto, canal_do_vendedor=canal_do_vendedor)
            return Decisao(proximo_no=no, ignorar=True)
        return None

    return None


def _efeito_nivel1(
    botao: Botao, trilha: str, *, canal_do_vendedor: bool, contexto: Contexto,
) -> Decisao | None:
    if botao.id == flows.ID_REPOR:
        return _decidir_quente(contexto, canal_do_vendedor=canal_do_vendedor)
    if botao.id == flows.ID_ADIAR:
        return _decidir_adiar()
    if botao.id == flows.ID_OPTOUT:
        return _decidir_optout()
    if botao.id == flows.ID_MANTER:
        # Trilha C não vende: "Manter cadastro" é opt-in prospectivo registrado, e a
        # abordagem comercial fica para uma SEGUNDA campanha, com consentimento na
        # mão. Encerrar aqui é o desfecho correto, não um beco.
        return Decisao(
            proximo_no=flows.NO_ENCERRADO,
            mensagem=Mensagem(
                corpo=flows.render(flows.MSG_CADASTRO_MANTIDO,
                                   {"vocativo": _vocativo(contexto.primeiro_nome)}),
            ),
            efeitos=Efeitos(tags=(flows.TAG_CADASTRO_MANTIDO,)),
        )
    if botao.id == flows.ID_ATUALIZAR:
        return Decisao(
            proximo_no=flows.NO_ENCERRADO,
            mensagem=Mensagem(corpo=flows.MSG_ATUALIZAR_DADOS),
            efeitos=Efeitos(tags=(flows.TAG_HUMANO,), handoff=True),
        )
    # Nó ou botão sem tratamento: inerte, nunca destrutivo.
    return Decisao(proximo_no=flows.NO_INTERESSE, ignorar=True)


def _decidir_classe(
    no: str, trilha: str, classe: str, *, canal_do_vendedor: bool, contexto: Contexto,
) -> Decisao | None:
    """Traduz uma classe da camada 2 no MESMO efeito que o botão equivalente.

    Nenhuma classe gera texto novo: toda mensagem continua vindo de flows.py.
    """
    if classe == CLASSE_SAIR:
        # Vale em qualquer nó, inclusive no de prazo: quem pede para parar, para.
        # Hoje há 52 pessoas em produção que clicaram opt-out e seguem elegíveis —
        # é essa dívida que esta linha existe para não repetir.
        return _decidir_optout()
    if classe == CLASSE_ENGANO:
        return Decisao(
            proximo_no=flows.NO_ENCERRADO,
            mensagem=Mensagem(corpo=flows.MSG_ENGANO, botoes=(flows.BTN_OPTOUT,)),
            efeitos=Efeitos(tags=(flows.TAG_ENGANO,), silenciar_ia=True,
                            pretexto_contestado=True),
        )
    if classe == CLASSE_QUENTE:
        return _decidir_quente(contexto, canal_do_vendedor=canal_do_vendedor)
    if classe == CLASSE_ADIAR:
        # No nó de prazo o lead já está sendo perguntado — repetir a pergunta seria
        # loop. Cai no nudge normal, que já é a pergunta de prazo.
        return None if no == flows.NO_PRAZO else _decidir_adiar()
    if classe == CLASSE_PERGUNTA:
        # Pergunta comercial de verdade: o bot não responde preço nem frete (há três
        # versões incompatíveis de política de frete em circulação). Vai para o João.
        return _ENTREGAR_AO_HUMANO
    # RUIDO e qualquer classe desconhecida caem na regra de nudge do chamador.
    return None
