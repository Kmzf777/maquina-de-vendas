"""Harmonização da política de preço: número travado, moldura liberada (FinOps 08/07/2026).

O system prompt carregava uma CONTRADIÇÃO frontal viajando junta em toda chamada comercial:
a regra 12 do base.py + o roteiro de atacado + todos os few-shots mandam usar verbo de
referência ("gira em torno de R$28,70" — exigência de QA/compliance), enquanto o
_build_catalog_block (C4, ae2728a) proibia exatamente essas expressões. Instrução em
conflito = mais thinking queimado e comportamento errático.

A intenção real do C4 era INTEGRIDADE DO VALOR (centavo exato, nunca arredondar/misturar
SKU) — não a moldura da frase. Harmonização: as três camadas passam a dizer a MESMA coisa:
o NÚMERO é sempre o exato do catálogo; a moldura de referência é permitida AO REDOR dele;
proibido usar a moldura para alterar/arredondar/vagar o número.
"""
from datetime import datetime, timezone, timedelta

from app.agent.orchestrator import _build_catalog_block
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT

TZ_BR = timezone(timedelta(hours=-3))


def _rule12_region() -> str:
    prompt = build_base_prompt(None, None, datetime.now(TZ_BR))
    start = prompt.find("12. PRECO")
    end = prompt.find("13. ", start)
    assert start != -1 and end != -1, "regra 12 não encontrada no base prompt"
    return prompt[start:end]


def test_catalog_block_trava_o_numero_e_libera_a_moldura():
    block = _build_catalog_block("- **Suave**\n  - Preço: R$28,70")
    low = block.lower()
    # a proibição de moldura (contradição com a regra 12/QA) saiu
    assert "amacie" not in low, "bloco de catálogo ainda proíbe a moldura de referência da regra 12"
    # a integridade do valor (intenção real do C4) permanece
    assert "exat" in low and "centavo" in low
    assert "arredondar" in low or "arredonde" in low
    # e a ponte explícita com a moldura da regra 12 existe
    assert "verbo de referencia" in low or "moldura" in low


def test_catalog_block_mantem_regras_de_variacao_e_ausencia():
    """As demais lições do C4 seguem intactas (SKU distinto, preço ausente → João)."""
    low = _build_catalog_block("qualquer").lower()
    assert "varia" in low  # confirmar variação antes do preço
    assert "não estiver na lista" in low or "nao estiver na lista" in low


def test_regra12_ancora_no_valor_exato_do_catalogo():
    low = _rule12_region().lower()
    # a moldura continua (exigência de QA)…
    assert "gira em torno de" in low
    # …mas agora ancorada explicitamente no número exato do catálogo
    assert "catalogo" in low or "catálogo" in low
    assert "exat" in low


def test_atacado_qualificadores_ancoram_valor_exato():
    low = ATACADO_PROMPT.lower()
    start = low.find("## apresentacao de precos")
    assert start != -1
    end = low.find("\n## ", start + 10)
    section = low[start:end if end != -1 else None]
    assert "gira em torno de" in section  # moldura preservada
    assert "exat" in section, "seção de qualificadores não ancora o número exato do catálogo"
