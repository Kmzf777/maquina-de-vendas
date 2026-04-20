"""Rehearsal runner — executa os 5 arquetipos A1-A5 sequencialmente.

Uso:
    REHEARSAL_MODE=true uvicorn app.main:app --env-file .env.local --port 8001 &
    python -m scripts.rehearsal_runner

Envs necessarias (em .env.local):
    GEMINI_API_KEY, DEV_BACKEND_URL, REHEARSAL_PHONE, SUPABASE_URL,
    SUPABASE_SERVICE_KEY, REDIS_URL
Opcionais:
    REHEARSAL_TURN_TIMEOUT (default 15), REHEARSAL_MAX_TURNS (default 20)
"""
import asyncio
import datetime as dt
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import redis.asyncio as aioredis
from dotenv import load_dotenv

# Load .env.local before importing backend modules that depend on env
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env.local")

from app.config import settings  # noqa: E402
from scripts.rehearsal import supabase_io, logger as rlogger, gemini_actor, verifier  # noqa: E402
from scripts.rehearsal.archetypes import ALL_ARCHETYPES, Archetype  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("rehearsal")

DEV_BACKEND_URL = os.environ.get("DEV_BACKEND_URL", "http://127.0.0.1:8001")
REHEARSAL_PHONE = os.environ.get("REHEARSAL_PHONE", "").strip()
MAX_TURNS = int(os.environ.get("REHEARSAL_MAX_TURNS", "20"))
TURN_TIMEOUT = float(os.environ.get("REHEARSAL_TURN_TIMEOUT", "15"))
POLL_INTERVAL = 0.5
OUTPUT_ROOT = Path(__file__).resolve().parent.parent.parent / "docs" / "superpowers" / "plans" / "pilot" / "rehearsal-runs"

FINAL_STAGES = {"A1": "atacado", "A2": "private_label", "A3": None, "A4": "atacado", "A5": "exportacao"}


def _now_iso() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


def _utc_ts_path_component() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


async def _health_check(client: httpx.AsyncClient) -> None:
    try:
        r = await client.get(f"{DEV_BACKEND_URL}/health", timeout=5)
        r.raise_for_status()
        log.info(f"Dev backend health OK ({DEV_BACKEND_URL})")
    except Exception as e:
        log.error(f"Dev backend health check failed: {e}")
        raise SystemExit(f"Dev backend em {DEV_BACKEND_URL} nao respondeu. Subir com REHEARSAL_MODE=true antes.")


def _build_meta_payload(phone: str, text: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "rehearsal",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "rehearsal", "display_phone_number": phone},
                    "contacts": [{"profile": {"name": "Rehearsal Lead"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": f"wamid.rehearsal.{uuid.uuid4().hex}",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


async def _send_user_message(client: httpx.AsyncClient, phone: str, text: str) -> None:
    payload = _build_meta_payload(phone, text)
    r = await client.post(f"{DEV_BACKEND_URL}/webhook/meta", json=payload, timeout=10)
    if r.status_code >= 400:
        log.warning(f"Webhook POST retornou {r.status_code}: {r.text[:200]}")


def _extract_stage_from_event(content: str) -> str | None:
    marker = "stage alterado para"
    low = content.lower()
    if marker in low:
        after = content[low.index(marker) + len(marker):].strip(": ,.")
        return after.split()[0].strip().lower() if after else None
    return None


def _terminated(archetype: Archetype, events: list[dict], turns: int) -> str | None:
    if turns >= MAX_TURNS:
        return "max_turns"
    for ev in events:
        content = ev.get("content", "").lower()
        if "encaminhado para" in content:
            return "encaminhar_humano"
    final_stage = FINAL_STAGES.get(archetype.id)
    if final_stage:
        for ev in events:
            stage = _extract_stage_from_event(ev.get("content", ""))
            if stage == final_stage:
                return "stage_reached"
    return None


async def _run_archetype(
    archetype: Archetype,
    client: httpx.AsyncClient,
    redis,
    run_dir: Path,
) -> dict:
    log.info(f"=== Iniciando arquetipo {archetype.id} ({archetype.slug}) ===")

    supabase_io.wipe_lead(REHEARSAL_PHONE)
    await supabase_io.wipe_redis_buffer(REHEARSAL_PHONE, redis)

    start_iso = _now_iso()
    await _send_user_message(client, REHEARSAL_PHONE, archetype.first_message)

    lead_id: str | None = None
    deadline = time.time() + TURN_TIMEOUT
    while time.time() < deadline and lead_id is None:
        await asyncio.sleep(POLL_INTERVAL)
        lead = supabase_io.get_lead_by_phone(REHEARSAL_PHONE)
        if lead:
            lead_id = lead["id"]
            break

    if not lead_id:
        log.error(f"{archetype.id}: lead nao foi criado em {TURN_TIMEOUT}s — abortando arquetipo")
        return {"archetype_id": archetype.id, "archetype_slug": archetype.slug,
                "status": "error", "error": "lead_not_created", "turns_count": 0,
                "terminated_by": "error", "soft_check": {}, "hard_checks": [],
                "stages_visited": []}

    turns = 1
    last_poll_iso = start_iso
    consecutive_timeouts = 0
    stages_visited: set[str] = set()
    terminated_by: str | None = None

    while True:
        valeria_msgs = []
        poll_deadline = time.time() + TURN_TIMEOUT
        while time.time() < poll_deadline:
            new_msgs = supabase_io.get_messages_since(lead_id, last_poll_iso)
            valeria_msgs = [m for m in new_msgs if m.get("role") == "assistant"]
            for m in new_msgs:
                if m.get("role") == "system":
                    stage = _extract_stage_from_event(m.get("content", ""))
                    if stage:
                        stages_visited.add(stage)
                        last_poll_iso = m["created_at"]
                if m.get("role") == "assistant":
                    last_poll_iso = m["created_at"]
            if valeria_msgs:
                break
            await asyncio.sleep(POLL_INTERVAL)

        if not valeria_msgs:
            consecutive_timeouts += 1
            log.warning(f"{archetype.id}: turno {turns} sem resposta (timeout #{consecutive_timeouts})")
            if consecutive_timeouts >= 2:
                terminated_by = "timeout"
                break
        else:
            consecutive_timeouts = 0

        events = supabase_io.get_system_events(lead_id)
        reason = _terminated(archetype, events, turns)
        if reason:
            terminated_by = reason
            break

        all_msgs = supabase_io.get_all_messages(lead_id)
        last_assistant = valeria_msgs[-1]["content"] if valeria_msgs else ""
        try:
            next_user_msg = gemini_actor.generate_next_lead_message(
                persona_prompt=archetype.persona_prompt,
                conversation_history=[{"role": m["role"], "content": m["content"]} for m in all_msgs],
                last_assistant_message=last_assistant,
            )
        except gemini_actor.GeminiFailure as e:
            log.error(f"{archetype.id}: Gemini falhou — {e}")
            terminated_by = "gemini_error"
            break

        if not next_user_msg:
            log.warning(f"{archetype.id}: Gemini retornou vazio — encerrando")
            terminated_by = "empty_gemini"
            break

        log.info(f"{archetype.id} turno {turns + 1} — Lead: {next_user_msg[:80]}")
        await _send_user_message(client, REHEARSAL_PHONE, next_user_msg)
        turns += 1

        if turns >= MAX_TURNS:
            terminated_by = "max_turns"
            break

    all_messages = supabase_io.get_all_messages(lead_id)
    events = supabase_io.get_system_events(lead_id)
    run_data = {
        "events": events,
        "messages": all_messages,
        "turns_count": turns,
        "stages_visited": stages_visited,
        "terminated_by": terminated_by,
    }
    verification = verifier.verify(archetype, run_data, transcript=_render_inline(all_messages))

    rlogger.write_archetype_artifacts(
        run_dir=run_dir,
        archetype=archetype,
        messages=all_messages,
        events=events,
        verification=verification,
    )

    log.info(f"=== {archetype.id} finalizado: status={verification['status']} turns={turns} by={terminated_by} ===")
    return verification


def _render_inline(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "?")
        label = {"user": "Lead", "assistant": "Valeria", "system": "system"}.get(role, role)
        lines.append(f"[{label}] {m.get('content', '')}")
    return "\n".join(lines)


async def main():
    if not REHEARSAL_PHONE:
        raise SystemExit("REHEARSAL_PHONE nao definido em .env.local")
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY nao definido em .env.local")

    only = os.environ.get("REHEARSAL_ONLY")
    archetypes = [a for a in ALL_ARCHETYPES if (not only or a.id == only)]
    if not archetypes:
        raise SystemExit(f"Nenhum arquetipo encontrado com REHEARSAL_ONLY={only}")

    run_ts = _utc_ts_path_component()
    run_dir = OUTPUT_ROOT / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Run dir: {run_dir}")

    started_at = _now_iso()
    run_meta = {
        "started_at": started_at,
        "git_sha": _git_sha(),
        "archetypes": [a.id for a in archetypes],
        "dev_backend_url": DEV_BACKEND_URL,
        "rehearsal_phone": REHEARSAL_PHONE,
        "gemini_model": gemini_actor.MODEL_NAME,
    }

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    verifications: list[dict] = []

    async with httpx.AsyncClient() as client:
        await _health_check(client)
        for archetype in archetypes:
            try:
                v = await _run_archetype(archetype, client, redis, run_dir)
            except Exception as e:
                log.exception(f"Erro catastrofico em {archetype.id}")
                v = {"archetype_id": archetype.id, "archetype_slug": archetype.slug,
                     "status": "error", "error": str(e), "turns_count": 0,
                     "terminated_by": "crash", "hard_checks": [], "soft_check": {},
                     "stages_visited": []}
            verifications.append(v)
            rlogger.write_run_summary(run_dir, verifications, {**run_meta, "finished_at": _now_iso()})

    await redis.close()

    log.info(f"Run completo. Artefatos em: {run_dir}")
    any_fail = any(v.get("status") != "passed" for v in verifications)
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
