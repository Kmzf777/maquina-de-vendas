"""Motor do fluxo de botões da ValerIA. Núcleo puro: sem banco, sem rede, sem relógio.

Intérprete do registry, não matriz de `if`: como valeria_registry.py declara os
destinos, decidir() só precisa achar o nó, casar o clique com um botão e devolver o
destino declarado. É por isso que este arquivo é curto.

Reusa os eventos e a saída de button_flow/engine.py de propósito — o runner já sabe
aplicar `Decisao`. NÃO estende `engine.decidir()`, que tem a matriz da recuperação
embutida (NO_INTERESSE, NO_PRAZO, trilhas) e ficaria ilegível servindo dois fluxos.

E reusa também o DESFECHO do irmão: chegar a um terminal ENCERRA o fluxo, e os
eventos seguintes voltam como `Decisao(ignorar=True)` — o mesmo campo que
`engine.decidir` devolve no nó `flows.NO_ENCERRADO`, e que o runner já trata sem
enviar, sem aplicar efeito e sem gravar estado. A diferença de forma é que ali o
encerramento tem um nó PRÓPRIO e aqui o próprio terminal é o nó; a guarda está em
`_encerrado`, e o único terminal que não encerra é `T_ADIAR` (ver o docstring dela).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.button_flow.engine import (
    Clique, Decisao as DecisaoBase, Efeitos, Mensagem, Texto, normalizar,
)
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

# A folha de prazos (os 30/60/90 do adiamento) é declarada em
# `reg.BOTOES_PRAZO`, junto com `reg.DIAS_POR_PRAZO`, e NÃO aqui: botão é
# estrutura, e este arquivo interpreta estrutura em vez de declará-la. Ela ficou
# no motor até 29/09/2026 e era a única aresta do fluxo invisível para quem lesse
# só o registry.

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
      2. opt-out por texto vence o contador de nudges E o encerramento;
      3. fluxo já encerrado devolve `ignorar` — turno nenhum acontece;
      4. clique casado com botão declarado vai para o destino declarado;
      5. o resto é nudge até o teto, e depois humano.
    """
    est = estado if isinstance(estado, dict) else {}

    botoes = _botoes_declarados(no_atual, nos, terminais)
    if botoes is None:
        return _ir_para(ID_HUMANO, nos, terminais)

    # Antes do contador e sem gastar nudge: quem pede para sair, sai. É a dívida
    # medida no outro fluxo (52 pessoas clicaram opt-out e seguiram elegíveis).
    #
    # E ACIMA da guarda de encerramento, que é a decisão de ordem deste arquivo: a
    # Meta EXIGE honrar o pedido de parar, então ele vale depois do handoff, depois
    # do adiamento e depois do bloqueio. Silenciar um "pare" para economizar uma
    # mensagem é o pior desfecho disponível — é o mesmo raciocínio que
    # `engine.decidir` escreve no topo dela ("o opt-out vence TUDO").
    #
    # A ÚNICA exceção é quem JÁ está em `T_OPTOUT`, e ela é aritmética, não
    # preferência: o nó só vira `T_OPTOUT` depois de `effects.aplicar` devolver True
    # (o runner aborta o turno e NÃO avança o estado quando a gravação do `opt_out`
    # falha), então estar nele é prova de que o pedido está registrado. Reaplicá-lo
    # não honra nada que já não esteja honrado e reenvia a confirmação — mandar "não
    # te mando mais mensagem por aqui" de novo, faturada, para quem acabou de pedir
    # silêncio é o oposto do pedido.
    if (isinstance(evento, Texto) and no_atual != ID_OPTOUT
            and normalizar(evento.conteudo) in FRASES_OPTOUT):
        return _ir_para(ID_OPTOUT, nos, terminais)

    # O FLUXO ACABOU. Terminal que não oferece botão é desfecho, não posição de
    # espera: o evento seguinte não gera mensagem, tag, observação, nota, mensagem de
    # sistema nem movimento de nó. Mesmo desenho do irmão, que move o estado para
    # `flows.NO_ENCERRADO` e devolve `ignorar` dali em diante — aqui o nó de destino
    # JÁ é o terminal (o runner grava `flow_state.node = "T_HUMANO"`), então o que
    # faltava era só esta leitura.
    #
    # Sem ela, `botoes` vazio deixava a guarda do nudge falsa e o turno caía na
    # última linha, `_ir_para(ID_HUMANO)`: `T_HUMANO` REAPLICADO a cada mensagem
    # seguinte, para sempre — tag regravada, observação de CRM e mensagem de sistema
    # novas em cada rodada. O carimbo de `human_control` de 30/09 corta isso só para
    # os três terminais de handoff (via `runner._motivo_para_nao_rodar`), e de
    # propósito: quem chega a `T_HUMANO` sem transbordo formal não é carimbado,
    # porque não foi entregue a ninguém.
    if _encerrado(no_atual, nos, terminais):
        return Decisao(proximo_no=no_atual, ignorar=True)

    if isinstance(evento, Clique):
        botao = _casar(no_atual, evento, botoes, est)
        if botao is not None:
            return _ir_para(
                botao.destino, nos, terminais,
                criterios=botao.grava,
                # Só um clique vindo da folha de prazos agenda recontato: comparar
                # com a tupla, e não olhar o id solto, impede que um botão de nó
                # com id homônimo agende um follow-up por acidente.
                dias=(reg.DIAS_POR_PRAZO.get(botao.id)
                      if botao in reg.BOTOES_PRAZO else None),
            )
        # Clique que não casou é tratado como texto livre: reoferece. Um id
        # desconhecido é tela antiga ou toque duplo, não recusa a usar botões.

    if botoes and _nudges(est) < reg.TETO_NUDGES:
        return _nudge(no_atual, botoes, corpo_nudge or reg.CORPO_NUDGE)

    # Teto estourado, ou nó sem botão para reoferecer (override de tela que esvaziou
    # um nó — terminal encerrado já saiu acima, por `_encerrado`). Note que isto NÃO é
    # blacklist: quem insiste em digitar é quem quer falar, e descartá-lo é a perda
    # que a auditoria do funil mediu.
    return _ir_para(ID_HUMANO, nos, terminais)


def _encerrado(
    no_atual: str, nos: dict[str, reg.No], terminais: dict[str, reg.Terminal],
) -> bool:
    """True quando o fluxo já chegou a um desfecho de onde não se clica.

    Lê a DECLARAÇÃO (`Terminal.prazos`), nunca a tupla de botões estar vazia, e a
    diferença é o defeito original invertido: `T_ADIAR` é terminal E posição de onde
    se clica — ele PERGUNTA o prazo e espera o toque, então chegar nele não é o fim
    (clicar um prazo, que leva a `T_ADIADO`, é). Já um NÓ que um override de tela
    esvaziou tem tupla vazia e NÃO está encerrado: é nó quebrado, e o desfecho seguro
    desse caso continua sendo entregar ao humano, não silenciar o lead.

    Nó VENCE terminal na mesma chave, exatamente como em `_botoes_declarados`: as duas
    funções leem a mesma posição e uma precedência diferente entre elas faria a mesma
    string ser nó para uma e desfecho para a outra — a classe de divergência que
    `campaigns/node_registry.py` documenta. Hoje os dois dicionários são disjuntos
    (`N*`/`P*`/`C*`/`E*` contra `T_*`) e nada garante isso por teste.

    Terminal novo entra encerrando por default, que é o lado certo para errar: um
    desfecho que esquece de encerrar volta a reprocessar cada mensagem do lead.
    """
    if no_atual in nos:
        return False
    terminal = terminais.get(no_atual)
    return terminal is not None and not terminal.prazos


def _botoes_declarados(
    no_atual: str, nos: dict[str, reg.No], terminais: dict[str, reg.Terminal],
) -> tuple[reg.Botao, ...] | None:
    """Botões que o lead tem na mão, ou None se o nó não existe.

    Terminal também é posição válida: `T_ADIAR` é destino E nó de onde se clica
    (os 30/60/90). Os outros terminais devolvem tupla vazia — posição conhecida,
    nada para tocar — e quem trata isso é `_encerrado`, ACIMA do casamento de
    clique: a tupla vazia é sintoma do desfecho, não o critério dele.
    """
    no = nos.get(no_atual)
    if no is not None:
        return no.botoes
    terminal = terminais.get(no_atual)
    if terminal is None:
        return None
    return reg.BOTOES_PRAZO if terminal.prazos else ()


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
    texto envelhece em silêncio. Vale igual para o `{prazo}` do `T_ADIADO`, que o
    runner resolve com o `rotulo_humano` do prazo clicado. A `foto` também fica no
    registry — o runner lê `nos[proximo_no].foto`, já que `Mensagem` (da
    recuperação) não tem esse campo.
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
            botoes=reg.BOTOES_PRAZO if terminal.prazos else (),
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
            # O `vendedor` declarado no terminal é a ÚNICA fonte de quem recebe o
            # lead. Sem esta linha ele morria no registry: `effects._aplicar_handoff`
            # carimbava o vendedor padrão (o João) e os handoffs de exportação
            # apareciam no KPI e no `metadata.handoff` como se fossem dele — 100%
            # deles, porque o ramo E nunca entrega a mais ninguém.
            vendedor=terminal.vendedor,
        ),
        criterios=dict(criterios),
    )
