"""Cria (ou devolve, se já existir) o dataset da Meta ligado ao WABA — passo único.

A CAPI for Business Messaging exige um dataset associado ao WABA. Doc (POST cria, GET consulta; permissões whatsapp_business_management e
whatsapp_business_manage_events):
https://developers.facebook.com/docs/marketing-api/conversions-api/business-messaging
Uso (container da API): python -m scripts.conversoes.criar_dataset_meta
Saída: o ID para pôr em META_CAPI_DATASET_ID.
"""
import os
import sys

import httpx


def main() -> None:
    waba = os.getenv("META_WABA_ID")
    token = os.getenv("META_CAPI_ACCESS_TOKEN")
    version = os.getenv("META_CAPI_API_VERSION") or "v25.0"
    if not waba or not token:
        sys.exit("defina META_WABA_ID e META_CAPI_ACCESS_TOKEN")
    url = f"https://graph.facebook.com/{version}/{waba}/dataset"
    with httpx.Client(timeout=20) as c:
        got = c.get(url, params={"access_token": token})
        if got.status_code == 200:
            existente = _extrair_id(got.json())
            if existente:
                print("dataset já existe:", existente)
                return
        resp = c.post(url, params={"access_token": token})
    resp.raise_for_status()
    print("dataset criado:", _extrair_id(resp.json()) or resp.json())


def _extrair_id(corpo: dict) -> str | None:
    """A doc fala em `dataset_id`; a Graph costuma devolver `id` ou `data: [{id}]`. Aceita os três."""
    itens = corpo.get("data")
    if isinstance(itens, list) and itens:
        corpo = itens[0]
    return corpo.get("dataset_id") or corpo.get("id")


if __name__ == "__main__":
    main()
