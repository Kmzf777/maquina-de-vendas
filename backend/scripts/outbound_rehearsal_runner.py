"""Outbound Rehearsal Runner — valida a Valéria Outbound com 4 archetypes (O1-O4).

Uso:
    REHEARSAL_MODE=true uvicorn app.main:app --env-file .env.local --port 8001 &
    python -m scripts.outbound_rehearsal_runner          # roda O1-O4 em paralelo
    REHEARSAL_ONLY=O3 python -m scripts.outbound_rehearsal_runner  # roda só um

Envs necessárias (em .env.local):
    GEMINI_API_KEY, DEV_BACKEND_URL, SUPABASE_URL,
    SUPABASE_SERVICE_KEY, REDIS_URL
Opcionais:
    REHEARSAL_TURN_TIMEOUT (default 20), REHEARSAL_MAX_TURNS (default 20)
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

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env.local")

from app.config import settings  # noqa: E402
from scripts.rehearsal import supabase_io, logger as rlogger, gemini_actor, verifier  # noqa: E402
from scripts.rehearsal.outbound_archetypes import (  # noqa: E402
    ALL_OUTBOUND_ARCHETYPES,
    OutboundArchetype,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("outbound_rehearsal")

DEV_BACKEND_URL = os.environ.get("DEV_BACKEND_URL", "http://127.0.0.1:8001")
META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "rehearsal")
MAX_TURNS = int(os.environ.get("REHEARSAL_MAX_TURNS", "20"))
TURN_TIMEOUT = float(os.environ.get("REHEARSAL_TURN_TIMEOUT", "20"))
POLL_INTERVAL = 0.5
_MAX_CONNECT_RETRIES = 2
OUTPUT_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "superpowers"
    / "plans"
    / "pilot"
    / "outbound-rehearsal-runs"
)


# ─── Payload builders ────────────────────────────────────────────────────────

def _build_button_reply_payload(phone: str, button_id: str, button_title: str) -> dict:
    """Monta payload webhook Meta para interactive/button_reply (quick reply)."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "rehearsal",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "phone_number_id": META_PHONE_NUMBER_ID,
                        "display_phone_number": phone,
                    },
                    "contacts": [{"profile": {"name": "Rehearsal Lead"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": f"wamid.rehearsal.{uuid.uuid4().hex}",
                        "timestamp": str(int(time.time())),
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {
                                "id": button_id,
                                "title": button_title,
                            },
                        },
                    }],
                },
                "field": "messages",
            }],
        }],
    }


def _build_text_payload(phone: str, text: str) -> dict:
    """Monta payload webhook Meta para mensagem de texto simples."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "rehearsal",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "phone_number_id": META_PHONE_NUMBER_ID,
                        "display_phone_number": phone,
                    },
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


def _build_first_message_payload(phone: str, first_message) -> dict:
    """Dispatcher: retorna payload correto conforme tipo de first_message."""
    if isinstance(first_message, dict) and first_message.get("type") == "button_reply":
        return _build_button_reply_payload(
            phone,
            first_message["button_id"],
            first_message["button_title"],
        )
    return _build_text_payload(phone, str(first_message))


def build_outbound_template_payload(phone: str) -> dict:
    """Monta o payload do template de disparo inicial para envio via Meta Cloud API.

    NOTA: Este payload é para referência/documentação. O envio real via broadcast
    já é feito pela infra existente (broadcast/worker.py + MetaCloudClient.send_template).
    No contexto do Rehearsal, o lead já existe e a conversa começa com a resposta dele.
    """
    return {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": "utilidade_22_04_2026_16_40",
            "language": {"code": "en"},
            "components": [
                {
                    "type": "button",
                    "buttons": [
                        {"type": "QUICK_REPLY", "text": "Sim"},
                        {"type": "QUICK_REPLY", "text": "Não"},
                        {"type": "QUICK_REPLY", "text": "Parar mensagens"},
                    ],
                }
            ],
        },
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _utc_ts_path_component() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%S")


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _extract_stage_from_event(content: str) -> str | None:
    marker = "stage alterado para"
    low = content.lower()
    if marker in low:
        after = content[low.index(marker) + len(marker):].strip(": ,.")
        return after.split()[0].strip().lower() if after else None
    return None


def _terminated(archetype: OutboundArchetype, events: list[dict], turns: int) -> str | None:
    if turns >= MAX_TURNS:
        return "max_turns"
    for ev in events:
        if "encaminhado para" in ev.get("content", "").lower():
            return "encaminhar_humano"
    return None


def _render_inline(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "?")
        label = {"user": "Lead", "assistant": "Valeria", "system": "system"}.get(role, role)
        lines.append(f"[{label}] {m.get('content', '')}")
    return "\n".join(lines)


async def _health_check(client: httpx.AsyncClient) -> None:
    try:
        r = await client.get(f"{DEV_BACKEND_URL}/health", timeout=5)
        r.raise_for_status()
        log.info(f"Dev backend health OK ({DEV_BACKEND_URL})")
    except Exception as e:
        log.error(f"Dev backend health check failed: {e}")
        raise SystemExit(
            f"Dev backend em {DEV_BACKEND_URL} nao respondeu. "
            "Subir com REHEARSAL_MODE=true antes."
        )


async def _send_webhook(client: httpx.AsyncClient, payload: dict) -> None:
    for attempt in range(3):
        try:
            r = await client.post(
                f"{DEV_BACKEND_URL}/webhook/meta",
                json=payload,
                timeout=httpx.Timeout(connect=20.0, read=90.0, write=10.0, pool=15.0),
            )
            if r.status_code >= 400:
                log.warning(f"Webhook POST retornou {r.status_code}: {r.text[:200]}")
            return
        except (httpx.ReadError, httpx.ConnectError, httpx.PoolTimeout) as exc:
            wait = 2 ** attempt
            log.warning(
                f"Webhook POST falhou ({exc.__class__.__name__}) "
                f"tentativa {attempt + 1}/3 — aguardando {wait}s"
            )
            if attempt == 2:
                raise
            await asyncio.sleep(wait)


# ─── Archetype runner ────────────────────────────────────────────────────────

async def _run_outbound_archetype(
    archetype: OutboundArchetype,
    client: httpx.AsyncClient,
    redis,
    run_dir: Path,
    phone: str,
) -> dict:
    log.info(f"[{archetype.id}] Iniciando ({archetype.slug}) phone={phone}")

    supabase_io.wipe_lead(phone)
    await supabase_io.wipe_redis_buffer(phone, redis)

    start_iso = _now_iso()

    first_payload = _build_first_message_payload(phone, archetype.first_message)
    for _attempt in range(_MAX_CONNECT_RETRIES + 1):
        try:
            await _send_webhook(client, first_payload)
            break
        except httpx.ConnectTimeout:
            if _attempt == _MAX_CONNECT_RETRIES:
                log.error(f"[{archetype.id}] ConnectTimeout apos {_MAX_CONNECT_RETRIES + 1} tentativas")
                return {
                    "archetype_id": archetype.id,
                    "archetype_slug": archetype.slug,
                    "status": "error",
                    "error": "ConnectTimeout",
                    "turns_count": 0,
                    "terminated_by": "crash",
                    "hard_checks": [],
                    "soft_check": {},
                    "stages_visited": [],
                }
            wait = 5.0 * (_attempt + 1)
            log.warning(f"[{archetype.id}] ConnectTimeout — tentativa {_attempt + 1}, aguardando {wait:.0f}s")
            await asyncio.sleep(wait)

    lead_id: str | None = None
    deadline = time.time() + TURN_TIMEOUT
    while time.time() < deadline and lead_id is None:
        await asyncio.sleep(POLL_INTERVAL)
        lead = supabase_io.get_lead_by_phone(phone)
        if lead:
            lead_id = lead["id"]

    if not lead_id:
        log.error(f"[{archetype.id}] Lead nao criado em {TURN_TIMEOUT}s — abortando")
        return {
            "archetype_id": archetype.id,
            "archetype_slug": archetype.slug,
            "status": "error",
            "error": "lead_not_created",
            "turns_count": 0,
            "terminated_by": "error",
            "soft_check": {},
            "hard_checks": [],
            "stages_visited": [],
        }

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
            log.warning(f"[{archetype.id}] Turno {turns} sem resposta (timeout #{consecutive_timeouts})")
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
            log.error(f"[{archetype.id}] Gemini falhou — {e}")
            terminated_by = "gemini_error"
            break

        if not next_user_msg:
            log.warning(f"[{archetype.id}] Gemini retornou vazio — encerrando")
            terminated_by = "empty_gemini"
            break

        log.info(f"[{archetype.id}] Turno {turns + 1} — Lead: {next_user_msg[:80]}")
        await _send_webhook(client, _build_text_payload(phone, next_user_msg))
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

    log.info(
        f"[{archetype.id}] Finalizado: status={verification['status']} "
        f"turns={turns} by={terminated_by}"
    )
    return verification


async def _run_with_jitter(
    idx: int,
    archetype: OutboundArchetype,
    client: httpx.AsyncClient,
    redis,
    run_dir: Path,
) -> dict:
    phone = f"5521{(90 + idx):08d}"  # Range separado dos T1-T6 (5511...) para evitar colisão
    log.info(f"[{archetype.id}] Agendado — phone={phone} jitter={idx * 2.0}s")
    await asyncio.sleep(idx * 2.0)
    return await _run_outbound_archetype(archetype, client, redis, run_dir, phone)


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY nao definido em .env.local")

    if os.environ.get("REHEARSAL_MODE") != "true":
        raise SystemExit(
            "REHEARSAL_MODE nao esta setado como 'true'. "
            "Subir o backend com REHEARSAL_MODE=true antes de executar."
        )

    only = os.environ.get("REHEARSAL_ONLY")
    archetypes = [a for a in ALL_OUTBOUND_ARCHETYPES if (not only or a.id == only)]
    if not archetypes:
        raise SystemExit(f"Nenhum arquetipo encontrado com REHEARSAL_ONLY={only}")

    started_at = _now_iso()
    run_ts = _utc_ts_path_component()
    run_dir = OUTPUT_ROOT / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Run dir: {run_dir}")

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async with httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=10,
            max_keepalive_connections=5,
            keepalive_expiry=30,
        ),
        timeout=httpx.Timeout(connect=20.0, read=90.0, write=10.0, pool=15.0),
    ) as client:
        await _health_check(client)

        # ── Execução paralela dos 4 leads ──────────────────────────────────
        # Para disparar os testes: descomentar o bloco abaixo e executar o script.
        #
        # tasks = [
        #     _run_with_jitter(idx, archetype, client, redis, run_dir)
        #     for idx, archetype in enumerate(archetypes)
        # ]
        # raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        #
        log.info(
            f"Infraestrutura pronta. {len(archetypes)} archetype(s) configurados: "
            + ", ".join(a.id for a in archetypes)
        )
        log.info("Para executar os testes: descomentar o bloco 'tasks' em main().")
        raw_results = []

    verifications: list[dict] = []
    for archetype, result in zip(archetypes, raw_results):
        if isinstance(result, BaseException):
            err_repr = f"{type(result).__name__}: {result}" if str(result) else type(result).__name__
            log.error(f"[{archetype.id}] Erro catastrofico: {err_repr}")
            verifications.append({
                "archetype_id": archetype.id,
                "archetype_slug": archetype.slug,
                "status": "error",
                "error": err_repr,
                "turns_count": 0,
                "terminated_by": "crash",
                "hard_checks": [],
                "soft_check": {},
                "stages_visited": [],
            })
        else:
            verifications.append(result)

    await redis.aclose()

    run_json = {
        "started_at": started_at,
        "finished_at": _now_iso(),
        "git_sha": _git_sha(),
        "archetypes": [a.id for a in archetypes],
        "dev_backend_url": DEV_BACKEND_URL,
        "phones": {a.id: f"5521{(90 + idx):08d}" for idx, a in enumerate(archetypes)},
        "gemini_model": gemini_actor.MODEL_NAME,
        "verifications": verifications,
        "mode": "infrastructure_ready_not_executed",
    }
    (run_dir / "run.json").write_text(
        json.dumps(run_json, ensure_ascii=False, indent=2, default=str)
    )

    log.info(f"Artefatos em: {run_dir}")


if __name__ == "__main__":
    asyncio.run(main())
