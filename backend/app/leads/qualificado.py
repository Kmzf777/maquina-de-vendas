"""Evento `lead_events.qualificado` (contrato da Onda 0, cartão b67f1c6b).

Um por lead (`dedupe_key='qualificado:'||lead_id`): o primeiro critério que qualificar
(repasse ao closer ou score) grava; os seguintes batem no dedupe e viram no-op.
Fail-soft: nunca levanta; erro ou duplicado só loga e devolve False."""
from __future__ import annotations

import logging
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# Mesmo texto de app/conversions/eligibility.py (_MOTIVOS_EXCLUIDOS): fallback de IA fora,
# recuperação trabalha a base própria e escalonamento é reclamação — não é lead qualificado.
MOTIVOS_EXCLUIDOS = ("ia temporariamente indisponível", "bot de recuperação", "escalonamento")


def motivo_qualifica(motivo: str | None) -> bool:
    texto = (motivo or "").lower()
    return not any(m in texto for m in MOTIVOS_EXCLUIDOS)


def score_qualifica(snapshot) -> bool:
    """Score qualifica (D2): `final_score >= 5` e não provisório. Snapshot ausente ou
    estranho -> False. Regra única do fluxo de botões e da tool `qualificar_lead`."""
    if not isinstance(snapshot, dict) or snapshot.get("is_provisional") is not False:
        return False
    try:
        return int(snapshot.get("final_score")) >= 5
    except (TypeError, ValueError):
        return False


def _duplicado(exc: Exception) -> bool:
    s = str(exc).lower()
    return "23505" in s or "duplicate" in s


def registrar_qualificado(*, lead_id: str, criterio: str, source: str, occurred_at: str | None = None,
                          segmento: str | None = None, b2b: bool | None = None, motivo: str | None = None,
                          vendedor_id: str | None = None) -> bool:
    if not lead_id:
        logger.warning("registrar_qualificado: sem lead_id; evento não gravado")
        return False
    evento: dict[str, Any] = {
        "lead_id": lead_id,
        "event_type": "qualificado",
        "source": source,
        "dedupe_key": f"qualificado:{lead_id}",
        "metadata": {"criterio": criterio, "segmento": segmento, "b2b": b2b,
                     "motivo": motivo, "vendedor_id": vendedor_id},
    }
    if occurred_at:
        evento["occurred_at"] = occurred_at
    try:
        get_supabase().table("lead_events").insert(evento).execute()
        return True
    except Exception as exc:
        if _duplicado(exc):
            logger.info("registrar_qualificado: lead %s já qualificado (dedupe)", lead_id)
        else:
            logger.warning("registrar_qualificado: evento do lead %s não gravado: %s", lead_id, exc)
        return False


# ── Desqualificação com motivo (F3, 06/11/2026) ─────────────────────────────
# A Valéria não gravava por que um lead NÃO foi ao vendedor: "ninguém é
# desqualificado, eles somem". Vocabulário fechado, o mesmo de
# `valeria_registry_v2.MOTIVOS_DESQUALIFICACAO` (repetido aqui de propósito: este
# módulo não importa o fluxo de botões).
MOTIVOS_DESQUALIFICACAO = ("consumidor_final", "sem_cnpj",
                           "sumiu_antes_da_tabela", "sumiu_depois_da_tabela")


def registrar_desqualificado(*, lead_id: str, motivo: str, no: str | None, source: str,
                             conversation_id: str | None = None, ramo: str | None = None,
                             chave: str | None = None) -> bool:
    """Evento `lead_events.desqualificado` com o motivo e o NÓ onde o lead parou.

    `chave` completa o dedupe (`desqualificado:<lead>:<motivo>:<chave>`): o mesmo
    lead pode sumir, voltar e sumir de novo; o chamador passa algo que distingue
    as ocorrências (o `last_customer_message_at`, por exemplo). Não mexe em
    `qualificado` nem em nada que vá para Meta/Google. Fail-soft.
    """
    if not lead_id or motivo not in MOTIVOS_DESQUALIFICACAO:
        logger.warning("registrar_desqualificado: lead %s motivo %r inválido", lead_id, motivo)
        return False
    evento: dict[str, Any] = {
        "lead_id": lead_id,
        "event_type": "desqualificado",
        "new_value": motivo,
        "source": source,
        "dedupe_key": f"desqualificado:{lead_id}:{motivo}:{chave or no or ''}",
        "metadata": {"motivo": motivo, "no": no, "ramo": ramo,
                     "conversation_id": conversation_id},
    }
    try:
        get_supabase().table("lead_events").insert(evento).execute()
        return True
    except Exception as exc:
        if _duplicado(exc):
            logger.info("registrar_desqualificado: lead %s já marcado (%s)", lead_id, motivo)
        else:
            logger.warning("registrar_desqualificado: lead %s não gravado: %s", lead_id, exc)
        return False
