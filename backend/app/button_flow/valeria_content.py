"""Camada de conteúdo editável do fluxo de botões da ValerIA. A tela edita, o
registry manda.

`valeria_registry.py` declara ESTRUTURA (quais nós existem, quantos botões,
para onde cada um vai, o que cada um grava no score) — isso é código, e não
muda por aqui. Este módulo é a fresta pela qual a tela de /campanhas edita só
o que é TEXTO: `corpo` e `rotulos`. Nada mais tem caminho de escrita: `aplicar`
lê só essas duas chaves de cada override, então um payload com `destino` ou
`grava` simplesmente não tem onde pousar — não é filtrado, é ignorado por
construção.

Três garantias, na ordem em que a spec as pede:
  1. A tabela `valeria_flow_content` é OVERRIDE, nunca fonte. Linha ausente =
     default do registry. `carregar` é fail-open (devolve `{}` em qualquer
     erro) porque migration pendente é modo de falha recorrente neste repo, e
     aqui ele emudeceria a ValerIA — mesmo raciocínio de
     `follow_up/service.py` ao ler `followup_joao_ajustes`.
  2. `aplicar` é pura e nunca muta `reg.NOS`: os dataclasses são frozen, mas o
     dict que os contém não é, então a defesa é devolver um dict NOVO.
  3. `validar` é o portão de gravação: um rótulo acima do limite da Meta faz o
     ENVIO falhar, não a leitura, então sem essa checagem no save a ValerIA só
     fica muda depois que o operador já achou que salvou.

── Terminais entram na mesma fresta, não numa nova ──────────────────────────
`reg.TERMINAIS` (8 desfechos — handoffs, adiamento, humano, fim, opt-out) tinha
`corpo` gravado só no código: a tela editava os 17 `NOS` e o nudge, mas nenhum
dos 8 terminais — inclusive o handoff, que a auditoria de 08/07 chama de
"momento mais frágil" da conversa. `carregar` já lê qualquer `node_id`
presente na tabela sem distinguir namespace, então terminal usa a MESMA linha
que nó — só o `aplicar` correspondente muda, porque `Terminal` não tem
`botoes`: é `aplicar_terminais`, não uma chave nova em `aplicar`.

── A terceira leitura: `historico_de_rotulos` ───────────────────────────────
`aplicar` e `aplicar_terminais` respondem "qual texto o lead VÊ". Falta a
pergunta oposta, e ela vale uma mensagem faturada: "o lead tocou num rótulo que
JÁ SAIU DO AR — que botão era?". Quem responde é `valeria_engine._casar`, lendo
`{node_id: {rotulo: botao_id}}`; quem guarda é a coluna
`valeria_flow_content.rotulos_antigos`, na forma `[{botao_id, rotulo, em}]`. O
meio — a conversão de uma forma na outra — é `historico_de_rotulos`, e ele mora
aqui porque este módulo é o dono da forma da tabela. Sem ele a rede de segurança
ficava GRAVADA e nunca LIDA: o clique de quem recebeu a tela antiga não casava
com botão nenhum e caía no nudge.

Blindagem herdada, e reforçada: terminal carrega EFEITO (`vendedor`, `tags`,
`handoff`, `optout`, `silenciar_ia`, `prazos`) que `Botao.grava` nem sonha em
ter — errar aqui não rebaixa um score, troca de vendedor ou desliga um
opt-out. `aplicar_terminais` só lê `corpo` do override, do mesmo jeito que
`aplicar` só lê `corpo`/`rotulos`: as outras chaves não são filtradas, são
ignoradas por não existir linha que as leia.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from app.button_flow import valeria_registry as reg
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_TABLE = "valeria_flow_content"


def carregar(flow_id: str) -> dict:
    """Lê os overrides de `flow_id`. I/O; fail-open.

    Devolve `{node_id: {"corpo": str|None, "rotulos": dict, "rotulos_antigos": list}}`.
    Qualquer falha (migration não aplicada, PostgREST fora do ar, tabela vazia)
    devolve `{}` e só loga — nunca propaga. `{}` é exatamente o valor que faz
    `aplicar` devolver os defaults do registry, então "banco indisponível" e
    "banco vazio" produzem o mesmo comportamento observável.
    """
    try:
        linhas = (
            get_supabase()
            .table(_TABLE)
            .select("node_id, corpo, rotulos, rotulos_antigos")
            .eq("flow_id", flow_id)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.warning(
            "[VALERIA_CONTENT] overrides de %r não lidos (migration 20260929 "
            "aplicada?) — seguindo com os defaults do registry: %s", flow_id, exc,
        )
        return {}

    overrides: dict = {}
    for linha in linhas:
        node_id = linha.get("node_id")
        if not node_id:
            continue
        overrides[node_id] = {
            "corpo": linha.get("corpo"),
            "rotulos": linha.get("rotulos") or {},
            "rotulos_antigos": linha.get("rotulos_antigos") or [],
        }
    return overrides


def aplicar(nos: dict, overrides: dict) -> dict:
    """Funde `overrides` sobre `nos`. Pura — devolve um dict NOVO, nunca muta `nos`.

    Só duas chaves de cada override têm efeito: `corpo` (substitui o corpo do
    nó) e `rotulos` (mapa `botao_id -> rótulo`, aplicado botão a botão — id
    ausente no override mantém o rótulo do registry). Qualquer outra chave
    (`destino`, `grava`, o que for) é lida por ninguém: não existe linha de
    código aqui que a leia, e é isso, não um filtro, que impede a tela de
    reescrever estrutura.

    Nó desconhecido no override é ignorado: a tela pode ter lixo de um nó que
    já não existe mais no registry (renomeado, removido) e isso não pode
    quebrar o fluxo dos nós que existem.
    """
    resultado = dict(nos)
    for node_id, override in overrides.items():
        no = resultado.get(node_id)
        if no is None:
            continue

        mudancas: dict = {}

        corpo = override.get("corpo")
        if corpo:
            mudancas["corpo"] = corpo

        rotulos = override.get("rotulos") or {}
        if rotulos:
            mudancas["botoes"] = tuple(
                replace(botao, rotulo=rotulos[botao.id]) if botao.id in rotulos else botao
                for botao in no.botoes
            )

        if mudancas:
            resultado[node_id] = replace(no, **mudancas)

    return resultado


def aplicar_terminais(terminais: dict, overrides: dict) -> dict:
    """Funde `overrides` sobre `terminais`. Pura — devolve um dict NOVO, nunca
    muta `terminais`. Mesma forma de `aplicar`, adaptada ao formato de
    `Terminal`.

    Só `corpo` tem efeito. Um `Terminal` não declara `botoes` (a folha do
    `T_ADIAR` é `reg.BOTOES_PRAZO`, declarada à parte no registry, e não
    pertence a nenhum terminal individual) — então não existe segunda chave a
    ler aqui como `rotulos` em `aplicar`. E os campos de EFEITO (`vendedor`,
    `tags`, `handoff`, `optout`, `silenciar_ia`, `prazos`) não são lidos do
    override por nenhuma linha deste corpo de função: não é filtro, é
    ausência de código que os leia — a mesma garantia estrutural que `aplicar`
    dá pra `destino`/`grava` nos nós.

    Terminal desconhecido no override é ignorado, mesmo motivo de `aplicar`:
    lixo de um id renomeado ou removido não pode derrubar os que existem.

    Override com `corpo` vazio/ausente não aplica nada — `if corpo:` trata os
    dois casos igual, o que é seguro aqui porque "não aplicar" e "aplicar
    branco" só coincidem observavelmente quando o DEFAULT do terminal já é
    branco (`T_HUMANO`, `T_FIM`); nos outros seis, `validar` nunca deixa um
    override branco chegar a esta função pela tela — ver o comentário de
    `validar` sobre a regra do corpo em branco.
    """
    resultado = dict(terminais)
    for terminal_id, override in overrides.items():
        terminal = resultado.get(terminal_id)
        if terminal is None:
            continue

        corpo = override.get("corpo")
        if corpo:
            resultado[terminal_id] = replace(terminal, corpo=corpo)

    return resultado


def historico_de_rotulos(overrides: dict) -> dict:
    """Converte os `rotulos_antigos` dos overrides no mapa que o MOTOR indexa. Pura.

    Da forma da COLUNA — `[{botao_id, rotulo, em}]` por linha — para a forma de
    `valeria_engine._casar`: `{node_id: {rotulo: botao_id}}`. As duas formas são
    diferentes de propósito e nenhuma muda:

      • a coluna é LISTA porque é assim que ela acumula (`_versionar` appenda, nunca
        sobrescreve), porque a lista casa com o default `'[]'::jsonb` da migration
        20260929 e porque ela sobrevive a dois botões que um dia compartilhem
        rótulo — um dict não sobreviveria;
      • o mapa é a estrutura de BUSCA: `_casar` recebe um rótulo e precisa do id do
        botão, então a chave tem de ser o rótulo.

    Sem esta conversão, `_casar` não encontra nada (`estado.get("rotulos_antigos")`
    volta None), o lead que recebeu a tela ANTIGA e tocou nela cai no nudge e a
    edição de um rótulo na tela passa a custar uma mensagem faturada por lead —
    exatamente o acidente que a coluna existe para impedir.

    Rótulo REPETIDO fica com a entrada MAIS RECENTE: `_versionar` appenda, então a
    última da lista descreve a tela mais parecida com a que o lead tem na mão.

    Não exige `corpo` nem `rotulos` na linha, e isso é contrato: a linha que
    `DELETE /api/valeria-flow/{node_id}` deixa para trás tem os dois NULOS e o
    histórico intacto — é o instante em que o rótulo editado acaba de sair do ar e
    em que o histórico mais importa.

    Nó sem histórico NÃO entra no mapa (em vez de entrar com `{}`): manter a
    diferença observável entre "não há histórico" e "há histórico vazio" é o que
    deixa o runner não tocar no `flow_state` de quem nunca teve rótulo editado.

    Tolera qualquer forma: `jsonb` aceita escalar, array e tipo errado em qualquer
    campo, e este valor chega do banco sem esquema. Uma entrada torta é descartada
    sozinha, sem levar as boas — nada no caminho do inbound pode estourar por isso.
    """
    if not isinstance(overrides, dict):
        return {}
    mapa: dict[str, dict[str, str]] = {}
    for node_id, override in overrides.items():
        if not isinstance(node_id, str) or not isinstance(override, dict):
            continue
        entradas = override.get("rotulos_antigos")
        if not isinstance(entradas, list):
            continue
        por_rotulo: dict[str, str] = {}
        for entrada in entradas:
            if not isinstance(entrada, dict):
                continue
            rotulo = entrada.get("rotulo")
            botao_id = entrada.get("botao_id")
            if not isinstance(rotulo, str) or not rotulo.strip():
                continue
            if not isinstance(botao_id, str) or not botao_id:
                continue
            por_rotulo[rotulo] = botao_id
        if por_rotulo:
            mapa[node_id] = por_rotulo
    return mapa


def _limite_de_rotulo(no: reg.No) -> int:
    return reg.LIMITE_TITULO_LISTA if no.tela == "lista" else reg.LIMITE_ROTULO_BOTAO


def validar(node_id: str, payload: dict) -> str | None:
    """Valida um override antes de gravar. Devolve a mensagem de erro (PT-BR,
    pra tela mostrar ao operador) ou `None` quando o payload pode ser salvo.

    Este é o portão que `carregar`/`aplicar`/`aplicar_terminais` não têm como
    ter: eles só LEEM o que já está gravado, e uma linha inválida ali dentro
    simplesmente não seria aplicada (rótulo não bate com nenhum `botao.id`)
    ou, pior, seria aplicada e a Meta recusaria o envio — a ValerIA fica muda
    naquele nó até alguém notar. Chamar isto ANTES do INSERT/UPDATE é o que
    fecha o buraco.

    Regra do corpo em branco, que MUDA entre nó e terminal:
      • Nó: branco é sempre rejeitado. Um nó sem corpo é uma tela da Meta sem
        texto — não existe leitura em que isso seja intencional.
      • Terminal: branco só é aceito onde o próprio registry já declara
        `corpo=""` por CONTRATO — `T_HUMANO` e `T_FIM`, onde vazio significa
        "não gasta mensagem" (valeria_registry.py). Nos outros seis
        (handoffs, `T_ADIAR`, `T_ADIADO`, `T_OPTOUT`) o default não é vazio, e
        aceitar um override vazio ali deixaria o motor em silêncio bem no
        turno em que o lead acabou de pedir pra ser encaminhado — o mesmo
        "momento mais frágil" que a auditoria 08/07 mediu para o handoff. Por
        isso a pergunta não é "este payload está em branco?", é "o DEFAULT
        deste terminal já era em branco?".
    """
    if node_id == reg.CHAVE_NUDGE:
        corpo = payload.get("corpo")
        if corpo is not None and not corpo.strip():
            return "o corpo do nudge não pode ficar vazio"
        return None

    if node_id == reg.CHAVE_ROTULO_LISTA:
        # A segunda chave reservada (ver `reg.CHAVE_ROTULO_LISTA`): o rótulo do
        # botão que abre a folha de opções. Guardado em `corpo` e não em `rotulos`
        # porque `rotulos` é um mapa `botao_id -> texto` e este botão não é de nó
        # nenhum — não tem id para ser chave.
        #
        # É o único override com LIMITE DE TAMANHO fora dos nós, e o limite é o que
        # torna a validação obrigatória aqui: 20 caracteres é teto da Meta, e um
        # rótulo acima dele faz a Meta RECUSAR a mensagem inteira — a ValerIA fica
        # muda em N0 e E1, as duas telas de lista, depois de o operador achar que
        # salvou. Branco tem o mesmo efeito (folha sem botão de abrir).
        rotulo = payload.get("corpo")
        if rotulo is not None:
            if not rotulo.strip():
                return "o rótulo do botão de lista não pode ficar vazio"
            if len(rotulo) > reg.LIMITE_ROTULO_BOTAO:
                return (
                    f"o rótulo do botão de lista tem {len(rotulo)} caracteres, "
                    f"o limite é {reg.LIMITE_ROTULO_BOTAO}"
                )
        return None

    no = reg.NOS.get(node_id)
    if no is not None:
        corpo = payload.get("corpo")
        if corpo is not None and not corpo.strip():
            return "o corpo não pode ficar vazio"

        rotulos = payload.get("rotulos") or {}
        if rotulos:
            ids_validos = {botao.id for botao in no.botoes}
            limite = _limite_de_rotulo(no)
            for botao_id, rotulo in rotulos.items():
                if botao_id not in ids_validos:
                    return f"botão {botao_id!r} não existe no nó {node_id!r}"
                if len(rotulo) > limite:
                    return (
                        f"rótulo de {botao_id!r} tem {len(rotulo)} caracteres, "
                        f"o limite é {limite}"
                    )

        return None

    terminal = reg.TERMINAIS.get(node_id)
    if terminal is not None:
        # Terminal não declara `botoes` — nem `T_ADIAR`, cuja folha 30/60/90 é
        # `reg.BOTOES_PRAZO`, uma tabela à parte no registry, não um campo do
        # terminal. Um `rotulos` aqui não tem `botao.id` nenhum pra casar, e
        # silenciar isso (como `aplicar_terminais` silencia chaves de efeito)
        # deixaria a tela achando que salvou um rótulo que nunca é lido —
        # override morto e invisível, o problema que o enunciado pede pra
        # evitar. Por isso REJEITA, não ignora.
        if payload.get("rotulos"):
            return f"terminal {node_id!r} não tem botões próprios — rótulo não pode ser editado aqui"

        corpo = payload.get("corpo")
        if corpo is not None and not corpo.strip() and terminal.corpo != "":
            return "o corpo não pode ficar vazio"

        return None

    return f"nó {node_id!r} não existe no registry"
