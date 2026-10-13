"""Lead que chega pelo botão de WhatsApp do anúncio Google ("Iniciar conversa").

O Google não manda gclid nem UTM para o WhatsApp: a única pista é o texto pronto do botão,
"Olá, encontrei vocês pelo Google e gostaria de obter mais informações.". Quem chega com ele
é marcado como Google Ads pago (utm_source=google + utm_medium=cpc — o que derive_channel e o
lead-origin.ts do CRM já entendem como Google Ads). Sem campanha: o texto não a identifica.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any

from app.leads.service import update_lead

logger = logging.getLogger(__name__)

# Trecho do texto pronto, já normalizado (minúsculas, sem acento, espaços colapsados).
_MARCA = "encontrei voces pelo google"

GOOGLE_ASSET_TRACKING: dict[str, str] = {"utm_source": "google", "utm_medium": "cpc"}

# Qualquer uma preenchida = o lead já tem origem; o carimbo não sobrescreve.
_ATTRIBUTION_COLUMNS: tuple[str, ...] = (
    "gclid", "fbclid", "ctwa_clid", "meta_ad_id", "utm_source", "utm_medium", "utm_campaign",
)


def _normalize(text: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def google_message_asset_tracking(text: str | None) -> dict[str, str] | None:
    """Tracking de Google Ads se `text` for o texto pronto do botão; senão None."""
    if not text or _MARCA not in _normalize(text):
        return None
    return dict(GOOGLE_ASSET_TRACKING)


def has_attribution(lead: dict[str, Any]) -> bool:
    return any(str(lead.get(col) or "").strip() for col in _ATTRIBUTION_COLUMNS)


def stamp_google_message_asset(lead: dict[str, Any] | None, text: str | None) -> bool:
    """Carimba Google Ads no lead sem origem que mandou o texto do botão. Fail-soft.

    Retorna True se gravou."""
    if not lead or not lead.get("id"):
        return False
    tracking = google_message_asset_tracking(text)
    if not tracking or has_attribution(lead):
        return False
    try:
        update_lead(lead["id"], **tracking, traffic_type="paid")
    except Exception as exc:
        logger.warning("google_message_asset: falha ao carimbar lead %s: %s", lead.get("id"), exc)
        return False
    logger.info("google_message_asset: lead %s marcado como Google Ads (botao WhatsApp)", lead["id"])
    return True
