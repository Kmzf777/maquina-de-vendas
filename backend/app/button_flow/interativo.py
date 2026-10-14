"""A estrutura da mensagem interativa gravada em `messages.metadata["interativo"]`.

O CRM (/conversas) só via o TEXTO das telas da ValerIA: os botões, o menu de lista e o
carrossel que o lead recebeu não chegavam à bolha, e o vendedor não sabia o que o lead
viu. Cada ponto que envia uma mensagem interativa grava, junto da linha, a estrutura
que saiu — e este módulo é o ÚNICO que a monta, para a forma não divergir entre a v1,
a v2 e a Recuperação.

A FORMA É CONTRATO com `frontend/src/lib/message-interativo.ts` (que a valida e a
desenha). Mudar uma chave aqui apaga a tela do vendedor sem erro nenhum:

    {"tipo": "botoes",    "imagem": <url|None>, "botoes": [<rótulo>, ...]}
    {"tipo": "lista",     "botao": <rótulo>, "linhas": [{"titulo", "descricao"}, ...]}
    {"tipo": "carrossel", "cards": [{"imagem", "texto", "botoes": [<rótulo>, ...]}, ...]}

Rótulos como o lead os viu (nunca o id), imagem como a URL pública que foi no header
e texto do card exatamente como enviado.

Puro, sem I/O. `metadata` é fail-soft: a mensagem JÁ saiu quando a estrutura é
montada, e um erro aqui não pode custar o registro dela no CRM.
"""
from __future__ import annotations

import logging
from typing import Callable, Iterable

logger = logging.getLogger(__name__)

CHAVE = "interativo"


def botoes(rotulos: Iterable[str], imagem: str | None = None) -> dict:
    return {"tipo": "botoes", "imagem": imagem or None, "botoes": [str(r) for r in rotulos]}


def lista(botao: str, linhas: Iterable[tuple[str, str | None]]) -> dict:
    return {
        "tipo": "lista",
        "botao": str(botao),
        "linhas": [{"titulo": str(titulo), "descricao": str(descricao or "")}
                   for titulo, descricao in linhas],
    }


def carrossel(cards: Iterable[tuple[str | None, str, Iterable[str]]]) -> dict:
    return {
        "tipo": "carrossel",
        "cards": [{"imagem": imagem or None, "texto": str(texto or ""),
                   "botoes": [str(r) for r in rotulos]}
                  for imagem, texto, rotulos in cards],
    }


def metadata(construir: Callable[[], dict | None], base: dict | None = None) -> dict | None:
    """`base` + `{"interativo": construir()}`. Nunca levanta.

    Recebe a CONSTRUÇÃO (e não o dict pronto) para que o erro de montar — um botão sem
    rótulo, um override estranho — caia aqui dentro, no try, e não na linha do chamador.
    Erro ou estrutura vazia devolvem a `base` intacta (None quando não havia base).
    """
    resultado = dict(base) if isinstance(base, dict) else None
    try:
        estrutura = construir()
    except Exception as exc:
        logger.warning("[INTERATIVO] estrutura da mensagem não montada — linha sem "
                       "metadata.%s: %s", CHAVE, exc)
        return resultado
    if not estrutura:
        return resultado
    resultado = resultado or {}
    resultado[CHAVE] = estrutura
    return resultado
