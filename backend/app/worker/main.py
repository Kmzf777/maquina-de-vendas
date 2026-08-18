"""Entrypoint do worker: uma asyncio.Task isolada por domínio.

Substitui o loop sequencial único de 30s (antigo broadcast/worker.run_worker):
falha ou lentidão em um domínio não atrasa os demais. Domínios quentes são
acordados por eventos (app/events/bus.py) com varredura de fallback; os de
manutenção rodam em tick próprio, mais espaçado (egress).
"""
import asyncio
import logging

from app.worker.runtime import run_event_driven, run_periodic

logger = logging.getLogger(__name__)


async def _broadcasts_tick() -> None:
    from app.broadcast.worker import process_broadcasts, process_scheduled_broadcasts
    await process_scheduled_broadcasts()
    await process_broadcasts()


async def _followups_tick() -> None:
    from app.follow_up.scheduler import process_due_followups
    await process_due_followups()


async def _automation_tick() -> None:
    from app.automation.engine import process_due_enrollments
    from app.automation.triggers import check_polling_triggers
    await check_polling_triggers()
    await process_due_enrollments()


async def _llm_parking_tick() -> None:
    from app.buffer.parking import drain_parked_llm_turns
    await drain_parked_llm_turns()


async def _memory_tick() -> None:
    from app.agent.memory_manager import process_stale_lead_memories
    await process_stale_lead_memories()


async def _channel_health_tick() -> None:
    from app.broadcast.worker import check_meta_channel_health
    await check_meta_channel_health()


async def _reconcile_tick() -> None:
    from app.broadcast.worker import (
        process_wrong_number_deadends,
        reconcile_broadcast_replies,
        reconcile_delivery_timeouts,
        retry_undelivered_cold_sends,
    )
    await asyncio.to_thread(reconcile_broadcast_replies)
    await asyncio.to_thread(reconcile_delivery_timeouts)
    await retry_undelivered_cold_sends()
    await asyncio.to_thread(process_wrong_number_deadends)


async def _ad_spend_sync_tick() -> None:
    from app.campaigns.ad_spend_sync import sync_all_ad_spend
    await sync_all_ad_spend(days=30)


async def _bling_sync_tick() -> None:
    from app.bling.sync import bling_sync_tick
    await bling_sync_tick()


async def _bling_jobs_tick() -> None:
    from app.bling.jobs import bling_jobs_tick
    await bling_jobs_tick()


# (nome, tipo, fn, intervalo/fallback em segundos)
TASK_SPECS = [
    ("broadcasts", "event", _broadcasts_tick, 60),
    ("followups", "event", _followups_tick, 30),
    ("automation", "event", _automation_tick, 30),
    ("llm-parking", "periodic", _llm_parking_tick, 30),
    ("memory", "periodic", _memory_tick, 60),
    ("channel-health", "periodic", _channel_health_tick, 300),
    ("reconcile", "periodic", _reconcile_tick, 300),
    ("ad-spend-sync", "periodic", _ad_spend_sync_tick, 86400),
    ("bling-sync", "periodic", _bling_sync_tick, 86400),
    ("bling-jobs", "periodic", _bling_jobs_tick, 30),
]


async def run_worker() -> None:
    logger.info("Worker started — %d domínios isolados (event-driven + periódicos)", len(TASK_SPECS))
    tasks = []
    for name, kind, fn, seconds in TASK_SPECS:
        if kind == "event":
            tasks.append(run_event_driven(name, fn, name, seconds))
        else:
            tasks.append(run_periodic(name, fn, seconds))
    await asyncio.gather(*tasks)
