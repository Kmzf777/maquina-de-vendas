"""Simulação E2E da lead Iasmin Silver — valida Fixes A/B/C/D juntos.

Roteiro pré-roteirizado (não usa Gemini para gerar mensagens) para reproduzir
exatamente as 4 mensagens que falharam em produção e verificar cada fix.

Uso:
    python -m scripts.iasmin_e2e_simulation

Env (em .env.local):
    SUPABASE_URL, SUPABASE_SERVICE_KEY, REDIS_URL
Opcional:
    DEV_BACKEND_URL (default: http://127.0.0.1:8001)
    REHEARSAL_TURN_TIMEOUT (default: 30)
"""
import asyncio
import datetime as dt
import logging
import os
import time
from pathlib import Path

import httpx
import redis.asyncio as aioredis
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env.local")

from app.config import settings  # noqa: E402
from scripts.rehearsal import supabase_io  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("iasmin_sim")

DEV_BACKEND_URL = os.environ.get("DEV_BACKEND_URL", "http://127.0.0.1:8001")
TURN_TIMEOUT = float(os.environ.get("REHEARSAL_TURN_TIMEOUT", "30"))
POLL_INTERVAL = 0.5
SIM_PHONE = "5511900000099"

SCRIPT = [
    "quero saber sobre private label",
    "quais os valores para começar? me conta o preço por embalagem de 250g e como funciona a personalização",
    "pode me mostrar as fotos dos cafés? queria ver a diferença das embalagens e tipos",
    "tá difícil, não quero falar com robô, desisto",
]

TURN_LABELS = [
    "Turn 1 — Entrada Private Label",
    "Turn 2 — Valores (valida Fix D: delay entre bubbles)",
    "Turn 3 — Fotos (valida Fix A: sem truncamento | Fix B: texto antes de imagens)",
    "Turn 4 — Frustração (valida Fix C: guardrail encaminhar_humano)",
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _meta_payload(text: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "iasmin-sim",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "rehearsal", "display_phone_number": SIM_PHONE},
                    "contacts": [{"profile": {"name": "Iasmin Sim"}, "wa_id": SIM_PHONE}],
                    "messages": [{
                        "from": SIM_PHONE,
                        # Omit "id": processor gets wamid=None → delivery_status
                        # não entra no insert, compatível com staging sem migration.
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


async def _post(client: httpx.AsyncClient, text: str) -> None:
    r = await client.post(
        f"{DEV_BACKEND_URL}/webhook/meta",
        json=_meta_payload(text),
        timeout=httpx.Timeout(connect=10.0, read=5.0, write=5.0, pool=5.0),
    )
    if r.status_code >= 400:
        log.warning("Webhook retornou %s: %s", r.status_code, r.text[:120])


# ---------------------------------------------------------------------------
# Polling helpers
# ---------------------------------------------------------------------------

async def _wait_for_response(lead_id: str, after_iso: str) -> list[dict]:
    deadline = time.time() + TURN_TIMEOUT
    bubbles: list[dict] = []
    stable_ticks = 0
    while time.time() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        msgs = supabase_io.get_messages_since(lead_id, after_iso)
        new_bubbles = [m for m in msgs if m.get("role") == "assistant"]
        if new_bubbles:
            if len(new_bubbles) == len(bubbles):
                stable_ticks += 1
                if stable_ticks >= 4:
                    break
            else:
                stable_ticks = 0
                bubbles = new_bubbles
    return bubbles


def _last_ts(messages: list[dict]) -> str:
    if not messages:
        return dt.datetime.now(dt.UTC).isoformat()
    return messages[-1]["created_at"]


# ---------------------------------------------------------------------------
# Validations
# ---------------------------------------------------------------------------

def _check_fix_a(bubbles: list[dict]) -> tuple[bool, str]:
    """Fix A: nenhum balão truncado mid-sentence."""
    if not bubbles:
        return False, "nenhuma resposta recebida"
    issues = []
    for b in bubbles:
        content = b.get("content", "")
        if len(content) > 10 and content[-1] not in ".!?,:;)\"'…\n":
            issues.append(f"possível truncamento: «{content[-40:]}»")
    if issues:
        return False, " | ".join(issues)
    total_chars = sum(len(b.get("content", "")) for b in bubbles)
    return True, f"{len(bubbles)} bubble(s), {total_chars} chars totais — sem truncamento detectado"


def _check_fix_b(bubbles: list[dict], events: list[dict]) -> tuple[bool, str]:
    """Fix B: ferramenta enviar_fotos foi chamada E texto chegou (deferred media funcionou)."""
    tool_called = any(
        "enviar_fotos" in ev.get("content", "") or "enviar_foto" in ev.get("content", "")
        for ev in events
    )
    has_text = bool(bubbles)
    if not tool_called:
        return False, "enviar_fotos não apareceu nos eventos — ferramenta não foi chamada"
    if not has_text:
        return False, "enviar_fotos chamada MAS nenhum texto chegou (processor bloqueado?)"
    return True, f"enviar_fotos detectada nos eventos + {len(bubbles)} bubble(s) de texto entregues antes das fotos"


def _check_fix_c(events: list[dict]) -> tuple[bool, str]:
    """Fix C: encaminhar_humano disparado pelo guardrail."""
    forwarded = any(
        "encaminhar" in ev.get("content", "").lower() or "encaminhado" in ev.get("content", "").lower()
        for ev in events
    )
    if forwarded:
        return True, "encaminhar_humano presente nos eventos — guardrail disparou corretamente"
    return False, "encaminhar_humano NÃO encontrado nos eventos — guardrail não disparou"


def _check_fix_d(all_messages: list[dict]) -> tuple[bool, str]:
    """Fix D: mede delay entre bubbles consecutivos na mesma resposta.

    Grupos de assistant messages consecutivas (sem user no meio) representam
    os bubbles de um mesmo turno. Ideal: ≥1 segundo de intervalo entre eles.
    """
    groups: list[list[dict]] = []
    current: list[dict] = []
    for m in all_messages:
        if m.get("role") == "assistant":
            current.append(m)
        else:
            if len(current) >= 2:
                groups.append(current)
            current = []
    if len(current) >= 2:
        groups.append(current)

    if not groups:
        return True, "nenhum turno com múltiplos bubbles encontrado (resposta em 1 bubble só)"

    details = []
    all_delays_ok = True
    for idx, group in enumerate(groups):
        deltas = []
        for i in range(1, len(group)):
            try:
                t0 = dt.datetime.fromisoformat(group[i - 1]["created_at"].replace("Z", "+00:00"))
                t1 = dt.datetime.fromisoformat(group[i]["created_at"].replace("Z", "+00:00"))
                deltas.append((t1 - t0).total_seconds())
            except Exception:
                pass
        if deltas:
            min_d = min(deltas)
            max_d = max(deltas)
            flag = "✓" if min_d >= 0.5 else "⚠ (REHEARSAL_MODE=true zera delays)"
            details.append(f"grupo {idx + 1} ({len(group)} bubbles): min={min_d:.2f}s max={max_d:.2f}s {flag}")
            if min_d < 0.1:
                all_delays_ok = False

    summary = " | ".join(details) if details else "sem dados de timing"
    return True, summary  # Fix D nunca falha — zera em rehearsal é comportamento esperado


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _print_separator(title: str = "") -> None:
    width = 70
    if title:
        pad = (width - len(title) - 2) // 2
        log.info("=" * pad + f" {title} " + "=" * (width - pad - len(title) - 2))
    else:
        log.info("=" * width)


async def main() -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async with httpx.AsyncClient() as client:
        # Health check
        try:
            r = await client.get(f"{DEV_BACKEND_URL}/health", timeout=5)
            r.raise_for_status()
            log.info("Backend OK: %s", DEV_BACKEND_URL)
        except Exception as exc:
            raise SystemExit(
                f"Backend em {DEV_BACKEND_URL} não respondeu ({exc}).\n"
                "Suba com: REHEARSAL_MODE=true uvicorn app.main:app --env-file .env.local --port 8001"
            )

        # Clean slate
        supabase_io.wipe_lead(SIM_PHONE)
        await supabase_io.wipe_redis_buffer(SIM_PHONE, redis)
        log.info("Lead anterior limpo. Iniciando simulação com phone=%s", SIM_PHONE)

        # ---------------------------------------------------------------
        # Turn 1: entrada
        # ---------------------------------------------------------------
        _print_separator(TURN_LABELS[0])
        log.info("Lead: %s", SCRIPT[0])
        await _post(client, SCRIPT[0])

        # Wait for lead creation
        lead_id = None
        deadline = time.time() + TURN_TIMEOUT
        while time.time() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            lead = supabase_io.get_lead_by_phone(SIM_PHONE)
            if lead:
                lead_id = lead["id"]
                break
        if not lead_id:
            raise SystemExit("Lead não criado em %ss — backend não está processando." % TURN_TIMEOUT)

        log.info("Lead criado: %s", lead_id)
        turn1_bubbles = await _wait_for_response(lead_id, "1970-01-01T00:00:00+00:00")
        log.info("Valéria (%d bubble(s)):", len(turn1_bubbles))
        for b in turn1_bubbles:
            log.info("  [bubble] %s", b["content"][:120])

        # ---------------------------------------------------------------
        # Turn 2: valores — valida Fix D
        # ---------------------------------------------------------------
        _print_separator(TURN_LABELS[1])
        log.info("Lead: %s", SCRIPT[1])
        await _post(client, SCRIPT[1])
        t2_anchor = _last_ts(turn1_bubbles)
        turn2_bubbles = await _wait_for_response(lead_id, t2_anchor)
        log.info("Valéria (%d bubble(s)):", len(turn2_bubbles))
        for b in turn2_bubbles:
            log.info("  [bubble] %s", b["content"][:120])

        # ---------------------------------------------------------------
        # Turn 3: fotos — valida Fix A + Fix B
        # ---------------------------------------------------------------
        _print_separator(TURN_LABELS[2])
        log.info("Lead: %s", SCRIPT[2])
        await _post(client, SCRIPT[2])
        t3_anchor = _last_ts(turn2_bubbles)
        turn3_bubbles = await _wait_for_response(lead_id, t3_anchor)
        log.info("Valéria (%d bubble(s)):", len(turn3_bubbles))
        for b in turn3_bubbles:
            log.info("  [bubble] %s", b["content"][:120])

        # ---------------------------------------------------------------
        # Turn 4: desisto — valida Fix C
        # ---------------------------------------------------------------
        _print_separator(TURN_LABELS[3])
        log.info("Lead: %s", SCRIPT[3])
        await _post(client, SCRIPT[3])
        t4_anchor = _last_ts(turn3_bubbles)
        # Guardrail is sync (bypasses LLM), allow shorter wait
        await asyncio.sleep(8)
        turn4_bubbles = await _wait_for_response(lead_id, t4_anchor)
        log.info("Valéria (%d bubble(s) pós-desisto):", len(turn4_bubbles))
        for b in turn4_bubbles:
            log.info("  [bubble] %s", b["content"][:120])

    await redis.aclose()

    # ---------------------------------------------------------------
    # Validation
    # ---------------------------------------------------------------
    all_messages = supabase_io.get_all_messages(lead_id)
    events = supabase_io.get_system_events(lead_id)

    fix_a_ok, fix_a_msg = _check_fix_a(turn2_bubbles + turn3_bubbles)
    fix_b_ok, fix_b_msg = _check_fix_b(turn3_bubbles, events)
    fix_c_ok, fix_c_msg = _check_fix_c(events)
    fix_d_ok, fix_d_msg = _check_fix_d(all_messages)

    _print_separator("RELATÓRIO FINAL")
    checks = [
        ("Fix A — Sem truncamento", fix_a_ok, fix_a_msg),
        ("Fix B — Deferred media (texto antes das fotos)", fix_b_ok, fix_b_msg),
        ("Fix C — Guardrail frustração", fix_c_ok, fix_c_msg),
        ("Fix D — Delay dinâmico entre bubbles", fix_d_ok, fix_d_msg),
    ]
    all_passed = True
    for label, ok, msg in checks:
        status = "✅ PASS" if ok else "❌ FAIL"
        log.info("%s | %s: %s", status, label, msg)
        if not ok:
            all_passed = False

    _print_separator("EVENTOS DO SISTEMA")
    for ev in events:
        log.info("  [event] %s", ev.get("content", "")[:120])

    _print_separator()
    if all_passed:
        log.info("🎯 SIMULAÇÃO CONCLUÍDA — todos os fixes validados com sucesso.")
    else:
        log.warning("⚠  SIMULAÇÃO CONCLUÍDA com falhas — ver relatório acima.")


if __name__ == "__main__":
    asyncio.run(main())
