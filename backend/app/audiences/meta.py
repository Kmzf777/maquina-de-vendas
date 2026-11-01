"""Acrescenta e remove pessoas nos públicos personalizados do Meta (cartão 4e0494e0).

Sem `usersreplace` de propósito (ajuste de 01/11): substituir derrubaria os públicos em uso de
~1.000 pessoas (o que a Tati subiu à mão) para 78 no PL e prejudicaria a entrega das campanhas.
`POST /users` só acrescenta; `DELETE /users` tira só as linhas que este job enviou e saíram.

Token no header `Authorization`, nunca na URL nem em mensagem de erro: o httpx loga a URL em INFO.
"""
from __future__ import annotations

import json
import os
from itertools import zip_longest
from typing import Any, Iterable

import httpx

from app.audiences.normalize import sha
from app.audiences.types import Pessoa
from app.conversions.hashing import meta_email_hash, meta_phone_hash

GRAPH = "https://graph.facebook.com"
SCHEMA = ["EMAIL", "PHONE", "FN", "LN", "CT", "ST", "ZIP", "COUNTRY", "LOOKALIKE_VALUE"]
SCHEMA_ID = SCHEMA[:-1]  # a remoção casa pela pessoa, sem o valor (que muda todo dia)
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


def identidade(row: list) -> list:
    """A linha sem o `LOOKALIKE_VALUE`: é o que identifica a pessoa para diff e remoção."""
    return row[:-1]


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


def _enviar(method: str, audience_id: str, schema: list[str], rows: list[list], *,
            transport: httpx.BaseTransport | None) -> dict[str, Any]:
    token = _token()
    pedacos = [rows[i:i + MAX_ROWS] for i in range(0, len(rows), MAX_ROWS)]
    url = f"{GRAPH}/{_version()}/{audience_id}/users"
    headers = {"Authorization": f"Bearer {token}"}
    respostas: list[dict] = []
    if pedacos:
        with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
            for dados in pedacos:
                try:
                    resp = client.request(method, url, headers=headers, data={
                        "payload": json.dumps({"schema": schema, "data": dados})})
                except httpx.HTTPError as exc:
                    raise RuntimeError(f"Meta rede: {type(exc).__name__}") from None
                _raise_if_error(resp, token)
                try:
                    body = resp.json()
                except ValueError:
                    body = {"raw": resp.text[:500]}
                respostas.append(body if isinstance(body, dict) else {"raw": body})
    return {
        "lotes": len(pedacos),
        "linhas": len(rows),
        "num_received": sum(int(r.get("num_received") or 0) for r in respostas),
        "num_invalid_entries": sum(int(r.get("num_invalid_entries") or 0) for r in respostas),
        "respostas": respostas,
    }


def add_users(audience_id: str, rows: list[list], *,
              transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    return _enviar("POST", audience_id, SCHEMA, rows, transport=transport)


def remove_users(audience_id: str, identidades: list[list], *,
                 transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    return _enviar("DELETE", audience_id, SCHEMA_ID, identidades, transport=transport)


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
