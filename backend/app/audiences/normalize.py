"""Normalização dos campos de pessoa para Meta e Google (cartão 4e0494e0).

Telefone e e-mail reaproveitam `app.conversions.hashing`. Aqui só entra celular: fixo nunca
vira identificador, e quem decide é o número (55 + DDD + 9 + 8 dígitos), não o campo do Bling.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from app.conversions.hashing import normalize_br_phone

_NAO_ALFANUM = re.compile(r"[^a-z0-9 ]+")
_ESPACOS = re.compile(r"\s+")


def sha(s: str | None) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest() if s else ""


def celular_br(raw: str | None) -> str | None:
    d = normalize_br_phone(raw)  # já põe o 9 no celular antigo de 12 dígitos
    return d if d and len(d) == 13 and d[4] == "9" else None


def email(raw: str | None) -> str | None:
    if not raw:
        return None
    e = _ESPACOS.sub("", raw).lower()
    local, arroba, dominio = e.partition("@")
    return e if local and arroba and dominio else None


def texto(raw: str | None) -> str:
    """Sem acento, minúsculo, só letras/dígitos/espaço. Pontuação some sem virar espaço."""
    s = unicodedata.normalize("NFKD", raw or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return _ESPACOS.sub(" ", _NAO_ALFANUM.sub("", s)).strip()


def nome_sobrenome(raw: str | None) -> tuple[str | None, str | None]:
    partes = texto(raw).split()
    if not partes:
        return None, None
    return partes[0], (partes[-1] if len(partes) > 1 else None)


def cidade(raw: str | None) -> str | None:
    return texto(raw).replace(" ", "") or None


def uf(raw: str | None) -> str | None:
    u = texto(raw).replace(" ", "")
    return u if len(u) == 2 and u.isalpha() else None


def cep(raw: str | None) -> str | None:
    d = "".join(ch for ch in (raw or "") if ch.isdigit())
    return d if len(d) == 8 else None
