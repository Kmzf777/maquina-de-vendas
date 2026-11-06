"""Lead que chega pelo botão de WhatsApp do anúncio Google ("Iniciar conversa") e retorno sem anúncio.

O Google não manda gclid nem UTM para o WhatsApp: a única pista é o texto pronto do botão,
"Olá, encontrei vocês pelo Google e gostaria de obter mais informações.". Quem chega com ele
é marcado como Google Ads pago (utm_source=google + utm_medium=cpc — o que derive_channel e o
lead-origin.ts do CRM já entendem como Google Ads). O texto não identifica a campanha: no lugar
dela vai o rótulo "WhatsApp do Google" em utm_campaign, que o CRM mostra como detalhe da origem e
o /trafego agrupa em "(não atribuído) · WhatsApp do Google".

F5 (cartão B, 06/11/2026) — os toques que se perdiam:
  1a. O texto do Google SEMPRE vira um toque `entrada` na linha do tempo, inclusive para quem já
      tem origem (quem veio do Meta e voltou pela busca da marca no Google: o caso da Tati). As
      colunas do lead continuam só sendo carimbadas quando ele não tem origem. Dedupe por lead e
      dia. Quando as colunas são carimbadas, quem grava o toque é o gatilho de `leads` (ele funde
      a entrada automática "WhatsApp direto" do cadastro, cartão B item 1c).
  1b. Retorno sem anúncio: lead que já existe e escreve depois de RETORNO_DIAS ou mais sem
      conversa, sem referral de anúncio e sem texto pronto, ganha um toque "WhatsApp direto" com
      metadata.retorno = true. É assim que a busca orgânica pela marca aparece.
  Os toques não levam click id: conversions/eligibility.py só cria clique de entrada com
  gclid/ctwa_clid/…, então nada disso vai para a fila de `ad_conversions`.

Cartão C item 3: `TEXTOS_PRONTOS` é a tabela genérica texto → canal/campanha. Hoje só tem o
texto do Google; o texto pronto dos sites (wa.me "Olá, vim pelo site do atacado") entra aqui.
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.leads.service import update_lead

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("America/Sao_Paulo")

# Dias sem conversa para a mensagem sem anúncio contar como um toque novo (cartão B item 1b).
RETORNO_DIAS = 7

GOOGLE_ASSET_TRACKING: dict[str, str] = {
    "utm_source": "google", "utm_medium": "cpc", "utm_campaign": "WhatsApp do Google",
}

# Tabela texto pronto → canal/campanha. `trecho` já normalizado (minúsculas, sem acento, espaços
# colapsados). `tracking` são as colunas carimbadas no lead SEM origem; `canal`/`campanha` vão no
# toque da linha do tempo. Para um texto novo (site, QR code), acrescente uma linha.
TEXTOS_PRONTOS: tuple[dict[str, Any], ...] = (
    {"trecho": "encontrei voces pelo google", "canal": "Google Ads",
     "campanha": "WhatsApp do Google", "source": "google_message_asset",
     "tracking": GOOGLE_ASSET_TRACKING},
)

# Qualquer uma preenchida = o lead já tem origem; o carimbo não sobrescreve.
_ATTRIBUTION_COLUMNS: tuple[str, ...] = (
    "gclid", "fbclid", "ctwa_clid", "meta_ad_id", "utm_source", "utm_medium", "utm_campaign",
)


def _normalize(text: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def reconhecer_texto_pronto(text: str | None) -> dict[str, Any] | None:
    """A linha de TEXTOS_PRONTOS cujo trecho aparece em `text`, ou None. Puro."""
    if not text:
        return None
    norm = _normalize(text)
    for linha in TEXTOS_PRONTOS:
        if linha["trecho"] in norm:
            return linha
    return None


def google_message_asset_tracking(text: str | None) -> dict[str, str] | None:
    """Tracking de Google Ads se `text` for o texto pronto do botão; senão None."""
    linha = reconhecer_texto_pronto(text)
    if not linha or linha["source"] != "google_message_asset":
        return None
    return dict(linha["tracking"])


def has_attribution(lead: dict[str, Any]) -> bool:
    return any(str(lead.get(col) or "").strip() for col in _ATTRIBUTION_COLUMNS)


def _dia_local(agora: datetime) -> str:
    return agora.astimezone(_TZ).date().isoformat()


def _inicio_do_dia(agora: datetime) -> str:
    local = agora.astimezone(_TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def evento_toque_texto_pronto(lead_id: str, linha: dict[str, Any], agora: datetime) -> dict[str, Any]:
    """Linha de `lead_events` do toque do texto pronto. Sem click id, de propósito. Puro."""
    tracking = linha.get("tracking") or {}
    return {
        "lead_id": lead_id,
        "event_type": "entrada",
        "new_value": linha["canal"],
        "occurred_at": agora.isoformat(),
        "source": linha["source"],
        "dedupe_key": f"entrada:{linha['source']}:{lead_id}:{_dia_local(agora)}",
        "metadata": {"canal": linha["canal"], "campanha_nome": linha["campanha"],
                     "texto_pronto": True, **tracking},
    }


def evento_retorno(lead_id: str, agora: datetime, dias: int | None) -> dict[str, Any]:
    """Linha de `lead_events` do retorno sem anúncio ("WhatsApp direto"). Puro."""
    return {
        "lead_id": lead_id,
        "event_type": "entrada",
        "new_value": "WhatsApp direto",
        "occurred_at": agora.isoformat(),
        "source": "retorno",
        "dedupe_key": f"entrada:retorno:{lead_id}:{_dia_local(agora)}",
        "metadata": {"canal": "WhatsApp direto", "retorno": True, "dias_sem_conversa": dias},
    }


def _sb():
    from app.db.supabase import get_supabase
    return get_supabase()


def _gravar_entrada(evento: dict[str, Any]) -> bool:
    """Insere o toque. A repetição esbarra no índice único de dedupe_key e conta como já gravado."""
    try:
        _sb().table("lead_events").insert(evento).execute()
    except Exception as exc:
        if "dedupe_key" in str(exc) or "duplicate key" in str(exc) or "23505" in str(exc):
            return False
        logger.warning("toque %s do lead %s não gravado: %s", evento.get("source"),
                       evento.get("lead_id"), exc)
        return False
    return True


def _ja_tem_toque_hoje(lead_id: str, canal: str, agora: datetime) -> bool:
    """Já existe entrada deste canal hoje (a do gatilho não usa a nossa dedupe_key)?"""
    try:
        rows = (_sb().table("lead_events").select("id").eq("lead_id", lead_id)
                .eq("event_type", "entrada").eq("new_value", canal)
                .gte("occurred_at", _inicio_do_dia(agora)).limit(1).execute().data)
    except Exception as exc:
        logger.warning("google_message_asset: não deu para conferir o toque de hoje (%s): %s", lead_id, exc)
        return False
    return bool(rows)


def registrar_toque_texto_pronto(lead: dict[str, Any] | None, text: str | None,
                                 agora: datetime | None = None) -> bool:
    """Grava o toque do texto pronto para o lead que JÁ tem origem. Fail-soft. True se gravou."""
    linha = reconhecer_texto_pronto(text)
    if not lead or not lead.get("id") or not linha:
        return False
    agora = agora or datetime.now(timezone.utc)
    if _ja_tem_toque_hoje(lead["id"], linha["canal"], agora):
        return False
    gravou = _gravar_entrada(evento_toque_texto_pronto(lead["id"], linha, agora))
    if gravou:
        logger.info("google_message_asset: toque %s gravado para o lead %s", linha["canal"], lead["id"])
    return gravou


def stamp_google_message_asset(lead: dict[str, Any] | None, text: str | None) -> bool:
    """Lead que mandou o texto do botão do Google. Fail-soft.

    Sem origem: carimba Google Ads nas colunas (o gatilho grava o toque). Com origem: as colunas
    ficam, e o toque vai direto para a linha do tempo (F5). Retorna True se carimbou as colunas."""
    if not lead or not lead.get("id"):
        return False
    tracking = google_message_asset_tracking(text)
    if not tracking:
        return False
    if has_attribution(lead):
        registrar_toque_texto_pronto(lead, text)
        return False
    try:
        update_lead(lead["id"], **tracking, traffic_type="paid")
    except Exception as exc:
        logger.warning("google_message_asset: falha ao carimbar lead %s: %s", lead.get("id"), exc)
        return False
    logger.info("google_message_asset: lead %s marcado como Google Ads (botao WhatsApp)", lead["id"])
    return True


def _ts(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not isinstance(v, str) or not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def dias_sem_conversa(lead: dict[str, Any], ultima_conversa: Any, agora: datetime) -> float | None:
    """Dias desde a última mensagem (de qualquer lado) ou, sem conversa nenhuma, desde o cadastro.
    None = sem data nenhuma. Puro."""
    marcos = [t for t in (_ts(lead.get("last_customer_message_at")), _ts(ultima_conversa)) if t]
    ref = max(marcos) if marcos else _ts(lead.get("created_at"))
    if ref is None:
        return None
    return (agora - ref).total_seconds() / 86400


def e_retorno(lead: dict[str, Any], text: str | None, *, tem_referral: bool,
              ultima_conversa: Any, agora: datetime) -> bool:
    """Regra do cartão B item 1b. Puro."""
    if tem_referral or reconhecer_texto_pronto(text):
        return False
    dias = dias_sem_conversa(lead, ultima_conversa, agora)
    return dias is not None and dias >= RETORNO_DIAS


def _ultima_conversa(lead_id: str) -> str | None:
    rows = (_sb().table("conversations").select("last_msg_at").eq("lead_id", lead_id)
            .order("last_msg_at", desc=True).limit(1).execute().data) or []
    return (rows[0] or {}).get("last_msg_at") if rows else None


def registrar_retorno(lead: dict[str, Any] | None, text: str | None, *, tem_referral: bool,
                      agora: datetime | None = None) -> bool:
    """Grava o toque "WhatsApp direto" (retorno) quando a regra pede. Fail-soft. True se gravou.

    Roda no _register_lead do webhook ANTES de last_customer_message_at e da conversa serem
    atualizados pela mensagem atual: o que se lê ali é a mensagem anterior. Lead recém-criado tem
    created_at de agora e não passa na regra."""
    if not lead or not lead.get("id") or tem_referral or reconhecer_texto_pronto(text):
        return False
    agora = agora or datetime.now(timezone.utc)
    try:
        ultima = _ultima_conversa(lead["id"])
        if not e_retorno(lead, text, tem_referral=tem_referral, ultima_conversa=ultima, agora=agora):
            return False
        dias = dias_sem_conversa(lead, ultima, agora)
        gravou = _gravar_entrada(evento_retorno(lead["id"], agora, int(dias) if dias is not None else None))
    except Exception as exc:
        logger.warning("retorno: falha ao avaliar o lead %s: %s", lead.get("id"), exc)
        return False
    if gravou:
        logger.info("retorno: lead %s voltou depois de %s dias sem conversa", lead["id"], int(dias or 0))
    return gravou
