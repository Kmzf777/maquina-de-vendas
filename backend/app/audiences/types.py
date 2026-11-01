"""Tipos da sincronização diária dos públicos PL/Atacado (cartão 4e0494e0).

Os IDs dos públicos são fixos: o job só troca o conteúdo, nunca cria nem renomeia público.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Audience:
    key: str            # meta_pl | meta_atacado | google_pl | google_atacado
    platform: str       # meta | google
    segment: str        # pl | atacado
    audience_id: str


AUDIENCES = (
    Audience("meta_pl", "meta", "pl", "120252789539440163"),
    Audience("meta_atacado", "meta", "atacado", "120252789580640163"),
    Audience("google_pl", "google", "pl", "9496018532"),
    Audience("google_atacado", "google", "atacado", "9496602202"),
)


@dataclass
class Fatos:
    """Uma linha de `audience_sync_facts()`: um comprador com venda `registrada`."""
    lead_id: str
    ultima_compra: datetime
    receita_365: float
    nome: str | None
    lead_phone: str | None
    lead_email: str | None
    pipeline_pl: bool = False
    pipeline_atacado: bool = False
    tag_pl: bool = False
    tag_atacado: bool = False
    fotolito: bool = False
    produto_pl: bool = False
    segmento: str | None = None
    docs: list[str] = field(default_factory=list)
    fones_bling: list[str] = field(default_factory=list)   # celular_e164 e telefone_e164
    emails_bling: list[str] = field(default_factory=list)
    contatos_bling: list[tuple[str, int]] = field(default_factory=list)  # (account, id)

    @classmethod
    def from_row(cls, r: dict[str, Any]) -> "Fatos":
        return cls(
            lead_id=str(r["lead_id"]),
            ultima_compra=datetime.fromisoformat(str(r["ultima_compra"]).replace("Z", "+00:00")),
            receita_365=float(r.get("receita_365") or 0),
            nome=r.get("nome"),
            lead_phone=r.get("lead_phone"),
            lead_email=r.get("lead_email"),
            pipeline_pl=bool(r.get("pipeline_pl")),
            pipeline_atacado=bool(r.get("pipeline_atacado")),
            tag_pl=bool(r.get("tag_pl")),
            tag_atacado=bool(r.get("tag_atacado")),
            fotolito=bool(r.get("fotolito")),
            produto_pl=bool(r.get("produto_pl")),
            segmento=r.get("segmento"),
            docs=list(r.get("docs") or []),
            fones_bling=list(r.get("fones_bling") or []),
            emails_bling=list(r.get("emails_bling") or []),
            contatos_bling=[(c["account"], int(c["id"])) for c in (r.get("contatos_bling") or [])],
        )


@dataclass
class Detalhe:
    """Linha de `audience_contact_details`: o que só o GET /contatos/{id} do Bling traz."""
    email: str | None = None
    municipio: str | None = None
    uf: str | None = None
    cep: str | None = None


@dataclass
class Pessoa:
    lead_id: str
    pl: bool
    atacado: bool
    celulares: list[str]      # "55DDD9XXXXXXXX", distintos
    emails: list[str]         # minúsculo, sem espaços, distintos
    nome: str | None
    sobrenome: str | None
    cidade: str | None
    uf: str | None
    cep: str | None           # 8 dígitos
    valor: float              # receita dos últimos 365 dias, BRL
