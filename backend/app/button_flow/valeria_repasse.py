"""Varredura de repasse automático da ValerIA v2 (spec §8).

Quem mostrou intenção (nó em `NOS_COM_INTENCAO`) e parou de responder entre 2h e 22h
atrás é repassado ao vendedor do ramo por `valeria_runner_v2.repassar_parado`, que
pega a trava (`flow_state.repasse_auto`) e portanto é idempotente: duas varreduras
concorrentes não repassam o mesmo lead duas vezes.

Limites: desligado por padrão (`VALERIA_REPASSE_AUTO_ENABLED`), páginas de 200 (o
PostgREST corta em 1000) e no máximo 50 repasses por rodada — a explosão de follow-up
de 03–04/10/2026 veio de agendamento sem limite. Nunca levanta.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from app.button_flow import valeria_registry_v2 as r2
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)
_LOG = "[VALERIA_V2]"

MAX_REPASSES_POR_RODADA = 50
TAMANHO_PAGINA = 200
MAX_PAGINAS = 10
JANELA_MIN_HORAS = 2
JANELA_MAX_HORAS = 22


def _habilitado() -> bool:
    return os.getenv("VALERIA_REPASSE_AUTO_ENABLED", "").strip().lower() in ("1", "on", "true")


def _horas_desde(valor: str | None, agora: datetime) -> float:
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max((agora - dt).total_seconds() / 3600, 0.0)
    except Exception:
        return float(JANELA_MIN_HORAS)


def _pagina(sb, inicio: str, fim: str, offset: int) -> list[dict]:
    return (
        sb.table("conversations")
        .select("*, leads(*)")
        .eq("flow_state->>flow", "valeria_botoes_v2")
        .in_("flow_state->>node", sorted(r2.NOS_COM_INTENCAO))
        .is_("flow_state->>repasse_auto", "null")
        .gte("last_customer_message_at", inicio)
        .lte("last_customer_message_at", fim)
        .order("last_customer_message_at")
        .order("id")
        .range(offset, offset + TAMANHO_PAGINA - 1)
        .execute()
        .data
    ) or []


async def varrer() -> int:
    """Repassa os parados elegíveis. Devolve quantos repasses ESTA rodada ganhou."""
    if not _habilitado():
        return 0
    try:
        from app.channels.service import get_channel_by_id
        from app.whatsapp.registry import get_provider
        from app.button_flow import valeria_runner_v2 as runner

        agora = datetime.now(timezone.utc)
        inicio = (agora - timedelta(hours=JANELA_MAX_HORAS)).isoformat()
        fim = (agora - timedelta(hours=JANELA_MIN_HORAS)).isoformat()
        sb = get_supabase()
        ganhos = 0
        offset = 0
        for _ in range(MAX_PAGINAS):
            linhas = _pagina(sb, inicio, fim, offset)
            for conv in linhas:
                if ganhos >= MAX_REPASSES_POR_RODADA:
                    break
                try:
                    lead = conv.get("leads")
                    if isinstance(lead, list):
                        lead = lead[0] if lead else None
                    if not lead or lead.get("human_control") is True or lead.get("opt_out") is True:
                        continue
                    channel = get_channel_by_id(conv.get("channel_id")) if conv.get("channel_id") else None
                    if not channel:
                        logger.warning("%s varredura sem canal conv=%s", _LOG, conv.get("id"))
                        continue
                    conversa = {k: v for k, v in conv.items() if k != "leads"}
                    ok = await runner.repassar_parado(
                        lead=lead, conversation=conversa, channel=channel,
                        provider=get_provider(channel),
                        horas=_horas_desde(conv.get("last_customer_message_at"), agora))
                    if ok:
                        ganhos += 1
                except Exception as exc:
                    logger.error("%s varredura falhou conv=%s: %s", _LOG, conv.get("id"), exc,
                                 exc_info=True)
            if ganhos >= MAX_REPASSES_POR_RODADA or len(linhas) < TAMANHO_PAGINA:
                break
            offset += TAMANHO_PAGINA
        logger.info("%s varredura de parados: %d repasse(s)", _LOG, ganhos)
        return ganhos
    except Exception as exc:
        logger.error("%s varredura de parados abortada: %s", _LOG, exc, exc_info=True)
        return 0
