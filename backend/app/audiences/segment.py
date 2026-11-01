"""Regra de segmento PL/Atacado e montagem da pessoa (cartão 4e0494e0).

A classificação fica em Python porque `segmento` é null para a maioria: aqui
`None == "atacado"` é simplesmente `False`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.audiences import normalize as n
from app.audiences.types import Detalhe, Fatos, Pessoa

JANELA = timedelta(days=365)


def dentro_da_janela(f: Fatos, agora: datetime) -> bool:
    """Última compra há no máximo 365 dias (365 exatos ainda entra)."""
    return agora - f.ultima_compra <= JANELA


def classificar(f: Fatos) -> tuple[bool, bool]:
    """Devolve `(pl, atacado)`. CNPJ só vira Atacado para quem não caiu em nenhum."""
    pl = f.pipeline_pl or f.tag_pl or f.fotolito or f.produto_pl or f.segmento == "private_label"
    at = f.pipeline_atacado or f.tag_atacado or f.segmento == "atacado"
    if not pl and not at:
        at = any(len(d) == 14 for d in f.docs)
    return bool(pl), bool(at)


def _distintos(valores) -> list[str]:
    return list(dict.fromkeys(v for v in valores if v))


def montar_pessoa(f: Fatos, detalhes: dict[tuple[str, int], Detalhe]) -> Pessoa | None:
    """Pessoa normalizada, ou None se não for PL nem Atacado."""
    pl, at = classificar(f)
    if not pl and not at:
        return None
    dets = [detalhes[c] for c in f.contatos_bling if c in detalhes]
    celulares = _distintos(n.celular_br(t) for t in [f.lead_phone, *f.fones_bling])
    emails = _distintos(n.email(e) for e in [f.lead_email, *f.emails_bling, *(d.email for d in dets)])
    nome, sobrenome = n.nome_sobrenome(f.nome)
    end = next((d for d in dets if d.cep), None)
    return Pessoa(
        lead_id=f.lead_id,
        pl=pl,
        atacado=at,
        celulares=celulares,
        emails=emails,
        nome=nome,
        sobrenome=sobrenome,
        cidade=n.cidade(end.municipio) if end else None,
        uf=n.uf(end.uf) if end else None,
        cep=n.cep(end.cep) if end else None,
        valor=round(f.receita_365, 2),
    )
