"""Orçamento determinístico para o setor atacado.

Módulo puro (sem rede, sem banco): matematica do carrinho, tabela de frete por região,
mapa UF→macrorregião, normalização de preços BRL e match de produtos por substring.

Consumido por tools.py — não importar de lá diretamente.

Princípios:
- Preços de produto NUNCA são hardcoded aqui (D1): vêm do DB `products` em tempo de
  cálculo, parseados pelo caller via `parse_brl`.
- Apenas frete/pedido-mínimo e o mapa UF→região são constantes aqui — esses são dados
  de negócio que saem do prompt (atacado.py) e se tornam código testável.
- Todas as funções são puras: mesmos inputs → mesmo output, sem efeito colateral.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Constantes de negócio — frete e regiões (movidas de atacado.py)
# ---------------------------------------------------------------------------


class FreightRule(BaseModel):
    """Regra de frete para uma macrorregião."""

    pedido_minimo: float
    frete: float
    gratis_acima: float


FREIGHT_TABLE: dict[str, FreightRule] = {
    "sul_sudeste": FreightRule(pedido_minimo=300.0, frete=55.0, gratis_acima=900.0),
    "centro_oeste": FreightRule(pedido_minimo=300.0, frete=65.0, gratis_acima=1000.0),
    "nordeste":     FreightRule(pedido_minimo=300.0, frete=75.0, gratis_acima=1200.0),
    "norte":        FreightRule(pedido_minimo=300.0, frete=85.0, gratis_acima=1500.0),
}

# Mapa IBGE de UF → chave do FREIGHT_TABLE.
# Sul e Sudeste compartilham a faixa 'sul_sudeste' (D2).
UF_TO_REGION: dict[str, str] = {
    # Norte
    "AC": "norte", "AP": "norte", "AM": "norte", "PA": "norte",
    "RO": "norte", "RR": "norte", "TO": "norte",
    # Nordeste
    "AL": "nordeste", "BA": "nordeste", "CE": "nordeste", "MA": "nordeste",
    "PB": "nordeste", "PE": "nordeste", "PI": "nordeste", "RN": "nordeste",
    "SE": "nordeste",
    # Centro-Oeste
    "DF": "centro_oeste", "GO": "centro_oeste", "MT": "centro_oeste", "MS": "centro_oeste",
    # Sudeste → sul_sudeste
    "ES": "sul_sudeste", "MG": "sul_sudeste", "RJ": "sul_sudeste", "SP": "sul_sudeste",
    # Sul → sul_sudeste
    "PR": "sul_sudeste", "RS": "sul_sudeste", "SC": "sul_sudeste",
}

# Override de cidade: frete flat, sem pedido mínimo, sem faixa de grátis (B2).
UBERLANDIA_FREIGHT: float = 15.0

# P2: desambiguação retorna no máximo este número de matches para não estourar contexto.
MAX_DISAMBIGUATION: int = 5

# Forma normalizada (sem acento, minúsculo) do override de cidade.
_UBERLANDIA_NORMALIZED = "uberlandia"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PedidoItem(BaseModel):
    """Um item do carrinho (B1: orçamento é um carrinho, não um único produto)."""

    produto: str
    quantidade: int = Field(gt=0, description="Quantidade deve ser > 0")


class OrcamentoInput(BaseModel):
    """Input validado de um orçamento — sempre um carrinho com >= 1 item."""

    itens: list[PedidoItem] = Field(min_length=1)
    estado: Optional[str] = None   # Sigla UF, ex. "SP"
    cidade: Optional[str] = None   # Override de cidade, ex. "Uberlândia"


class LineQuote(BaseModel):
    """Linha resolvida do carrinho: produto já matchado no catálogo + preço do DB."""

    produto: str
    quantidade: int
    preco_unitario: float
    subtotal_linha: float


class Quote(BaseModel):
    """Resultado do cálculo determinístico do orçamento."""

    lines: list[LineQuote]
    subtotal: float
    frete: float
    total: float
    frete_gratis: bool
    abaixo_minimo: bool
    pedido_minimo: Optional[float]   # None para Uberlândia (sem pedido mínimo)
    region_key: Optional[str]


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _normalize_text(value: str | None) -> str:
    """Remove acentos e converte para minúsculas para comparação normalizada."""
    if not value:
        return ""
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _fmt_brl(value: float) -> str:
    """Formata float em string BRL (R$ 1.234,56)."""
    # Python :,.2f usa , como milhar e . como decimal → trocar separadores
    formatted = f"{value:,.2f}"  # e.g. "1,234.56"
    swapped = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {swapped}"


# ---------------------------------------------------------------------------
# Funções públicas — puras, testáveis sem rede
# ---------------------------------------------------------------------------


def parse_brl(s: str) -> float:
    """Converte string de preço BRL para float.

    Exemplos:
        "R$ 97,70"    → 97.70
        "R$ 1.169,70" → 1169.70

    Levanta ValueError para formato inválido (P1: chamado apenas nos produtos
    que deram match — não rode na base de dados inteira).
    """
    clean = re.sub(r"R\$\s*", "", s.strip())  # remove "R$" e espaços iniciais
    clean = clean.replace(".", "")             # remove separador de milhar
    clean = clean.replace(",", ".")            # vírgula decimal → ponto
    clean = clean.strip()
    if not clean:
        raise ValueError(f"Valor BRL inválido: {s!r}")
    try:
        return float(clean)
    except ValueError:
        raise ValueError(f"Valor BRL inválido: {s!r}")


def resolve_region(
    estado: str | None,
    cidade: str | None,
) -> tuple[str | None, bool]:
    """Resolve a chave de região a partir do estado e/ou cidade.

    Retorna (region_key, is_uberlandia):
    - Se cidade normalizada == "uberlandia": (None, True) — mesmo sem estado (B2).
    - Se UF conhecida: (region_key, False).
    - Caso contrário: (None, False) — caller deve pedir o estado.
    """
    # B2: Override de cidade tem precedência sobre o estado
    if _normalize_text(cidade) == _UBERLANDIA_NORMALIZED:
        return (None, True)

    if estado:
        region = UF_TO_REGION.get(estado.upper())
        if region:
            return (region, False)

    return (None, False)


def match_products(produto: str, products: list[dict]) -> list[dict]:
    """Busca produtos por substring normalizada (sem acento, caixa baixa).

    Retorna até MAX_DISAMBIGUATION resultados (P2 — nunca devolve 50+ itens ao LLM).
    Considera apenas o campo "name" de cada dicionário de produto.
    """
    needle = _normalize_text(produto)
    if not needle:
        return []

    matches = [
        p for p in products
        if needle in _normalize_text(p.get("name", ""))
    ]
    return matches[:MAX_DISAMBIGUATION]


def compute_quote(
    lines: list[LineQuote],
    region_key: str | None,
    is_uberlandia: bool,
) -> Quote:
    """Calcula o orçamento a partir das linhas resolvidas do carrinho.

    B1: o pedido mínimo é avaliado sobre o subtotal GLOBAL (soma de todas as linhas),
    não linha a linha.
    B2: Uberlândia → frete flat R$15, sem pedido mínimo, sem faixa de grátis.
    """
    subtotal = sum(line.subtotal_linha for line in lines)

    if is_uberlandia:
        frete = UBERLANDIA_FREIGHT
        frete_gratis = False
        abaixo_minimo = False
        pedido_minimo = None
    else:
        rule = FREIGHT_TABLE.get(region_key) if region_key else None
        if rule is None:
            # Região desconhecida: o caller (tools.py) deve detectar este caso
            # antes de chamar compute_quote e pedir o estado ao usuário.
            frete = 0.0
            frete_gratis = False
            abaixo_minimo = False
            pedido_minimo = None
        else:
            pedido_minimo = rule.pedido_minimo
            abaixo_minimo = subtotal < rule.pedido_minimo
            if subtotal >= rule.gratis_acima:
                frete = 0.0
                frete_gratis = True
            else:
                frete = rule.frete
                frete_gratis = False

    return Quote(
        lines=lines,
        subtotal=subtotal,
        frete=frete,
        total=subtotal + frete,
        frete_gratis=frete_gratis,
        abaixo_minimo=abaixo_minimo,
        pedido_minimo=pedido_minimo,
        region_key=region_key,
    )


def format_quote(quote: Quote) -> str:
    """Formata o orçamento em texto legível, item a item.

    Inclui:
    - Breakdown por linha (produto, quantidade, preço unitário, subtotal da linha).
    - Subtotal global do pedido.
    - Frete (em BRL ou "grátis").
    - Total do pedido.
    - Aviso de pedido mínimo quando abaixo_minimo=True.
    """
    parts: list[str] = ["*Orçamento detalhado:*"]

    for line in quote.lines:
        preco_fmt = _fmt_brl(line.preco_unitario)
        sub_fmt = _fmt_brl(line.subtotal_linha)
        parts.append(f"• {line.produto}: {line.quantidade}x {preco_fmt} = {sub_fmt}")

    parts.append("")
    parts.append(f"Subtotal: {_fmt_brl(quote.subtotal)}")

    if quote.frete_gratis:
        parts.append("Frete: grátis ✓")
    else:
        parts.append(f"Frete: {_fmt_brl(quote.frete)}")

    parts.append(f"*Total: {_fmt_brl(quote.total)}*")

    if quote.abaixo_minimo and quote.pedido_minimo is not None:
        min_fmt = _fmt_brl(quote.pedido_minimo)
        parts.append(
            f"\n⚠️ Pedido mínimo para atacado: {min_fmt}. "
            "Adicione mais itens ao carrinho para prosseguir."
        )

    return "\n".join(parts)
