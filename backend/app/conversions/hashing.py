# backend/app/conversions/hashing.py
"""Normalização + SHA-256 dos identificadores de usuário.

Meta e Google normalizam DIFERENTE e um hash de formato errado simplesmente não casa (sem
erro nenhum): a Meta quer o telefone só com dígitos e DDI (`5534...`); o Google quer E.164 com
`+` (`+5534...`) e o e-mail do Gmail sem os pontos antes do `@`.
"""
import hashlib
import re

_NAO_DIGITO = re.compile(r"\D+")
_GMAIL = ("gmail.com", "googlemail.com")


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def normalize_br_phone(phone: str | None) -> str | None:
    """Dígitos com DDI 55. Aceita máscara, '+', zero de tronco. Menos de 10 dígitos → None."""
    if not phone:
        return None
    d = _NAO_DIGITO.sub("", phone).lstrip("0")
    if len(d) < 10:
        return None
    if not d.startswith("55") or len(d) <= 11:
        d = "55" + d
    return d


def _normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    e = email.strip().lower()
    if "@" not in e or e.startswith("@") or e.endswith("@"):
        return None
    return e


def meta_phone_hash(phone: str | None) -> str | None:
    d = normalize_br_phone(phone)
    return _sha256(d) if d else None


def google_phone_hash(phone: str | None) -> str | None:
    d = normalize_br_phone(phone)
    return _sha256("+" + d) if d else None


def meta_email_hash(email: str | None) -> str | None:
    e = _normalize_email(email)
    return _sha256(e) if e else None


def google_email_hash(email: str | None) -> str | None:
    e = _normalize_email(email)
    if not e:
        return None
    local, domain = e.split("@", 1)
    if domain in _GMAIL:
        local = local.replace(".", "")
    return _sha256(f"{local}@{domain}")
