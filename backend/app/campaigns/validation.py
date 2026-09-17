"""Validacao de ativacao de uma campanha do builder (/campanhas) — FUNCAO PURA.

POR QUE ISTO EXISTE
───────────────────
Ativar uma campanha no builder valida UMA coisa hoje (`router.api_activate_campaign`):
o no de gatilho tem `next_node_id`. Tudo o mais passa. O builder nunca foi usado — 16
campanhas, 0 ativas, 0 matriculas na historia — entao nenhuma das armadilhas abaixo
chegou a machucar em producao. Quem carregava as guardas era a aba Esteiras
(`esteiras_router`, sete regras em prosa na docstring do modulo), e ela so sabia validar
as 4 esteiras do SEED: topologia fixa, tres toques e uma acao final. Este modulo
generaliza aquelas regras para topologia qualquer — que e o que o builder produz.

TODAS as falhas cobertas aqui sao SILENCIOSAS. Nenhuma levanta erro no motor, nenhuma
aparece no log: a campanha fica verde na tela e o lead nao recebe nada. E por isso que
a guarda tem de ser na ATIVACAO — depois, nao ha sintoma para investigar.

  • Template nao aprovado e a mais cara, e a razao de a camada existir. Template nao
    aprovado NAO impede a inscricao, so o ENVIO: a campanha inscreve o lead, nao manda
    nada e mesmo assim caminha ate a acao final — na reposicao isso marca o card como
    Perdido sem uma unica mensagem ter saido, ou seja, o sistema registra "nao teve
    resposta" para quem nunca foi contatado. Dado comercial destruido sem um erro.
    A mensagem diz NOME e STATUS de cada um porque a acao muda com o status: PENDING
    e esperar, REJECTED e corrigir e ressubmeter, e ausente da Meta e criar do zero —
    o estado inicial deste projeto, em que os templates `esteira_*` que o seed
    referencia nunca foram submetidos.
  • Condicao com um ramo nulo: `engine._execute_condition` faz
    `next_node_id = node["yes_node_id"] if result else node["no_node_id"]` e, com nulo,
    chama `_complete()`. Metade das matriculas morre no meio do fluxo, marcadas como
    concluidas.
  • No do meio sem saida: a FK de `next_node_id` e ON DELETE SET NULL. Apagar um no no
    canvas deixa o ANTECESSOR com a seta nula — a campanha continua "inteira" na tela e
    toda matricula que chega ali e encerrada calada. E a assinatura desse apagao.
  • Campo obrigatorio vazio: `stage_stagnation`/`no_sale_in_stage` fazem
    `if not stage: continue` (gatilho pulado inteiro, todo tick, sem log);
    `move_deal_stage` sem `stage_id` volta sem tocar o card; `send` sem
    `template_name` levanta KeyError e a matricula entra em retry.
  • Valor fora do vocabulario: operador desconhecido faz `_compare` devolver False em
    TODA comparacao; `last_speaker` fora de (qualquer|lead|nos) faz a RPC devolver
    conjunto vazio para sempre; rotulo de coluna no lugar de `leads.stage` nunca casa.
  • Sem canal caem DUAS protecoes: `_conversation_followup_disabled(lead, None)`
    devolve False sem consultar nada (a flag "Finalizar Conversa" do vendedor passa a
    ser ignorada) e `_execute_send_node` cai em `get_channel_for_lead`, que devolve o
    canal da conversa ATIVA MAIS RECENTE — um template assinado "Aqui e o Joao" pode
    sair do numero da ValerIA.

CONTRATO
────────
`validar` e PURA: nao faz I/O e nao importa o motor. Quem busca campanha, nos e
templates e o chamador (a rota de ativacao). E o que torna a suite possivel sem banco —
e o que impede esta camada de virar mais um lugar onde o builder e o motor divergem,
porque as regras de CAMPO saem inteiras do `node_registry`, a mesma fonte que a tela
consome.

`templates` e um MAPA nome → status CRU da Meta ({'joao_t1': 'APPROVED', 'joao_t3':
'PENDING'}), nao um conjunto de aprovados. O conjunto nao serve porque ele funde tres
situacoes que pedem tres acoes diferentes do operador: PENDING e esperar, REJECTED e
corrigir e ressubmeter, e ausente do mapa e criar o template. O status vai CRU de
proposito e a comparacao e normalizada (`.lower() == 'approved'`), porque o sync local
grava minusculo e o payload da Meta vem 'APPROVED' — mesmo criterio do
`esteiras_router._STATUS_APROVADO` e do `templates/preflight._normalize_variants`.

FAIL-OPEN, UM UNICO: `templates=None` significa "nao deu para consultar
`message_templates`" e pula SO a regra 12 — mesmo criterio do
`esteiras_router._nao_aprovados`, pelo mesmo motivo (a tela ja filtra o select por
aprovados, e travar a ativacao inteira por um timeout do Supabase e pior do que o risco
que a guarda cobre). Um mapa VAZIO nao e a mesma coisa que None: vazio quer dizer "a
Meta nao tem nenhum desses templates" e reprova. Todas as demais regras continuam
valendo: oscilacao de banco nao e anistia para grafo quebrado.

AS MENSAGENS SAO PARA O OPERADOR, nao para o dev. "O toque 3 usa o template
`joao_conversa_atacado_t3`, que nao esta aprovado na Meta" e acionavel;
"template_nao_aprovado" nao e. O `codigo` existe para a tela agrupar/estilizar e o
`no_id` para ela destacar o no no canvas — o texto e o que a pessoa le.
"""
from __future__ import annotations

import uuid as _uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

from app.campaigns.node_registry import REGISTRO, VALORES_FIXOS, Campo, TipoDeNo

# Onde mora o subtipo de cada tipo de no. E o mesmo formato que o seed grava e que o
# motor le (`cfg.get("trigger_type")`, `cfg.get("action_type")`, ...).
_SUBTIPO_POR_TIPO = {
    "trigger": "trigger_type",
    "action": "action_type",
    "condition": "condition_type",
}

# Vocabularios cujo valor e um uuid de linha do banco. `usuario_id`/`lista_usuario_id`
# tambem sao uuid na pratica e NAO estao aqui de proposito: a tela escolhe o vendedor
# numa lista (nao ha digitacao a errar) e um id de usuario que nao existe mais nao
# quebra a campanha — `assign_to` so nao acha alvo. Se um dia virar problema medido,
# basta acrescentar o vocabulario nesta tupla.
_VOCAB_DE_ID = ("etapa_id", "funil_id", "canal_id")

_TIPOS_DE_ENVIO = ("send", "send_text")

# `message_templates.status`: o sync local grava minusculo, o payload cru da Meta vem
# 'APPROVED'. Comparamos normalizado, como `esteiras_router` e `templates/preflight`.
_STATUS_APROVADO = "approved"

# O que o operador tem de FAZER, por status. A acao muda com o status — e por isso que
# a regra 12 recebe um mapa de status e nao um conjunto de aprovados.
_ACAO_POR_STATUS = {
    "pending": "Espere a aprovação da Meta e ative a campanha depois.",
    "rejected": "A Meta recusou este template: corrija o texto e submeta de novo — "
                "enquanto estiver nesse estado ele nunca vai enviar.",
    "paused": "A Meta pausou este template por qualidade: só volta a enviar depois de "
              "sair da pausa.",
    "disabled": "A Meta desabilitou este template: ele não volta — crie outro e "
                "submeta.",
}
_ACAO_GENERICA = ("Só template com status APPROVED envia: resolva a pendência na Meta "
                  "e ative a campanha depois.")

# Explica a consequencia UMA vez, em todas as variantes da regra 12. E o que o dono
# precisa entender: o estrago nao e "nao enviou", e "registrou que nao teve resposta".
_ENVIO_MUDO = (
    "Template que não envia não impede a INSCRIÇÃO, só o envio: a campanha inscreve o "
    "lead, não manda nada e mesmo assim caminha até a ação final — registrando \"não "
    "teve resposta\" para quem nunca foi contatado."
)


@dataclass(frozen=True)
class Problema:
    """Um motivo para a campanha nao poder ser ativada.

    `no_id` e None quando o problema e da campanha inteira (nao ha gatilho, por
    exemplo) — a tela mostra esses no topo, sem no para destacar.
    """
    no_id: str | None
    codigo: str
    mensagem: str


# ─── Leitura do no ───────────────────────────────────────────────────────────────


def _id(no: dict) -> str:
    return str(no.get("id") or "")


def _tipo(no: dict) -> str:
    return str(no.get("type") or "").strip()


def _chave_do_registro(no: dict) -> tuple[str, str | None]:
    tipo = _tipo(no)
    chave_sub = _SUBTIPO_POR_TIPO.get(tipo)
    if not chave_sub:
        return (tipo, None)
    sub = (no.get("config") or {}).get(chave_sub)
    if tipo == "condition" and not sub:
        # `engine._execute_condition` faz cfg.get("condition_type", "replied_recently"):
        # condicao sem subtipo E uma replied_recently para o motor, e tem de ser
        # validada como tal.
        sub = "replied_recently"
    return (tipo, sub if sub else None)


def _do_registro(no: dict) -> TipoDeNo | None:
    return REGISTRO.get(_chave_do_registro(no))


def _rotulo(no: dict) -> str:
    tipo = _do_registro(no)
    return tipo.rotulo if tipo else (_tipo(no) or "no")


def _saidas(no: dict) -> list[str]:
    """As arestas que O MOTOR de fato percorre saindo deste no.

    Nao e "todo campo *_node_id preenchido": a semantica e a do `engine._process_one`.
    - `condition` sai SO por yes/no (um `next_node_id` gravado ali e ignorado pelo
      motor — segui-lo aqui marcaria como alcancavel um no que nunca executa);
    - `end` nao sai: `_execute_end` chama `_complete()` antes de olhar o `next`;
    - o resto sai por `next_node_id`.
    """
    tipo = _tipo(no)
    if tipo == "end":
        return []
    if tipo == "condition":
        return [str(x) for x in (no.get("yes_node_id"), no.get("no_node_id")) if x]
    return [str(no["next_node_id"])] if no.get("next_node_id") else []


def _vazio(valor: Any) -> bool:
    """Ausente para efeito de "campo obrigatorio".

    NAO e falsidade: `0` (janela de recompra de 0 dias) e `False` (nao pular fim de
    semana) sao valores legitimos e configurados de proposito. Um `if not valor` aqui
    reprovaria campanha correta — e a tela nao teria o que corrigir.
    """
    if valor is None:
        return True
    if isinstance(valor, str):
        return not valor.strip()
    if isinstance(valor, (list, tuple, set, dict)):
        return not valor
    return False


def _e_uuid(valor: Any) -> bool:
    if isinstance(valor, _uuid.UUID):
        return True
    if not isinstance(valor, str):
        return False
    try:
        _uuid.UUID(valor)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


# ─── Nomes que o operador reconhece ──────────────────────────────────────────────


def _ordens_de_envio(por_id: dict[str, dict], gatilho: dict | None) -> dict[str, int]:
    """{id do no de envio: numero do toque}, na ordem em que o fluxo os alcanca.

    "toque 2" e como o dono le a cadencia (e o vocabulario da aba Esteiras); "o no
    send de id 9f3a…" nao e. So numera no ALCANCAVEL: chamar de "toque 4" um no que o
    fluxo nunca atinge seria mentir dentro da propria mensagem de erro.
    """
    if gatilho is None:
        return {}
    ordens: dict[str, int] = {}
    for nid in _percorrer(por_id, _id(gatilho)):
        if _tipo(por_id[nid]) in _TIPOS_DE_ENVIO:
            ordens[nid] = len(ordens) + 1
    return ordens


def _percorrer(por_id: dict[str, dict], inicio: str) -> list[str]:
    """Ids alcancaveis a partir de `inicio`, em largura e em ordem determinista."""
    vistos: list[str] = []
    marcados = {inicio}
    fila = deque([inicio])
    while fila:
        atual = fila.popleft()
        if atual not in por_id:
            continue
        vistos.append(atual)
        for destino in _saidas(por_id[atual]):
            if destino in por_id and destino not in marcados:
                marcados.add(destino)
                fila.append(destino)
    return vistos


def _ident(no: dict, ordens: dict[str, int]) -> str:
    """Como a mensagem chama este no. Comeca frase, entao vem capitalizado."""
    nid = _id(no)
    if nid in ordens:
        return f'O toque {ordens[nid]} ("{_rotulo(no)}")'
    if _tipo(no) == "trigger":
        return f'O gatilho ("{_rotulo(no)}")'
    return f'O nó "{_rotulo(no)}" (id {nid[:8]})'


def _curto(no: dict, ordens: dict[str, int]) -> str:
    """Versao curta, para encadear varios nos numa frase so (o caminho do ciclo)."""
    nid = _id(no)
    if nid in ordens:
        return f"toque {ordens[nid]}"
    if _tipo(no) == "trigger":
        return "gatilho"
    return f'"{_rotulo(no)}"'


def _lista_de_campos(tipo: TipoDeNo, chaves: Iterable[str]) -> str:
    por_chave = {c.chave: c for c in tipo.campos}
    return ", ".join(
        f'"{por_chave[c].rotulo}" ({c})' if c in por_chave else f'"{c}"'
        for c in chaves
    )


# ─── Regras 1 a 4: os campos, direto do registro ─────────────────────────────────


def _problemas_de_campo(no: dict, ordens: dict[str, int]) -> list[Problema]:
    tipo = _do_registro(no)
    if tipo is None:
        # Tipo/subtipo que o registro nao conhece (campanha antiga, subtipo escrito a
        # mao no banco). Nao ha contrato para conferir os campos — as regras de GRAFO
        # continuam valendo sobre ele, que e o que impede um no desconhecido de virar
        # buraco no fluxo.
        return []

    cfg = no.get("config") or {}
    nid = _id(no)
    ident = _ident(no, ordens)
    fora: list[Problema] = []

    for campo in tipo.campos:
        valor = cfg.get(campo.chave)
        if _vazio(valor):
            if campo.obrigatorio:
                fora.append(Problema(
                    nid, "campo_obrigatorio",
                    f'{ident} está sem "{campo.rotulo}" ({campo.chave}), que é '
                    f"obrigatório para ativar a campanha.",
                ))
            continue
        fora.extend(_problemas_de_valor(no, campo, valor, ident))

    for grupo in tipo.requer_um_de:
        if all(_vazio(cfg.get(chave)) for chave in grupo):
            fora.append(Problema(
                nid, "requer_um_de",
                f"{ident} precisa de pelo menos um destes campos preenchidos: "
                f"{_lista_de_campos(tipo, grupo)}. Com todos vazios o nó fica sem alvo "
                f"e a campanha roda sem nunca encontrar ninguém.",
            ))

    return fora


def _problemas_de_valor(no: dict, campo: Campo, valor: Any, ident: str) -> list[Problema]:
    nid = _id(no)

    if campo.vocab in _VOCAB_DE_ID:
        if not _e_uuid(valor):
            return [Problema(
                nid, "valor_invalido",
                f'{ident}: o campo "{campo.rotulo}" ({campo.chave}) está com '
                f'"{valor}", que não é um identificador válido. O motor compara por '
                f"id — nome ou rótulo digitado à mão nunca casa com nada e o nó não "
                f"faz efeito. Escolha a opção na lista em vez de digitar.",
            )]
        return []

    if campo.vocab in VALORES_FIXOS:
        aceitos = VALORES_FIXOS[campo.vocab]
        if str(valor) not in {v for v, _rot in aceitos}:
            opcoes = ", ".join(f"{v} ({rot})" for v, rot in aceitos)
            return [Problema(
                nid, "valor_invalido",
                f'{ident}: o campo "{campo.rotulo}" ({campo.chave}) está com '
                f'"{valor}", que não é um valor aceito — o motor não reconhece esse '
                f"texto e simplesmente não faz nada (sem erro no log). Use um destes: "
                f"{opcoes}.",
            )]
    return []


# ─── Regras 8 e 9: as saidas de cada no ──────────────────────────────────────────


def _problemas_de_saida(no: dict, ordens: dict[str, int]) -> list[Problema]:
    tipo = _tipo(no)
    nid = _id(no)
    ident = _ident(no, ordens)

    if tipo == "trigger":
        return []   # gatilho sem saida ja e acusado como `gatilho_solto`
    if tipo == "end":
        return []   # no de fim nao tem saida por definicao

    if tipo == "condition":
        faltando = [
            rotulo for rotulo, chave in (("SIM", "yes_node_id"), ("NÃO", "no_node_id"))
            if not no.get(chave)
        ]
        if not faltando:
            return []
        ramos = " e ".join(faltando)
        return [Problema(
            nid, "condicao_incompleta",
            f"{ident} está sem a saída {ramos}. O motor segue "
            f"`yes_node_id` quando a condição dá SIM e `no_node_id` quando dá NÃO; "
            f"com a saída vazia ele encerra a matrícula ali mesmo, em silêncio — o "
            f"lead sai do fluxo sem receber nada e a campanha marca como concluída.",
        )]

    if not _saidas(no):
        return [Problema(
            nid, "no_sem_saida",
            f"{ident} não está ligado a nenhum nó seguinte e não é um nó de "
            f"encerramento. Isso costuma ser a marca de um nó apagado no meio do "
            f"fluxo (ao apagar, a seta de quem vinha antes fica vazia): toda matrícula "
            f"que chegar aqui é encerrada calada. Ligue-o ao próximo nó ou a um nó de "
            f"Encerrar.",
        )]
    return []


# ─── Regras 11 e 12: canal e template ────────────────────────────────────────────


def _problemas_de_envio(no: dict, ordens: dict[str, int], campanha_sem_canal: bool,
                        templates: dict[str, str] | None) -> list[Problema]:
    if _tipo(no) not in _TIPOS_DE_ENVIO:
        return []

    cfg = no.get("config") or {}
    nid = _id(no)
    ident = _ident(no, ordens)
    fora: list[Problema] = []

    if campanha_sem_canal and _vazio(cfg.get("channel_id")):
        extra = (
            " Neste nó o canal ainda decide QUAL janela de 24h vale, porque a janela é "
            "por canal." if _tipo(no) == "send_text" else ""
        )
        fora.append(Problema(
            nid, "sem_canal",
            f"{ident} não tem canal e a campanha também não. Sem canal a mensagem sai "
            f"pelo número da conversa mais recente do lead — que pode ser o da ValerIA, "
            f"assinando como o vendedor — e a marcação \"Finalizar Conversa\" que o "
            f"vendedor faz em /conversas passa a ser ignorada. Escolha o canal da "
            f"campanha (ou um canal neste nó).{extra}",
        ))

    # Regra 12 e a UNICA que o fail-open desliga: `None` quer dizer que a consulta a
    # `message_templates` falhou, nao que o template esteja aprovado. Mapa VAZIO nao e
    # None — vazio e uma resposta ("a Meta nao conhece nenhum desses") e reprova.
    nome = cfg.get("template_name")
    if templates is not None and _tipo(no) == "send" and not _vazio(nome):
        fora.extend(_problema_de_template(nid, ident, str(nome), templates))

    return fora


def _problema_de_template(nid: str, ident: str, nome: str,
                          templates: dict[str, str]) -> list[Problema]:
    """As tres situacoes que um conjunto de aprovados fundiria numa so.

    Ausente, PENDING e REJECTED pedem acoes diferentes do operador (criar, esperar,
    corrigir). Dizer so "nao esta aprovado" devolve a pessoa para a Meta sem saber o
    que procurar — e no caso do ausente ela procura um template que nao existe.
    """
    if nome not in templates:
        return [Problema(
            nid, "template_nao_aprovado",
            f"{ident} usa o template `{nome}`, que NÃO EXISTE na Meta — nunca foi "
            f"submetido, ou foi criado com outro nome. {_ENVIO_MUDO} Crie o template "
            f"com esse nome exato, espere a aprovação e ative a campanha depois.",
        )]

    status = templates[nome]
    bruto = str(status) if status is not None else ""
    normalizado = bruto.strip().lower()
    if normalizado == _STATUS_APROVADO:
        return []

    acao = _ACAO_POR_STATUS.get(normalizado, _ACAO_GENERICA)
    como_esta = f"está {bruto} na Meta" if bruto else "está sem status na Meta"
    return [Problema(
        nid, "template_nao_aprovado",
        f"{ident} usa o template `{nome}`, que {como_esta}. {_ENVIO_MUDO} {acao}",
    )]


# ─── Regras 7 e 10: alcancabilidade e ciclo ──────────────────────────────────────


def _problemas_de_alcance(nos: list[dict], por_id: dict[str, dict], gatilho: dict,
                          ordens: dict[str, int]) -> list[Problema]:
    alcancados = set(_percorrer(por_id, _id(gatilho)))
    return [
        Problema(
            _id(no), "no_inalcancavel",
            f"{_ident(no, ordens)} não é alcançável a partir do gatilho: nenhuma seta "
            f"chega até ele, então ele nunca vai executar. Ligue-o ao fluxo ou apague-o.",
        )
        for no in nos if _id(no) not in alcancados
    ]


def _problemas_de_ciclo(nos: list[dict], por_id: dict[str, dict],
                        ordens: dict[str, int]) -> list[Problema]:
    """DFS com marcacao branco/cinza/preto.

    Cinza/preto e nao "ja visitei": um fluxo com condicao e um GRAFO, nao uma lista —
    os dois ramos desaguando no mesmo no de fim (o losango, que e o desenho normal de
    uma cadencia) faria um detector ingenuo acusar ciclo em campanha correta.
    """
    BRANCO, CINZA, PRETO = 0, 1, 2
    cor = {nid: BRANCO for nid in por_id}
    fora: list[Problema] = []
    ja_relatados: set[frozenset[str]] = set()

    for raiz in [_id(no) for no in nos]:
        if cor.get(raiz, PRETO) != BRANCO:
            continue
        cor[raiz] = CINZA
        caminho = [raiz]
        pilha = [(raiz, iter(_saidas(por_id[raiz])))]
        while pilha:
            atual, arestas = pilha[-1]
            destino = next(arestas, None)
            if destino is None:
                cor[atual] = PRETO
                pilha.pop()
                caminho.pop()
                continue
            if destino not in por_id:
                continue
            if cor[destino] == CINZA:
                volta = caminho[caminho.index(destino):] + [destino]
                assinatura = frozenset(volta)
                if assinatura not in ja_relatados:
                    ja_relatados.add(assinatura)
                    trilha = " → ".join(_curto(por_id[nid], ordens) for nid in volta)
                    fora.append(Problema(
                        destino, "ciclo",
                        f"O fluxo volta para trás e fecha um ciclo: {trilha}. A "
                        f"matrícula repete esse trecho para sempre — o lead recebe o "
                        f"mesmo toque de novo e de novo, e a campanha nunca termina. "
                        f"Corte uma das setas de volta.",
                    ))
                continue
            if cor[destino] == BRANCO:
                cor[destino] = CINZA
                caminho.append(destino)
                pilha.append((destino, iter(_saidas(por_id[destino]))))
    return fora


# ─── A entrada ───────────────────────────────────────────────────────────────────


def validar(campanha: dict, nos: list[dict],
            templates: dict[str, str] | None) -> list[Problema]:
    """Tudo o que impede esta campanha de ser ativada. Lista vazia = pode ligar.

    `campanha` e a linha de `campaigns` (so `channel_id` e lido), `nos` sao as linhas de
    `campaign_nodes` como o PostgREST devolve (id, type, config, next/yes/no_node_id) e
    `templates` e o mapa nome → status CRU da Meta ('APPROVED'/'PENDING'/'REJECTED'…),
    ou None quando a consulta falhou — unico caso de fail-open (ver o cabecalho do
    modulo). Nome que nao esta no mapa e um template que nao existe na Meta.

    A ordem da lista e a de leitura da tela: primeiro o que e da campanha inteira,
    depois cada no na ordem em que veio, e por fim os problemas de topologia.
    """
    campanha = campanha or {}
    nos = [n for n in (nos or []) if isinstance(n, dict) and n.get("id")]
    por_id = {_id(n): n for n in nos}

    gatilhos = [n for n in nos if _tipo(n) == "trigger"]
    # `gatilho` so existe quando ha UM: com zero ou dois, seguir "o primeiro" seria
    # validar um fluxo que o motor talvez nem execute.
    gatilho = gatilhos[0] if len(gatilhos) == 1 else None
    ordens = _ordens_de_envio(por_id, gatilho)

    problemas: list[Problema] = []

    if not gatilhos:
        problemas.append(Problema(
            None, "sem_gatilho",
            "A campanha não tem nó de gatilho. O gatilho é o que matricula o lead — "
            "sem ele a campanha fica ativa e nunca acontece nada.",
        ))
    elif len(gatilhos) > 1:
        quais = ", ".join(f'"{_rotulo(n)}"' for n in gatilhos)
        problemas.append(Problema(
            None, "gatilho_duplicado",
            f"A campanha tem {len(gatilhos)} nós de gatilho ({quais}), e o motor usa "
            f"apenas o primeiro que encontra — os outros ficam desenhados na tela sem "
            f"nunca disparar. Deixe um só gatilho por campanha.",
        ))
    elif not gatilho.get("next_node_id"):
        problemas.append(Problema(
            _id(gatilho), "gatilho_solto",
            "O gatilho não está ligado a nenhum nó. A matrícula começa no nó SEGUINTE "
            "ao gatilho: sem essa ligação o lead é matriculado e o fluxo termina no "
            "mesmo instante.",
        ))

    campanha_sem_canal = _vazio(campanha.get("channel_id"))
    for no in nos:
        problemas.extend(_problemas_de_campo(no, ordens))
        problemas.extend(_problemas_de_saida(no, ordens))
        problemas.extend(_problemas_de_envio(no, ordens, campanha_sem_canal, templates))

    # Alcancabilidade so faz sentido com um gatilho ligado: sem ponto de partida TODO
    # no seria orfao e a lista viraria ruido em cima da causa real, que ja foi relatada.
    if gatilho is not None and gatilho.get("next_node_id"):
        problemas.extend(_problemas_de_alcance(nos, por_id, gatilho, ordens))

    problemas.extend(_problemas_de_ciclo(nos, por_id, ordens))
    return problemas
