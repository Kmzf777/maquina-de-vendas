"""Evento `lead_events.repasse`: um por repasse ao closer (D3), sem sobrescrever histórico.

Fail-soft: o repasse em si (mensagem-marcador + carimbo metadata.handoff) já foi gravado e é
o que follow-up, buffer e watchdog leem; perder o evento só empobrece a linha do tempo."""
from __future__ import annotations

import logging
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def registrar_repasse(*, lead_id: str, conversation_id: str | None, message_id: str | None,
                      occurred_at: str | None, source: str, vendedor_id: str | None = None,
                      vendedor: str | None = None, segmento: str | None = None,
                      motivo: str | None = None) -> bool:
    if not lead_id or not message_id:
        logger.warning("registrar_repasse: lead %s sem message_id; evento não gravado", lead_id)
        return False
    evento: dict[str, Any] = {
        "lead_id": lead_id,
        "event_type": "repasse",
        "new_value": vendedor,
        "source": source,
        "dedupe_key": f"repasse:{message_id}",
        "metadata": {"vendedor_id": vendedor_id, "vendedor": vendedor, "segmento": segmento,
                     "motivo": motivo, "conversation_id": conversation_id, "message_id": message_id},
    }
    if occurred_at:
        evento["occurred_at"] = occurred_at
    try:
        get_supabase().table("lead_events").insert(evento).execute()
        return True
    except Exception as exc:  # inclui violação do dedupe_key (repetição) — idempotente
        logger.error("registrar_repasse: evento do lead %s não gravado: %s", lead_id, exc)
        return False


def marcador_id_e_data(marcador: Any) -> tuple[str | None, str | None]:
    """(id, created_at) da linha devolvida por `save_message` do marcador.

    Só aceita dict: qualquer outra coisa (None quando o insert falhou, dublê de teste)
    vira (None, None), e `registrar_repasse` não grava nada sem message_id."""
    if not isinstance(marcador, dict):
        return None, None
    return marcador.get("id"), marcador.get("created_at")
