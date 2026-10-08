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


def _erro(resp: httpx.Response) -> str:
    """Status + mensagem da Graph. Sem `raise_for_status()`: a mensagem dele traz a URL."""
    try:
        msg = (resp.json().get("error") or {}).get("message")
    except (ValueError, AttributeError):
        msg = None
    return f"HTTP {resp.status_code}: {msg or resp.text[:300]}"


def main() -> None:
    waba = (os.getenv("META_WABA_ID") or "").strip()
    token = (os.getenv("META_CAPI_ACCESS_TOKEN") or "").strip()
    version = (os.getenv("META_CAPI_API_VERSION") or "").strip() or "v25.0"
    if not waba or not token:
        sys.exit("defina META_WABA_ID e META_CAPI_ACCESS_TOKEN")
    url = f"https://graph.facebook.com/{version}/{waba}/dataset"
    # Token só no header: na query ele aparece no log do httpx e nas mensagens de erro.
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=20, headers=headers) as c:
            got = c.get(url)
            if got.status_code == 200:
                existente = _extrair_id(got.json())
                if existente:
                    print("dataset já existe:", existente)
                    return
            resp = c.post(url)
    except httpx.HTTPError as exc:
        sys.exit(f"falha de rede ao falar com a Meta: {type(exc).__name__}")
    if resp.status_code != 200:
        sys.exit(f"a Meta recusou a criação do dataset — {_erro(resp)}")
    print("dataset criado:", _extrair_id(resp.json()) or resp.json())


def _extrair_id(corpo: dict) -> str | None:
    """A doc fala em `dataset_id`; a Graph costuma devolver `id` ou `data: [{id}]`. Aceita os três."""
    itens = corpo.get("data")
    if isinstance(itens, list) and itens:
        corpo = itens[0]
    return corpo.get("dataset_id") or corpo.get("id")


if __name__ == "__main__":
    main()
