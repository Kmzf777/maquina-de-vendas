"""Públicos do Google pela Data Manager API: `audienceMembers:ingest` e `:remove` (cartão 4e0494e0).

A API não tem "substituir": o job manda todos os atuais no ingest e remove só os identificadores
que saíram (o diff é por identificador). O OAuth reaproveita o cache de `app.conversions.google`.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from app.audiences.normalize import sha
from app.audiences.types import Pessoa
from app.conversions.google import _access_token, _reset_token_cache
from app.conversions.hashing import google_email_hash, google_phone_hash

INGEST_URL = "https://datamanager.googleapis.com/v1/audienceMembers:ingest"
REMOVE_URL = "https://datamanager.googleapis.com/v1/audienceMembers:remove"
MAX_IDENTIFICADORES = 10
MAX_MEMBROS = 10_000
_TIMEOUT = 60.0


def _digits(v: str | None) -> str:
    return "".join(ch for ch in (v or "") if ch.isdigit())


def identificadores(p: Pessoa) -> list[dict[str, Any]]:
    """E-mails, celulares e endereço (se tiver nome, sobrenome e CEP), no máximo 10."""
    ids: list[dict[str, Any]] = []
    for e in p.emails:
        h = google_email_hash(e)
        if h:
            ids.append({"emailAddress": h})
    for c in p.celulares:
        h = google_phone_hash(c)
        if h:
            ids.append({"phoneNumber": h})
    if p.nome and p.sobrenome and p.cep:
        ids.append({"address": {"givenName": sha(p.nome), "familyName": sha(p.sobrenome),
                                "regionCode": "BR", "postalCode": p.cep}})
    return ids[:MAX_IDENTIFICADORES]


def build_member(p: Pessoa) -> dict[str, Any]:
    return {"userData": {"userIdentifiers": identificadores(p)}}


def remove_member(ident: dict[str, Any]) -> dict[str, Any]:
    return {"userData": {"userIdentifiers": [ident]}}


def build_body(audience_id: str, members: list[dict[str, Any]], *, validate_only: bool,
               operacao: str = "ingest") -> dict[str, Any]:
    customer = _digits(os.getenv("GOOGLE_ADS_CUSTOMER_ID"))
    login = _digits(os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID"))
    dest: dict[str, Any] = {
        "operatingAccount": {"accountType": "GOOGLE_ADS", "accountId": customer},
        "productDestinationId": str(audience_id),
    }
    if login and login != customer:
        dest["loginAccount"] = {"accountType": "GOOGLE_ADS", "accountId": login}
    body: dict[str, Any] = {
        "destinations": [dest],
        "audienceMembers": members,
        "encoding": "HEX",
        "validateOnly": bool(validate_only),
    }
    if operacao == "ingest":
        # Brasil não é EEE; a base legal (LGPD) está na política de privacidade.
        body["consent"] = {"adUserData": "CONSENT_GRANTED", "adPersonalization": "CONSENT_GRANTED"}
        body["termsOfService"] = {"customerMatchTermsOfServiceStatus": "ACCEPTED"}
    return body


def _mensagem(resp: httpx.Response) -> str:
    try:
        err = (resp.json() or {}).get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except ValueError:
        msg = None
    return f"HTTP {resp.status_code}: {msg or resp.text[:300]}"


def _enviar(url: str, operacao: str, audience_id: str, members: list[dict[str, Any]], *,
            validate_only: bool, transport: httpx.BaseTransport | None) -> list[dict[str, Any]]:
    if not members:
        return []
    respostas: list[dict[str, Any]] = []
    with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
        token, erro, _auth = _access_token(client)
        if not token:
            raise RuntimeError(erro or "falha ao obter access token do Google")
        for i in range(0, len(members), MAX_MEMBROS):
            body = build_body(audience_id, members[i:i + MAX_MEMBROS], validate_only=validate_only,
                              operacao=operacao)
            resp = client.post(url, headers={"Authorization": f"Bearer {token}"}, json=body)
            if resp.status_code != 200:
                if resp.status_code == 401:
                    _reset_token_cache()  # token revogado: a próxima rodada pede outro
                raise RuntimeError(_mensagem(resp))
            try:
                data = resp.json()
            except ValueError:
                data = {"raw": resp.text[:500]}
            respostas.append(data if isinstance(data, dict) else {"raw": data})
    return respostas


def ingest(audience_id: str, members: list[dict[str, Any]], *, validate_only: bool,
           transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    return _enviar(INGEST_URL, "ingest", audience_id, members, validate_only=validate_only,
                   transport=transport)


def remove(audience_id: str, members: list[dict[str, Any]], *, validate_only: bool,
           transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    return _enviar(REMOVE_URL, "remove", audience_id, members, validate_only=validate_only,
                   transport=transport)
