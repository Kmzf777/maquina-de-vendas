"""Diff dos identificadores enviados a cada público (cartão 4e0494e0)."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def ident_hash(ident: dict[str, Any]) -> str:
    """sha256 do identificador em JSON canônico (chaves ordenadas, sem espaços)."""
    s = json.dumps(ident, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def diff_identificadores(antes: set[str], agora: set[str]) -> tuple[set[str], set[str]]:
    """Devolve `(entram, saem)`."""
    return agora - antes, antes - agora
