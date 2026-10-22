"""Segmento do lead (`leads.segmento`), separado da fase do funil (`leads.stage`).

Contrato da Onda 0 do cartão b67f1c6b: nomes fixos, usados por vendedores, repasse,
qualificação e dashboard."""
from __future__ import annotations

import logging
import re
import unicodedata

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

SEGMENTOS = ("atacado", "private_label", "consumo", "exportacao")
FASES = ("pending", "novo", "triagem", "qualificando", "perdido")
SEGMENTOS_B2B = ("atacado", "private_label")


def _sem_acento(v: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", v) if not unicodedata.combining(c))


def normalizar_segmento(v: str | None) -> str | None:
    """"Private Label"/"private-label" -> "private_label"; fase, "secretaria" ou lixo -> None."""
    if not v:
        return None
    chave = re.sub(r"[\s\-]+", "_", _sem_acento(v).strip().lower())
    return chave if chave in SEGMENTOS else None


def fase_valida(v: str | None) -> bool:
    return v in FASES


def lead_e_b2b(lead_id: str) -> bool:
    """rpc `fn_lead_b2b`. Fail-soft: qualquer erro vira False (e loga)."""
    try:
        return bool(get_supabase().rpc("fn_lead_b2b", {"p_lead": lead_id}).execute().data)
    except Exception as exc:
        logger.warning("lead_e_b2b: rpc fn_lead_b2b falhou para o lead %s: %s", lead_id, exc)
        return False
