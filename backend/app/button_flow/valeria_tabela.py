"""Tabela de preços e texto de card da ValerIA v2 (puro, sem I/O).

Todo preço vem da lista de produtos recebida (`products`); nenhum valor de
negócio é escrito à mão aqui. O módulo só lê atributos do Card (id, corpo,
skus, exige_min_lot), então não importa o tipo em runtime.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.button_flow.valeria_registry import Card

LIMITE_CARD_CHARS = 160
LIMITE_CARD_QUEBRAS = 2
SKU_BASE_PL = "Café Canastra 250g — c/ embalagem Canastra"
PACOTES_EXEMPLO_PL = 100

_MARCADOR = re.compile(r"\{preco:([^}]+)\}")


# --------------------------------------------------------------- leitura

def precos_por_nome(produtos: list[dict], setor: str) -> dict[str, str]:
    """{products.name: price_formatted} só de ativos com preço, no setor dado."""
    saida: dict[str, str] = {}
    for p in produtos or []:
        if p.get("sector") != setor or not p.get("is_active"):
            continue
        preco = (p.get("price_formatted") or "").strip()
        if preco and p.get("name"):
            saida[p["name"]] = preco
    return saida


def min_lots_por_nome(produtos: list[dict], setor: str) -> dict[str, str]:
    """{products.name: min_lot} dos ativos do setor que têm min_lot."""
    saida: dict[str, str] = {}
    for p in produtos or []:
        if p.get("sector") != setor or not p.get("is_active"):
            continue
        lote = (p.get("min_lot") or "").strip()
        if lote and p.get("name"):
            saida[p["name"]] = lote
    return saida


# ------------------------------------------------------------ formatação

def _parse(preco: str) -> Decimal | None:
    """'R$ 1.169,70' -> Decimal('1169.70')."""
    limpo = re.sub(r"[^\d,.]", "", preco or "")
    limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except (InvalidOperation, ValueError):
        return None


def _formatar(valor: Decimal) -> str:
    """Decimal -> 'R$ 2.670,00' (milhar com ponto, decimal com vírgula)."""
    s = f"{valor:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


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

def _slot(precos: dict[str, str], rotulo: str, classico: str | None, suave: str | None = None) -> str | None:
    """'moído X' ou, se Clássico e Suave diferem, 'moído Clássico X · Suave Y'."""
    c = precos.get(classico) if classico else None
    s = precos.get(suave) if suave else None
    if c and s and c != s:
        return f"{rotulo} Clássico {c} · Suave {s}"
    valor = c or s
    return f"{rotulo} {valor}" if valor else None


def _juntar(partes: list[str | None], sep: str = " · ") -> str:
    return sep.join(p for p in partes if p)


def _linhas_atacado(p: dict[str, str]) -> list[str]:
    linhas: list[str] = []

    def cs(formato: str, tipo: str) -> tuple[str, str]:
        return (f"Canastra Clássico — {tipo} {formato}", f"Canastra Suave — {tipo} {formato}")

    cabecalho_cs = []
    for fmt, label in (("250g", "250g "), ("500g", "500g "), ("1kg", "1kg  ")):
        moido = _slot(p, "moído", *cs(fmt, "Moído")) if fmt != "1kg" else None
        grao = _slot(p, "grão", *cs(fmt, "Em Grãos"))
        corpo = _juntar([moido, grao])
        if corpo:
            cabecalho_cs.append(f"{label} {corpo}")
    if cabecalho_cs:
        linhas.append("☕ Clássico · Suave")
        linhas.extend(cabecalho_cs)

    canela = _slot(p, "250g moído", "Canastra Canela — Moído 250g")
    if canela:
        linhas.append(f"☕ Canela  {canela}")

    micro_m, micro_g = p.get("Microlote — Moído 250g"), p.get("Microlote — Em Grãos 250g")
    if micro_m and micro_g and micro_m != micro_g:
        micro = f"250g moído {micro_m} · grão {micro_g}"
    elif micro_m or micro_g:
        micro = f"250g {micro_m or micro_g}"
    else:
        micro = ""
    if micro:
        linhas.append(f"☕ Microlote  {micro}")

    nectar = _juntar([
        _slot(p, "Gourmet 1kg", "Néctar de Minas Gourmet — Em Grãos 1kg"),
        _slot(p, "moído 500g", "Néctar de Minas Gourmet — Moído 500g"),
        _slot(p, "Blend 1kg", "Néctar de Minas Blend Arábica+Robusta — Em Grãos 1kg"),
    ])
    if nectar:
        linhas.append(f"☕ Néctar de Minas  {nectar}")

    granel_c = p.get("Granel Canastra Clássico — 2kg em grãos")
    granel_s = p.get("Granel Canastra Suave — 2kg em grãos")
    granel_n = _juntar([p.get("Granel Néctar de Minas Espresso — 2kg em grãos"),
                        p.get("Granel Néctar de Minas Intenso — 2kg em grãos")])
    base = granel_c or granel_s
    partes_granel: list[str] = []
    if base:
        valor = _parse(base)
        por_kg = f" ({_formatar(valor / 2)}/kg)" if valor is not None else ""
        if granel_c and granel_s and granel_c != granel_s:
            partes_granel.append(f"Clássico {granel_c} · Suave {granel_s}{por_kg}")
        else:
            partes_granel.append(f"Clássico/Suave {base}{por_kg}")
    nec = [p[n] for n in ("Granel Néctar de Minas Espresso — 2kg em grãos",
                          "Granel Néctar de Minas Intenso — 2kg em grãos") if n in p]
    if nec:
        partes_granel.append(f"Néctar {nec[0]}" if len(set(nec)) == 1 else "Néctar " + " / ".join(nec))
    if partes_granel:
        linhas.append(f"📦 Granel 2kg em grão  {' · '.join(partes_granel)}")

    caps = p.get("Cápsula Canastra Clássico — Display 10 cápsulas") or p.get("Cápsula Canastra Canela — Display 10 cápsulas")
    drip = p.get("Drip Coffee Canastra Suave — Display 10 sachês")
    cd = _juntar([f"Cápsulas (10 un) {caps}" if caps else None,
                  f"Drip (10 sachês) {drip}" if drip else None])
    if cd:
        linhas.append(f"☕ {cd}")

    moedor = _juntar([
        f"Moedor profissional {p['Moedor Elétrico Profissional — Unitário']}" if "Moedor Elétrico Profissional — Unitário" in p else None,
        f"Moedor + 10 granel {p['Moedor + 10 pacotes granel']}" if "Moedor + 10 pacotes granel" in p else None,
    ])
    if moedor:
        linhas.append(f"⚙️ {moedor}")
    return linhas


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
