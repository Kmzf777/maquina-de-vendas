"""Tabela de preços e texto de card da ValerIA v2 (puro, sem I/O).

Todo preço vem da lista de produtos recebida (`products`); nenhum valor de
negócio é escrito à mão aqui. O módulo só lê atributos do Card (id, corpo,
skus, exige_min_lot), então não importa o tipo em runtime.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:  # pragma: no cover
    from app.button_flow.valeria_registry import Card

LIMITE_CARD_CHARS = 160
LIMITE_CARD_QUEBRAS = 2
SKU_BASE_PL = "Café Canastra 250g — c/ embalagem Canastra"
PACOTES_EXEMPLO_PL = 100

_MARCADOR = re.compile(r"\{preco:([^}]+)\}")


# ------------------------------------------------------------ formatação

_PRECO_RE = re.compile(r"^\s*R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s*$")
_CENTAVO = Decimal("0.01")


def _parse(preco: object) -> Decimal | None:
    """'R$ 1.169,70' -> Decimal('1169.70'). Estrito: qualquer outra coisa ou valor <= 0 vira None."""
    if not isinstance(preco, str):
        return None
    m = _PRECO_RE.match(preco)
    if not m:
        return None
    valor = Decimal(m.group(1).replace(".", "") + "." + (m.group(2) or "0"))
    return valor if valor > 0 else None


def _formatar(valor: Decimal) -> str:
    """Decimal -> 'R$ 2.670,00' (milhar com ponto, decimal com vírgula)."""
    valor = valor.quantize(_CENTAVO, ROUND_HALF_UP)
    s = f"{valor:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


# --------------------------------------------------------------- leitura

def precos_por_nome(produtos: list[dict], setor: str) -> dict[str, str]:
    """{products.name: price_formatted} só de ativos no setor com preço válido.

    Preço que não passa no parse estrito é descartado: preço errado é pior que sem preço.
    """
    saida: dict[str, str] = {}
    for p in produtos or []:
        if p.get("sector") != setor or not p.get("is_active"):
            continue
        preco = p.get("price_formatted")
        if isinstance(preco, str) and p.get("name") and _parse(preco) is not None:
            saida[p["name"]] = preco.strip()
    return saida


def min_lots_por_nome(produtos: list[dict], setor: str) -> dict[str, str]:
    """{products.name: min_lot} dos ativos do setor que têm min_lot (texto)."""
    saida: dict[str, str] = {}
    for p in produtos or []:
        if p.get("sector") != setor or not p.get("is_active"):
            continue
        lote = p.get("min_lot")
        if isinstance(lote, str) and lote.strip() and p.get("name"):
            saida[p["name"]] = lote.strip()
    return saida


# ------------------------------------------------------------------ card

def resolver_card(card: "Card", precos: dict[str, str], min_lots: dict[str, str]) -> str | None:
    """Texto final do card, ou None se o card não puder sair."""
    nomes = set(card.skus) | set(_MARCADOR.findall(card.corpo))
    if any(n not in precos for n in nomes):
        return None
    if card.exige_min_lot is not None:
        exigido = card.exige_min_lot.strip()
        if any((min_lots.get(s) or "").strip() != exigido for s in card.skus):
            return None
    texto = _MARCADOR.sub(lambda m: precos[m.group(1)], card.corpo)
    if len(texto) > LIMITE_CARD_CHARS or texto.count("\n") > LIMITE_CARD_QUEBRAS:
        return None
    return texto


# ---------------------------------------------------------------- tabela

class Slot(NamedTuple):
    """Um trecho da linha: `rotulo` + preço(s) das `variantes` [(nome, sku)].

    Se as variantes presentes têm preços diferentes, imprime todas com o nome;
    se iguais, imprime um preço só (com o nome apenas quando `nomear`).
    `por_kg` acrescenta o preço por kg (preço do pacote de 2kg / 2).
    """
    rotulo: str
    variantes: tuple[tuple[str, str], ...]
    nomear: bool = False
    por_kg: bool = False


def _cs(tipo: str, formato: str) -> tuple[tuple[str, str], ...]:
    return (("Clássico", f"Canastra Clássico — {tipo} {formato}"),
            ("Suave", f"Canastra Suave — {tipo} {formato}"))


# Cada grupo: (cabeçalho, linhas). Linha = (prefixo, slots). Prefixo None = linha única
# "cabeçalho + slots"; com prefixo, o cabeçalho vai sozinho e cada linha começa pelo prefixo.
# Grupos/slots sem nenhum SKU ativo somem; SKU ausente dentro de um slot é ignorado.
GRUPOS_ATACADO: tuple = (
    ("☕ Clássico · Suave", (
        ("250g", (Slot("moído", _cs("Moído", "250g")), Slot("grão", _cs("Em Grãos", "250g")))),
        ("500g", (Slot("moído", _cs("Moído", "500g")), Slot("grão", _cs("Em Grãos", "500g")))),
        ("1kg", (Slot("grão", _cs("Em Grãos", "1kg")),)),
    )),
    ("☕ Canela  ", ((None, (Slot("250g moído", (("", "Canastra Canela — Moído 250g"),)),)),)),
    ("☕ Microlote  ", ((None, (Slot("250g", (("moído", "Microlote — Moído 250g"),
                                              ("grão", "Microlote — Em Grãos 250g"))),)),)),
    ("☕ Néctar de Minas  ", ((None, (
        Slot("Gourmet 1kg", (("", "Néctar de Minas Gourmet — Em Grãos 1kg"),)),
        Slot("moído 500g", (("", "Néctar de Minas Gourmet — Moído 500g"),)),
        Slot("Blend 1kg", (("", "Néctar de Minas Blend Arábica+Robusta — Em Grãos 1kg"),)),
    )),)),
    ("📦 Granel 2kg em grão  ", ((None, (
        Slot("", (("Clássico", "Granel Canastra Clássico — 2kg em grãos"),
                  ("Suave", "Granel Canastra Suave — 2kg em grãos")), nomear=True, por_kg=True),
        Slot("Néctar", (("Espresso", "Granel Néctar de Minas Espresso — 2kg em grãos"),
                        ("Intenso", "Granel Néctar de Minas Intenso — 2kg em grãos"))),
    )),)),
    ("☕ ", ((None, (
        Slot("Cápsulas (10 un)", (("Clássico", "Cápsula Canastra Clássico — Display 10 cápsulas"),
                                  ("Canela", "Cápsula Canastra Canela — Display 10 cápsulas"))),
        Slot("Drip (10 sachês)", (("", "Drip Coffee Canastra Suave — Display 10 sachês"),)),
    )),)),
    ("⚙️ ", ((None, (
        Slot("Moedor profissional", (("", "Moedor Elétrico Profissional — Unitário"),)),
        Slot("Moedor + 10 granel", (("", "Moedor + 10 pacotes granel"),)),
    )),)),
)


def _com_kg(preco: str, por_kg: bool) -> str:
    if not por_kg:
        return preco
    valor = _parse(preco)
    return f"{preco} ({_formatar(valor / 2)}/kg)" if valor is not None else preco


def _render_slot(slot: Slot, precos: dict[str, str]) -> str | None:
    presentes = [(nome, precos[sku]) for nome, sku in slot.variantes if sku in precos]
    if not presentes:
        return None
    if len({p for _, p in presentes}) > 1:
        texto = " · ".join(f"{n} {_com_kg(p, slot.por_kg)}".strip() for n, p in presentes)
    else:
        texto = _com_kg(presentes[0][1], slot.por_kg)
        if slot.nomear:
            texto = f"{'/'.join(n for n, _ in presentes)} {texto}"
    return f"{slot.rotulo} {texto}".strip()


def _linhas_atacado(precos: dict[str, str]) -> list[str]:
    saida: list[str] = []
    for cabecalho, linhas in GRUPOS_ATACADO:
        corpos: list[tuple[str | None, str]] = []
        for prefixo, slots in linhas:
            partes = [r for r in (_render_slot(sl, precos) for sl in slots) if r]
            if partes:
                corpos.append((prefixo, " · ".join(partes)))
        if not corpos:
            continue
        if corpos[0][0] is None:
            saida.append(f"{cabecalho}{corpos[0][1]}")
        else:
            saida.append(cabecalho)
            saida.extend(f"{pre:<4}  {corpo}" for pre, corpo in corpos)
    return saida


def tabela_atacado(precos: dict[str, str], regras: str) -> str | None:
    """Mensagem 2 do atacado. None se não há nenhum preço."""
    if not precos:
        return None
    linhas = _linhas_atacado(precos)
    if not linhas:
        return None
    partes = ["tabela atacado — preço por pacote 📋", "", *linhas]
    if regras:
        partes += ["", regras]
    return "\n".join(partes)


# ------------------------------------------------------------ private label

def total_pl(precos: dict[str, str]) -> str | None:
    """100 × preço do 250g c/ embalagem Canastra, em reais."""
    valor = _parse(precos.get(SKU_BASE_PL, ""))
    if valor is None:
        return None
    return _formatar(valor * PACOTES_EXEMPLO_PL)


def como_funciona_pl(precos: dict[str, str], modelo: str) -> str | None:
    """Resolve {total_pl} no modelo; None se o SKU base faltar."""
    total = total_pl(precos)
    if total is None:
        return None
    return modelo.replace("{total_pl}", total)
