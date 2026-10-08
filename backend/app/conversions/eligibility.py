# backend/app/conversions/eligibility.py
"""Regras de elegibilidade — funções puras, sem I/O.

O "clique atribuído" de um evento é a entrada mais recente do lead, da mesma plataforma, que
aconteceu ANTES do evento e dentro da janela. `leads.ctwa_clid` é sobrescrito a cada clique
novo, então a fonte do histórico é a linha do tempo (`lead_events` tipo `entrada`).
"""
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# Meta: janela de atribuição padrão por clique (7 dias) — e a CAPI recusa event_time > 7 dias.
# Google: clique importável até 90 dias.
WINDOW = {"meta": timedelta(days=7), "google": timedelta(days=90)}
CLICK_TYPES = {"meta": ("ctwa_clid",), "google": ("gclid", "gbraid", "wbraid")}
_PLATFORM_OF = {t: p for p, ts in CLICK_TYPES.items() for t in ts}

# Repasses que NÃO são qualificação: o fallback de LLM fora do ar repassa todo mundo, o bot de
# Recuperação trabalha a base própria (não é tráfego pago) e escalonamento é reclamação.
_MOTIVOS_EXCLUIDOS = ("ia temporariamente indisponível", "bot de recuperação", "escalonamento")

SEGMENTOS = ("atacado", "private_label")


@dataclass(frozen=True)
class Click:
    platform: str
    click_id: str
    click_id_type: str
    click_at: datetime
    campaign_name: str | None


def parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _txt(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def clicks_from_entradas(entradas: list[dict[str, Any]]) -> list[Click]:
    """Uma entrada pode ter mais de um ID (raro); cada ID vira um Click."""
    out: list[Click] = []
    for e in entradas:
        at = parse_ts(e.get("occurred_at"))
        meta = e.get("metadata") or {}
        if at is None:
            continue
        # Nome da campanha: o resolvido pelo anúncio Meta (`campanha_nome`); sem ele (Google, ou
        # anúncio Meta ainda não sincronizado), o `utm_campaign` cru da entrada.
        campanha = _txt(meta.get("campanha_nome")) or _txt(meta.get("utm_campaign")) or None
        for ctype, platform in _PLATFORM_OF.items():
            cid = (meta.get(ctype) or "").strip()
            if cid:
                out.append(Click(platform, cid, ctype, at, campanha))
    return out


def clicks_from_lead_fallback(lead: dict[str, Any], known: list[Click]) -> list[Click]:
    """Lead com ID de clique que nunca virou entrada (4 de 699 no Google em 08/10/2026):
    usa `created_at` como hora do clique."""
    known_ids = {c.click_id for c in known}
    at = parse_ts(lead.get("created_at"))
    if at is None:
        return []
    out = []
    for ctype, platform in _PLATFORM_OF.items():
        cid = (lead.get(ctype) or "").strip()
        if cid and cid not in known_ids:
            out.append(Click(platform, cid, ctype, at, None))
    return out


def attributed_click(clicks: list[Click], platform: str, event_at: datetime) -> Click | None:
    window = WINDOW[platform]
    cands = [c for c in clicks
             if c.platform == platform and c.click_at <= event_at and event_at - c.click_at <= window]
    return max(cands, key=lambda c: c.click_at) if cands else None


def segment_for(lead_stage: str | None) -> str:
    return lead_stage if lead_stage in SEGMENTOS else "geral"


def qualified_handoff_ok(handoff: dict[str, Any] | None) -> bool:
    if not handoff or not parse_ts(handoff.get("at")):
        return False
    motivo = (handoff.get("motivo") or "").strip().lower()
    return not motivo.startswith(_MOTIVOS_EXCLUIDOS)


def stage_allowed(stage: str, ja_era_cliente: bool | None) -> bool:
    """Quem já era cliente só gera venda: lead/qualificado dele ensinariam o algoritmo a
    buscar a base atual. NULL = o sistema não sabe → trata como novo."""
    return stage == "purchase" or ja_era_cliente is not True


def build_dedupe_key(platform: str, stage: str, click_id: str, sale_id: str | None) -> str:
    if stage == "purchase":
        return f"{platform}:purchase:{sale_id}"
    return f"{platform}:{stage}:{click_id}"


def build_event_id(stage: str, lead_id: str, click_id: str, sale_id: str | None) -> str:
    """Mesmo ID nas duas plataformas (event_id na Meta, transactionId no Google)."""
    if stage == "purchase":
        return f"purchase:{sale_id}"
    h = hashlib.sha256(click_id.encode()).hexdigest()[:12]
    return f"{stage}:{lead_id}:{h}"
