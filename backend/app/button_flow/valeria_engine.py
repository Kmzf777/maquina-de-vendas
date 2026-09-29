"""Motor do fluxo de botões da ValerIA. Núcleo puro: sem banco, sem rede, sem relógio.

Intérprete do registry, não matriz de `if`: como valeria_registry.py declara os
destinos, decidir() só precisa achar o nó, casar o clique com um botão e devolver o
destino declarado. É por isso que este arquivo é curto.

Reusa os eventos e a saída de button_flow/engine.py de propósito — o runner já sabe
aplicar `Decisao`. NÃO estende `engine.decidir()`, que tem a matriz da recuperação
embutida (NO_INTERESSE, NO_PRAZO, trilhas) e ficaria ilegível servindo dois fluxos.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.button_flow.engine import (
    Clique, Decisao as DecisaoBase, Efeitos, Mensagem, Texto, normalizar,
)
from app.button_flow import flows
from app.button_flow import valeria_registry as reg


@dataclass(frozen=True)
class Decisao(DecisaoBase):
    """`Decisao` da recuperação + os critérios de score que o clique revelou.

    Campo novo aqui e não na base: a recuperação não tem score, e acrescentar
    campo na dataclass dela obrigaria a revisar todos os call sites daquele fluxo.
    """
    criterios: dict = field(default_factory=dict)


# Opt-out sem IA. Casamento por IGUALDADE normalizada, NUNCA substring: "não quero
# trocar de fornecedor" contém "não quero" e não é pedido de saída. A Meta exige
# honrar o pedido de parar, e sem modelo esta lista é o único jeito de detectá-lo.
FRASES_OPTOUT = frozenset(normalizar(f) for f in (
    "pare", "parar", "para", "sair", "me tira", "me tire", "remover",
    "descadastrar", "nao quero mais", "não quero mais", "cancelar",
    "para de mandar", "pare de mandar", "nao me manda mais",
))

# Os dois terminais que o MOTOR escolhe sozinho — nenhum botão aponta para eles.
ID_HUMANO = "T_HUMANO"
ID_OPTOUT = "T_OPTOUT"

# Os três prazos do adiamento vêm de `flows.PRAZOS`, não são redeclarados: os
# 30/60/90 estão calibrados no intervalo real entre compras desta base (78-122
# dias) e a recuperação já é dona deles. Aqui só ganham a forma de `reg.Botao`
# para que TODO botão que sai deste fluxo tenha o mesmo tipo — o runner da
# ValerIA renderiza `id`+`rotulo` e não precisa saber de dois formatos.
#
# `destino="T_FIM"` porque escolher prazo encerra sem descartar: a tag de
# adiamento já foi aplicada na chegada ao T_ADIAR, e T_FIM tem corpo vazio (não
# gasta mensagem faturada). A TAG de `flows.Prazo` NÃO é reusada — ela diz
# "Recuperação: 30 dias", que é o desfecho do outro fluxo.
BOTOES_PRAZO: tuple[reg.Botao, ...] = tuple(
    reg.Botao(id=p.id, rotulo=p.titulo, destino="T_FIM") for p in flows.PRAZOS
)
_DIAS_POR_PRAZO: dict[str, int] = {p.id: p.dias for p in flows.PRAZOS}

# Último recurso quando o próprio `terminais` não traz o T_HUMANO (dicionário
# montado a partir de override de tela). Entregar ao humano tem de funcionar
# mesmo com o registry incompleto — é o desfecho seguro de todo caminho de erro.
_HUMANO_SEM_REGISTRY = Decisao(
    proximo_no=ID_HUMANO,
    efeitos=Efeitos(tags=(reg.TAG_HUMANO,), silenciar_ia=True),
)


def decidir(
    no_atual: str,
    evento: object,
    estado: dict | None,
    nos: dict[str, reg.No],
    terminais: dict[str, reg.Terminal],
    *,
    corpo_nudge: str | None = None,
) -> Decisao:
    """Próximo passo do fluxo. Pura: mesma entrada, mesma saída, sempre.

    `nos` e `terminais` entram como parâmetro (e não são lidos do módulo) porque o
    runner passa as cópias já com os overrides de `valeria_flow_content` aplicados
    — o motor interpreta a estrutura, a tela é dona do texto. `corpo_nudge` é o
    override da chave reservada `reg.CHAVE_NUDGE`, que não é nó e por isso não
    chega dentro de `nos`.

    A ORDEM abaixo é o comportamento:
      1. nó desconhecido devolve ao humano (flow_state corrompido nunca estoura);
      2. opt-out por texto vence o contador de nudges;
      3. clique casado com botão declarado vai para o destino declarado;
      4. o resto é nudge até o teto, e depois humano.
    """
    est = estado if isinstance(estado, dict) else {}

    botoes = _botoes_declarados(no_atual, nos, terminais)
    if botoes is None:
        return _ir_para(ID_HUMANO, nos, terminais)

    # Antes do contador e sem gastar nudge: quem pede para sair, sai. É a dívida
    # medida no outro fluxo (52 pessoas clicaram opt-out e seguiram elegíveis).
    if isinstance(evento, Texto) and normalizar(evento.conteudo) in FRASES_OPTOUT:
        return _ir_para(ID_OPTOUT, nos, terminais)

    if isinstance(evento, Clique):
        botao = _casar(no_atual, evento, botoes, est)
        if botao is not None:
            return _ir_para(
                botao.destino, nos, terminais,
                criterios=botao.grava,
                # Só um clique vindo da folha de prazos agenda recontato: comparar
                # com a tupla, e não olhar o id solto, impede que um botão de nó
                # com id homônimo agende um follow-up por acidente.
                dias=_DIAS_POR_PRAZO.get(botao.id) if botao in BOTOES_PRAZO else None,
            )
        # Clique que não casou é tratado como texto livre: reoferece. Um id
        # desconhecido é tela antiga ou toque duplo, não recusa a usar botões.

    if botoes and _nudges(est) < reg.TETO_NUDGES:
        return _nudge(no_atual, botoes, corpo_nudge or reg.CORPO_NUDGE)

    # Sem botão para reoferecer (terminal que já encerrou) ou teto estourado. Note
    # que isto NÃO é blacklist: quem insiste em digitar é quem quer falar, e
    # descartá-lo é a perda que a auditoria do funil mediu.
    return _ir_para(ID_HUMANO, nos, terminais)


def _botoes_declarados(
    no_atual: str, nos: dict[str, reg.No], terminais: dict[str, reg.Terminal],
) -> tuple[reg.Botao, ...] | None:
    """Botões que o lead tem na mão, ou None se o nó não existe.

    Terminal também é posição válida: `T_ADIAR` é destino E nó de onde se clica
    (os 30/60/90). Os outros terminais devolvem tupla vazia — posição conhecida,
    nada para tocar — e é isso que manda o evento seguinte para o humano em vez
    de gastar uma mensagem reoferecendo botão que não existe.
    """
    no = nos.get(no_atual)
    if no is not None:
        return no.botoes
    terminal = terminais.get(no_atual)
    if terminal is None:
        return None
    return BOTOES_PRAZO if terminal.prazos else ()


def _casar(
    no_atual: str, clique: Clique, botoes: tuple[reg.Botao, ...], estado: dict,
) -> reg.Botao | None:
    """Botão deste nó que o clique representa, ou None.

    O `id` é o contrato: a mensagem interativa da Meta devolve o id no webhook
    (meta_parser.py grava em `payload`). `rotulos_antigos` é a rede de segurança
    para o lead que recebeu a tela ANTES de o operador editar o rótulo — nesse
    caso o histórico pode trazer o texto, e perder esse clique é perder um lead
    por causa de uma edição de copy.
    """
    por_id = {b.id: b for b in botoes}
    candidatos = [c for c in (clique.payload, clique.titulo) if c]
    for candidato in candidatos:
        achado = por_id.get(candidato)
        if achado is not None:
            return achado

    antigos = estado.get("rotulos_antigos")
    mapa = antigos.get(no_atual) if isinstance(antigos, dict) else None
    if not isinstance(mapa, dict):
        return None
    # Normalizado nas duas pontas: há 64 cliques gravados em produção como "Nao
    # tenho interesse" e ZERO em "Não tenho interesse" (nota de `normalizar`).
    por_rotulo = {normalizar(k): v for k, v in mapa.items()}
    for candidato in candidatos:
        botao_id = por_rotulo.get(normalizar(candidato))
        if botao_id in por_id:
            return por_id[botao_id]
    return None


def _nudges(estado: dict) -> int:
    """Nudges já gastos NO ATENDIMENTO, não no nó. Por nó, 17 nós dariam 51."""
    gastos = estado.get("nudges", 0)
    return gastos if isinstance(gastos, int) and not isinstance(gastos, bool) else 0


def _nudge(no_atual: str, botoes: tuple[reg.Botao, ...], corpo: str) -> Decisao:
    """Reenvia o MESMO nó: corpo de reoferecimento, botões idênticos aos dele."""
    return Decisao(
        proximo_no=no_atual,
        mensagem=Mensagem(corpo=corpo, botoes=botoes),
        marcar_nudge=True,
    )


def _ir_para(
    destino: str,
    nos: dict[str, reg.No],
    terminais: dict[str, reg.Terminal],
    *,
    criterios: tuple[tuple[str, object], ...] = (),
    dias: int | None = None,
) -> Decisao:
    """Monta a Decisao do destino DECLARADO. Nenhum texto nasce aqui.

    O corpo sai como está no registry, com `{preco}` e tudo: quem resolve o
    marcador contra `products` é o runner, no instante do envio, porque preço no
    texto envelhece em silêncio. A `foto` também fica no registry — o runner lê
    `nos[proximo_no].foto`, já que `Mensagem` (da recuperação) não tem esse campo.
    """
    no = nos.get(destino)
    if no is not None:
        return Decisao(
            proximo_no=destino,
            mensagem=Mensagem(corpo=no.corpo, botoes=no.botoes),
            criterios=dict(criterios),
        )

    terminal = terminais.get(destino)
    if terminal is None:
        return _HUMANO_SEM_REGISTRY

    # Corpo vazio é o contrato declarado de "não gasta mensagem faturada"
    # (T_HUMANO e T_FIM). Mensagem None é como o runner lê isso.
    mensagem = None
    if terminal.corpo:
        mensagem = Mensagem(
            corpo=terminal.corpo,
            botoes=BOTOES_PRAZO if terminal.prazos else (),
        )
    return Decisao(
        proximo_no=destino,
        mensagem=mensagem,
        efeitos=Efeitos(
            tags=terminal.tags,
            optout=terminal.optout,
            handoff=terminal.handoff,
            silenciar_ia=terminal.silenciar_ia,
            recontato_dias=dias,
        ),
        criterios=dict(criterios),
    )
