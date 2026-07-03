"""Watchdog fim-a-fim (Etapa 1 / A1).

Contexto: o apagao de producao (01-02/07) deixou leads ate 21h sem resposta com
mensagens salvas no banco e ZERO alertas. Os alertas ja existentes (llm_down,
billing) observam EXCECOES no caminho de execucao — se o processo morre em
silencio (timer morto, handoff incompleto, `[AGENT FAILED]` generico sem alerta),
nada dispara. Este modulo observa o BANCO (verdade fim-a-fim, independente de qual
bug matou o turno):

  - Check 1 `ai_unresponsive` (caso Welita): lead mandou mensagem num canal de IA
    com a IA ligada e ninguem respondeu.
  - Check 2 `orphan_lead_reply` (caso Rafael): lead respondeu com a IA desligada e
    sem controle humano assumido — ninguem e dono da conversa.
  - Check 3 `followup_jobs_stuck`: jobs de follow-up pendentes com fire_at muito no
    passado — o scheduler parou de rodar.

Roda como task asyncio no lifespan de main.py, espelhando o padrao de run_flusher
(app/buffer/flusher.py): loop infinito, sleep entre ticks, cancelado no shutdown.
Cada check e uma funcao SINCRONA pura (testavel sem o loop); o isolamento de falha
(um check quebrado nao derruba os outros) e responsabilidade do loop, no
try/except por item.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.alerts.service import create_system_alert
from app.buffer.recovery import recover_orphaned_buffers
from app.config import get_settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# --- Constantes (sem numeros magicos inline) -----------------------------------
WATCHDOG_INTERVAL_SECONDS = 60
AI_UNRESPONSIVE_GRACE_MINUTES = 5
# Usado tambem como piso da janela de candidatas do Check 2 (_find_unanswered_conversations
# e compartilhada) -- so leva o nome do Check 1 porque foi o caso motivador (Welita).
AI_UNRESPONSIVE_LOOKBACK_HOURS = 24
ORPHAN_REPLY_GRACE_MINUTES = 30
STUCK_JOB_HOURS = 2
ALERT_DEDUP_HOURS = 1
# Teto de mensagens candidatas por tick (passo 1 dos Checks 1/2) e de jobs presos
# por tick (Check 3) — mantem as queries limitadas mesmo sob volume alto.
CANDIDATE_MESSAGE_LIMIT = 500
STUCK_JOB_LIMIT = 50

# Mesmo padrao de app/follow_up/service.py:13 — escopa Check 3 ao ambiente atual
# (dev/production) para nao misturar jobs de teste com os reais.
_ENV_TAG = "dev" if get_settings().is_dev_env else "production"


def _parse_ts(value) -> datetime:
    """Converte um timestamp do Supabase (string ISO, sufixo `Z` ou `+00:00`, ou já
    um `datetime`) num `datetime` aware. NUNCA compare timestamps como string —
    offset e precisao de microsegundos variam entre linhas; sempre parseie antes.
    """
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _alert_recently_fired(alert_type: str) -> bool:
    """True se ja existe um alerta `alert_type` NAO resolvido criado na ultima hora.

    Dedup espelhando o padrao de `processor._fire_llm_down_alert` /
    `alerts.service.fire_billing_alert`. Fail-open: erro ao consultar -> False (nao
    bloqueia o alerta — foi o silencio, nao um alerta duplicado, que deixou o
    apagao de 01-02/07 invisivel).
    """
    try:
        sb = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ALERT_DEDUP_HOURS)).isoformat()
        existing = (
            sb.table("system_alerts")
            .select("id")
            .eq("type", alert_type)
            .eq("resolved", False)
            .gte("created_at", cutoff)
            .limit(1)
            .execute()
        )
        return bool(existing.data)
    except Exception as exc:
        logger.warning("[WATCHDOG] falha ao checar dedup do alerta type=%s: %s", alert_type, exc)
        return False


def _find_unanswered_conversations(
    now: datetime,
    *,
    grace_minutes: int,
    embed_select: str,
    scope_ok: Callable[[dict], bool],
) -> list:
    """Estrategia PostgREST em 3 passos (sem NOT EXISTS), compartilhada pelos Checks 1 e 2.

    1. Candidatas: ultima mensagem `role=user` por conversation_id, na janela
       [now-lookback, now-grace]. O grace evita falso-positivo em mensagem
       recem-chegada que ainda pode estar dentro da janela de buffer/processamento.
    2. Escopo: embeda conversations->channels/leads via `embed_select`; `scope_ok`
       decide se a conversa cai no escopo do check (ex.: canal de IA + IA ligada).
    3. Respostas: ultima mensagem assistant/system por conversation_id dentro do
       escopo restante. Uma conversa esta violada quando NAO existe resposta com
       timestamp maior que o da sua mensagem candidata.

    Retorna a lista de `conversation_id` em violacao.
    """
    sb = get_supabase()
    lookback_cutoff = (now - timedelta(hours=AI_UNRESPONSIVE_LOOKBACK_HOURS)).isoformat()
    grace_cutoff = (now - timedelta(minutes=grace_minutes)).isoformat()

    # Passo 1 — candidatas.
    candidates_res = (
        sb.table("messages")
        .select("conversation_id, created_at")
        .eq("role", "user")
        .gte("created_at", lookback_cutoff)
        .lte("created_at", grace_cutoff)
        .order("created_at", desc=True)
        .limit(CANDIDATE_MESSAGE_LIMIT)
        .execute()
    )
    last_user_msg: dict = {}
    for row in candidates_res.data or []:
        conv_id = row["conversation_id"]
        ts = row["created_at"]
        if conv_id not in last_user_msg or _parse_ts(ts) > _parse_ts(last_user_msg[conv_id]):
            last_user_msg[conv_id] = ts

    if not last_user_msg:
        return []

    # Passo 2 — escopo.
    ids = list(last_user_msg.keys())
    scope_res = (
        sb.table("conversations")
        .select(embed_select)
        .in_("id", ids)
        .execute()
    )
    ids_restantes = [row["id"] for row in (scope_res.data or []) if scope_ok(row)]

    if not ids_restantes:
        return []

    # Passo 3 — respostas (so precisa olhar a partir da candidata mais antiga).
    min_candidate_ts = min((last_user_msg[cid] for cid in ids_restantes), key=_parse_ts)
    replies_res = (
        sb.table("messages")
        .select("conversation_id, created_at")
        .in_("conversation_id", ids_restantes)
        .in_("role", ["assistant", "system"])
        .gte("created_at", min_candidate_ts)
        .execute()
    )
    latest_reply: dict = {}
    for row in replies_res.data or []:
        conv_id = row["conversation_id"]
        ts = row["created_at"]
        if conv_id not in latest_reply or _parse_ts(ts) > _parse_ts(latest_reply[conv_id]):
            latest_reply[conv_id] = ts

    violated = []
    for conv_id in ids_restantes:
        reply_ts = latest_reply.get(conv_id)
        if reply_ts is None or not (_parse_ts(reply_ts) > _parse_ts(last_user_msg[conv_id])):
            violated.append(conv_id)
    return violated


def check_ai_unresponsive(now: datetime) -> int:
    """Check 1 (caso Welita) — retorna o nº de conversas em violacao (0 = ok)."""
    violated = _find_unanswered_conversations(
        now,
        grace_minutes=AI_UNRESPONSIVE_GRACE_MINUTES,
        embed_select="id, channels!inner(mode), leads!inner(ai_enabled, opt_out, name)",
        scope_ok=lambda row: (
            (row.get("channels") or {}).get("mode") == "ai"
            and (row.get("leads") or {}).get("ai_enabled") is True
        ),
    )
    n = len(violated)
    if n:
        logger.warning("[WATCHDOG] ai_unresponsive: %d conversa(s) em violacao", n)
        if not _alert_recently_fired("ai_unresponsive"):
            create_system_alert(
                "ai_unresponsive",
                "IA sem resposta a leads",
                f"{n} conversa(s) com mensagem de lead sem resposta há mais de "
                f"{AI_UNRESPONSIVE_GRACE_MINUTES}min no canal de IA. Verifique "
                "backend/worker/LLM (apagão 01-02/07 teve essa assinatura).",
                severity="critical",
                metadata={"conversation_ids": violated[:10]},
            )
    return n


def check_orphan_lead_reply(now: datetime) -> int:
    """Check 2 (caso Rafael) — retorna o nº de conversas em violacao (0 = ok).

    Pos-handoff (`human_control=true`) NAO alerta — e o estado esperado (a ponte
    B1 que garante um vendedor efetivamente assumindo e outra etapa).
    """
    violated = _find_unanswered_conversations(
        now,
        grace_minutes=ORPHAN_REPLY_GRACE_MINUTES,
        embed_select="id, leads!inner(ai_enabled, human_control, opt_out, name)",
        scope_ok=lambda row: (
            (row.get("leads") or {}).get("ai_enabled") is False
            and (row.get("leads") or {}).get("human_control") is False
            and (row.get("leads") or {}).get("opt_out") is False
        ),
    )
    n = len(violated)
    if n:
        logger.warning("[WATCHDOG] orphan_lead_reply: %d conversa(s) em violacao", n)
        if not _alert_recently_fired("orphan_lead_reply"):
            create_system_alert(
                "orphan_lead_reply",
                "Lead respondeu sem dono",
                f"{n} lead(s) responderam há mais de {ORPHAN_REPLY_GRACE_MINUTES}min "
                "com a IA desligada e sem controle humano assumido (sem dono). "
                "Verifique se algum vendedor precisa assumir a conversa.",
                severity="warning",
                metadata={"conversation_ids": violated[:10]},
            )
    return n


def check_stuck_followup_jobs(now: datetime) -> int:
    """Check 3 — jobs de follow-up pendentes com fire_at muito no passado (scheduler parado)."""
    sb = get_supabase()
    cutoff = (now - timedelta(hours=STUCK_JOB_HOURS)).isoformat()
    res = (
        sb.table("follow_up_jobs")
        .select("id, job_type, fire_at")
        .eq("status", "pending")
        .eq("env_tag", _ENV_TAG)
        .lte("fire_at", cutoff)
        .limit(STUCK_JOB_LIMIT)
        .execute()
    )
    rows = res.data or []
    n = len(rows)
    if n:
        logger.warning("[WATCHDOG] followup_jobs_stuck: %d job(s) presos (env=%s)", n, _ENV_TAG)
        if not _alert_recently_fired("followup_jobs_stuck"):
            job_types = sorted({row["job_type"] for row in rows if row.get("job_type")})
            create_system_alert(
                "followup_jobs_stuck",
                "Follow-ups presos sem disparo",
                f"{n} job(s) de follow-up pendentes há mais de {STUCK_JOB_HOURS}h "
                f"(env={_ENV_TAG}). Verifique se o scheduler de follow-up está rodando.",
                severity="warning",
                metadata={"count": n, "job_types": job_types},
            )
    return n


async def run_watchdog(app) -> None:
    """Loop de background iniciado pelo lifespan (main.py). Roda ate ser cancelado.

    `REHEARSAL_MODE=true`: o tick so dorme — nenhum check, nenhuma recovery (mesmo
    padrao de `schedule_handoff_rescue`/`schedule_ai_return`). Caso contrario, cada
    check roda em try/except proprio (isolamento de falha: um check quebrado NAO
    impede os demais nem a recovery de buffers orfaos de rodarem no mesmo tick).

    Cada check e uma funcao SINCRONA que faz 2-4 round-trips HTTP via supabase-py —
    chamada direta bloquearia o event loop INTEIRO (webhooks, typing, timers de
    buffer) pela duracao da chamada; com o Supabase degradado (timeout de ate 120s),
    um unico tick travaria o processo por minutos e ate o shutdown ficaria preso
    esperando essa chamada sincrona retornar. `asyncio.to_thread` roda o check numa
    thread do executor default — o event loop nunca bloqueia em I/O de check, e o
    cancelamento (`asyncio.CancelledError`) e entregue no proprio `await`, entao o
    `except asyncio.CancelledError: raise` abaixo volta a ser significativo (uma
    chamada sincrona direta nunca seria cancelada no meio). `get_supabase()` ja e
    thread-local por design (app/db/supabase.py) — nao precisa de guarda extra aqui.
    """
    logger.info("[WATCHDOG] iniciado (intervalo=%ds)", WATCHDOG_INTERVAL_SECONDS)
    while True:
        if os.environ.get("REHEARSAL_MODE") == "true":
            await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
            continue

        now = datetime.now(timezone.utc)

        try:
            await asyncio.to_thread(check_ai_unresponsive, now)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[WATCHDOG] check check_ai_unresponsive falhou: %s", exc, exc_info=True)

        try:
            await asyncio.to_thread(check_orphan_lead_reply, now)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[WATCHDOG] check check_orphan_lead_reply falhou: %s", exc, exc_info=True)

        try:
            await asyncio.to_thread(check_stuck_followup_jobs, now)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[WATCHDOG] check check_stuck_followup_jobs falhou: %s", exc, exc_info=True)

        try:
            await recover_orphaned_buffers(app.state.redis, require_no_deadline=True, source="watchdog")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[WATCHDOG] recover_orphaned_buffers falhou: %s", exc, exc_info=True)

        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
