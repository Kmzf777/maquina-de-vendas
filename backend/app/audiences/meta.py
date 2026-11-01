"""Troca do conteúdo dos públicos personalizados do Meta via `usersreplace` (cartão 4e0494e0).

`usersreplace` substitui a lista inteira numa sessão de lotes: o último lote (`last_batch_flag`)
fecha a troca. Com 0 pessoas manda 1 lote vazio: esvaziar é o certo quando ninguém se qualifica.

Token no header `Authorization`, nunca na URL nem em mensagem de erro: o httpx loga a URL em INFO.
"""
from __future__ import annotations

import json
import os
import random
from itertools import zip_longest
from typing import Any, Iterable

import httpx

from app.audiences.normalize import sha
from app.audiences.types import Pessoa
from app.conversions.hashing import meta_email_hash, meta_phone_hash

GRAPH = "https://graph.facebook.com"
SCHEMA = ["EMAIL", "PHONE", "FN", "LN", "CT", "ST", "ZIP", "COUNTRY", "LOOKALIKE_VALUE"]
MAX_ROWS = 10000
_TIMEOUT = 60.0
_CHECK_FIELDS = "name,operation_status,approximate_count_lower_bound,approximate_count_upper_bound,is_value_based"


def _version() -> str:
    return (os.getenv("META_AUDIENCES_API_VERSION") or "").strip() or "v25.0"


def _token() -> str:
    tok = (os.getenv("META_AUDIENCES_ACCESS_TOKEN") or "").strip()
    if not tok:
        raise RuntimeError("META_AUDIENCES_ACCESS_TOKEN não configurado")
    return tok


def build_rows(pessoas: Iterable[Pessoa]) -> list[list]:
    rows: list[list] = []
    for p in pessoas:
        fixos = [sha(p.nome), sha(p.sobrenome), sha(p.cidade), sha(p.uf), sha(p.cep), sha("br")]
        for e, c in zip_longest(p.emails, p.celulares):
            rows.append([meta_email_hash(e) or "", meta_phone_hash(c) or "", *fixos, p.valor])
    return rows


def build_batches(rows: list[list], session_id: int | str, max_rows: int = MAX_ROWS) -> list[dict]:
    pedacos = [rows[i:i + max_rows] for i in range(0, len(rows), max_rows)] or [[]]
    n = len(pedacos)
    return [
        {
            "payload": {"schema": SCHEMA, "data": dados},
            "session": {"session_id": session_id, "batch_seq": i, "last_batch_flag": i == n,
                        "estimated_num_total": len(rows)},
        }
        for i, dados in enumerate(pedacos, start=1)
    ]


def _error_message(resp: httpx.Response) -> str:
    try:
        err = (resp.json() or {}).get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else None
    except ValueError:
        msg = None
    return f"Meta HTTP {resp.status_code}: {msg or resp.text[:300]}"


def _raise_if_error(resp: httpx.Response, token: str) -> None:
    if resp.status_code != 200:
        raise RuntimeError(_error_message(resp).replace(token, "***"))


def replace(audience_id: str, pessoas: Iterable[Pessoa], *, transport: httpx.BaseTransport | None = None,
            session_id: int | None = None) -> dict[str, Any]:
    token = _token()
    if session_id is None:
        session_id = random.randint(1, 2**62)
    rows = build_rows(pessoas)
    lotes = build_batches(rows, session_id, max_rows=MAX_ROWS)
    url = f"{GRAPH}/{_version()}/{audience_id}/usersreplace"
    headers = {"Authorization": f"Bearer {token}"}
    respostas: list[dict] = []
    with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
        for lote in lotes:
            try:
                resp = client.post(url, headers=headers, data={
                    "payload": json.dumps(lote["payload"]),
                    "session": json.dumps(lote["session"]),
                })
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Meta rede: {type(exc).__name__}".replace(token, "***")) from None
            _raise_if_error(resp, token)
            try:
                body = resp.json()
            except ValueError:
                body = {"raw": resp.text[:500]}
            respostas.append(body if isinstance(body, dict) else {"raw": body})
    return {
        "session_id": session_id,
        "lotes": len(lotes),
        "linhas": len(rows),
        "num_received": sum(int(r.get("num_received") or 0) for r in respostas),
        "num_invalid_entries": sum(int(r.get("num_invalid_entries") or 0) for r in respostas),
        "respostas": respostas,
    }


def check_audience(audience_id: str, *, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    token = _token()
    url = f"{GRAPH}/{_version()}/{audience_id}"
    with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
        try:
            resp = client.get(url, params={"fields": _CHECK_FIELDS},
                              headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Meta rede: {type(exc).__name__}") from None
    _raise_if_error(resp, token)
    return resp.json()
