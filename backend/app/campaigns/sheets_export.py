"""Escreve 1 linha por evento de conversão numa Planilha Google (Data Manager / Make importam).

Env-gated e fail-soft: sem GOOGLE_SHEETS_CONV_ID / credencial de service account, é no-op
logado. A planilha é a ponte p/ o Google (evita dev-token do Google Ads API). O service
account precisa estar COMPARTILHADO como editor na planilha alvo.
"""
import json
import logging
import os
from typing import Any

from app.campaigns.capi_dispatcher import hash_phone

logger = logging.getLogger(__name__)

_SHEET_RANGE = "A:I"

# canônico → (conversion_name p/ Google Ads, status_funil legível)
_CONVERSION_NAMES = {
    "lead": ("Lead_Captado", "Lead_captado"),
    "qualified": ("Lead_Qualificado", "qualificado"),
    "opportunity": ("Oportunidade_Criada", "oportunidade"),
    "purchase": ("Venda_Fechada", "vendido"),
}


def build_sheet_row(lead: dict[str, Any], event: str, value: float | None,
                    currency: str, when: str) -> list[Any]:
    """Monta a linha na ordem-contrato do doc (9 colunas)."""
    conversion_name, status_funil = _CONVERSION_NAMES.get(event, (event, event))
    return [
        lead.get("name") or "",
        lead.get("gclid") or "",
        lead.get("email") or "",
        hash_phone(lead.get("wa_id") or lead.get("phone")) or "",
        conversion_name,
        when,
        currency,
        value,
        status_funil,
    ]


def _build_service():  # pragma: no cover - I/O real, mockado nos testes
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds_json = os.environ["GOOGLE_SA_JSON"]
    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def append_conversion_row(row: list[Any]) -> dict[str, Any]:
    """Append da linha na planilha. Fail-soft. Retorna {"synced": bool, "reason"?: str}."""
    sheet_id = os.environ.get("GOOGLE_SHEETS_CONV_ID")
    if not sheet_id or not os.environ.get("GOOGLE_SA_JSON"):
        logger.info("[SHEETS] Sem GOOGLE_SHEETS_CONV_ID/GOOGLE_SA_JSON — append ignorado")
        return {"synced": False, "reason": "no_config"}
    try:
        service = _build_service()
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id, range=_SHEET_RANGE,
            valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        logger.info("[SHEETS] Linha de conversão anexada (%s)", row[4] if len(row) > 4 else "?")
        return {"synced": True}
    except Exception as exc:
        logger.error("[SHEETS] Falha ao anexar linha: %s", exc, exc_info=True)
        return {"synced": False, "reason": "http_error", "error": str(exc)}
