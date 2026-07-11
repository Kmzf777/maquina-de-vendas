"""Gatilho determinístico de entrada por frase de prefill de anúncio (Trilha B, auditoria 10/07).

Alguns anúncios abrem a conversa com uma frase de prefill FIXA — ex.: "Olá! Quero saber mais
sobre ter a Marca Própria de Café." Ela deveria mover o lead pro funil certo já na entrada,
mas isso dependia do LLM chamar `mudar_stage`: falhou silenciosamente em 1 de 4 leads (o João
Marcos ficou preso em `pending` por 2 turnos e o catálogo nem foi injetado, porque
`catalog.get_products_by_funnel` devolve "" para stage fora dos funis).

Este módulo é o NÚCLEO PURO do gatilho (segue o padrão de `app/agent/persona.py`): mapeia a
frase EXATA (após normalização) para o stage de destino, sem nenhum I/O — testável isolado. O
efeito de transição (writes no banco) fica no processor, que chama `apply_stage_transition`.

Regra de match: IGUALDADE da frase normalizada, nunca substring — para não sequestrar uma
mensagem grande que apenas CONTENHA a frase de prefill.
"""
from __future__ import annotations

import unicodedata

# Pontuação tolerada NAS BORDAS da frase (a Meta às vezes acrescenta "." final; o lead pode
# colar a frase com "!!!" no fim). Só as pontas são limpas — pontuação interna (o "!" de
# "Olá!") é significativa e faz parte da chave normalizada.
_BORDER_PUNCT = "!.?,;: "


def _normalize(text: str | None) -> str:
    """Normaliza para comparação por igualdade: sem acento, minúsculo, espaços colapsados,
    pontuação das PONTAS removida. Espelha o estilo de `app/agent/catalog.py:_normalize`
    (NFKD + descarte de combining chars), mas preserva espaços como separador (não vira
    underscore) porque a chave aqui é uma frase inteira, não um slug."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    collapsed = " ".join(no_accents.lower().split())  # colapsa qualquer whitespace repetido
    return collapsed.strip(_BORDER_PUNCT)


# Mapa frase-normalizada → stage de destino. As chaves são registradas JÁ NORMALIZADAS
# (rode o texto original por _normalize antes de acrescentar uma nova). Note o "!" interno
# preservado e o "." final removido pela limpeza de bordas.
PREFILL_STAGE_TRIGGERS: dict[str, str] = {
    "ola! quero saber mais sobre ter a marca propria de cafe": "private_label",
}


def match_prefill_stage(text: str | None) -> str | None:
    """Stage de destino se `text` casar EXATAMENTE (após normalização) com uma frase de
    prefill conhecida; None caso contrário. Igualdade, nunca substring."""
    return PREFILL_STAGE_TRIGGERS.get(_normalize(text))
