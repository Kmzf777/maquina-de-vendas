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


def _limite_de_rotulo(no: reg.No) -> int:
    return reg.LIMITE_TITULO_LISTA if no.tela == "lista" else reg.LIMITE_ROTULO_BOTAO


def validar(node_id: str, payload: dict) -> str | None:
    """Valida um override antes de gravar. Devolve a mensagem de erro (PT-BR,
    pra tela mostrar ao operador) ou `None` quando o payload pode ser salvo.

    Este é o portão que `carregar`/`aplicar` não têm como ter: eles só LEEM o
    que já está gravado, e uma linha inválida ali dentro simplesmente não seria
    aplicada por `aplicar` (rótulo não bate com nenhum `botao.id`) ou, pior,
    seria aplicada e a Meta recusaria o envio — a ValerIA fica muda naquele nó
    até alguém notar. Chamar isto ANTES do INSERT/UPDATE é o que fecha o buraco.
    """
    if node_id == reg.CHAVE_NUDGE:
        corpo = payload.get("corpo")
        if corpo is not None and not corpo.strip():
            return "o corpo do nudge não pode ficar vazio"
        return None

    no = reg.NOS.get(node_id)
    if no is None:
        return f"nó {node_id!r} não existe no registry"

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
