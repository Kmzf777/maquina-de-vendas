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
# Tamanho de cada pagina do passo 1 (candidatas) dos Checks 1/2 — mantem cada query
# individual limitada mesmo sob volume alto.
CANDIDATE_PAGE_SIZE = 500
# Teto de seguranca de PAGINAS do passo 1 (ver _find_unanswered_conversations):
# CANDIDATE_MAX_PAGES * CANDIDATE_PAGE_SIZE = 5.000 msgs/24h, uma ordem de grandeza
# acima do volume atual. Antes da paginacao, uma UNICA pagina de 500 podia dar MISS
# completo — sob rajada, 500+ mensagens mais novas (de conversas ja respondidas)
# ocupavam toda a janela e uma conversa fantasma mais antiga (ainda sem resposta)
# nunca aparecia (finding do review final da Etapa 1). Se o teto de paginas for
# atingido, loga um warning — falso negativo aceito (mensagens mais antigas que o
# teto ficam de fora) em troca de nunca paginar sem fim.
CANDIDATE_MAX_PAGES = 10
# Tamanho de lote para .in_("id"/"conversation_id", ids) nos passos 2/3 — evita URL
# gigante quando a janela candidata tem 500+ conversation_ids distintos.
ID_CHUNK_SIZE = 100
# Teto de respostas buscadas POR CHUNK no passo 3 (replies). Direcao segura por
# construcao: combinado com `.order("created_at", desc=True)`, as respostas mais
# NOVAS ficam no topo — sao elas que CLAREIAM violacoes (timestamp > candidata).
# Truncar as mais antigas (fora do limit) so pode gerar falso positivo (alerta a
# mais para uma conversa que na verdade tem uma resposta antiga irrelevante), nunca
# esconder uma violacao real.
REPLIES_FETCH_LIMIT = 1000
# Teto de jobs presos por tick (Check 3) — mesma logica de limitar cada query.
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


def _chunked(seq: list, n: int):
    """Divide `seq` em fatias de tamanho `n` (a ultima fatia pode ser menor).

    Usado pelos passos 2/3 de `_find_unanswered_conversations` para evitar um unico
    `.in_()` com centenas/milhares de UUIDs (URL gigante).
    """
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


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
       Paginado em blocos de CANDIDATE_PAGE_SIZE (ate CANDIDATE_MAX_PAGES) — uma
       unica pagina podia dar MISS completo sob rajada (ver docstring da constante).
       A reducao "ultima msg por conversation_id" e feita em Python por max de
       `_parse_ts` sobre TODAS as paginas agregadas — e order-independent, entao a
       ordem de chegada das paginas nao afeta o resultado.
    2. Escopo: embeda conversations->channels/leads via `embed_select`; `scope_ok`
       decide se a conversa cai no escopo do check (ex.: canal de IA + IA ligada).
       `.in_("id", ids)` e feito em chunks de ID_CHUNK_SIZE (helper `_chunked`) para
       nao montar uma URL gigante quando ha centenas de candidatas.
    3. Respostas: ultima mensagem assistant/system por conversation_id dentro do
       escopo restante, tambem em chunks de ID_CHUNK_SIZE, cada chunk com
       `order desc + limit(REPLIES_FETCH_LIMIT)` (ver docstring da constante para a
       justificativa da direcao ser segura). Uma conversa esta violada quando NAO
       existe resposta com timestamp maior que o da sua mensagem candidata.

    Retorna a lista de `conversation_id` em violacao.
    """
    sb = get_supabase()
    lookback_cutoff = (now - timedelta(hours=AI_UNRESPONSIVE_LOOKBACK_HOURS)).isoformat()
    grace_cutoff = (now - timedelta(minutes=grace_minutes)).isoformat()

    # Passo 1 — candidatas, paginado.
    last_user_msg: dict = {}
    offset = 0
    for _ in range(CANDIDATE_MAX_PAGES):
        page_res = (
            sb.table("messages")
            .select("conversation_id, created_at")
            .eq("role", "user")
            .gte("created_at", lookback_cutoff)
            .lte("created_at", grace_cutoff)
            .order("created_at", desc=True)
            .range(offset, offset + CANDIDATE_PAGE_SIZE - 1)
            .execute()
        )
        page_rows = page_res.data or []
        for row in page_rows:
            conv_id = row["conversation_id"]
            ts = row["created_at"]
            if conv_id not in last_user_msg or _parse_ts(ts) > _parse_ts(last_user_msg[conv_id]):
                last_user_msg[conv_id] = ts
        if len(page_rows) < CANDIDATE_PAGE_SIZE:
            break  # pagina parcial/vazia = fim natural da janela
        offset += CANDIDATE_PAGE_SIZE
    else:
        # Consumiu as CANDIDATE_MAX_PAGES sem achar pagina parcial/vazia — pode
        # haver candidatas mais antigas ainda nao lidas (ver docstring da constante).
        logger.warning("[WATCHDOG] janela candidata truncada em %d páginas", CANDIDATE_MAX_PAGES)

    if not last_user_msg:
        return []

    # Passo 2 — escopo, em chunks.
    ids = list(last_user_msg.keys())
    scope_rows: list = []
    for chunk in _chunked(ids, ID_CHUNK_SIZE):
        chunk_res = (
            sb.table("conversations")
            .select(embed_select)
            .in_("id", chunk)
            .execute()
        )
        scope_rows.extend(chunk_res.data or [])
    ids_restantes = [row["id"] for row in scope_rows if scope_ok(row)]

    if not ids_restantes:
        return []

    # Passo 3 — respostas, em chunks (so precisa olhar a partir da candidata mais
    # antiga). Direcao segura por construcao: dentro de CADA chunk, `order desc +
    # limit(REPLIES_FETCH_LIMIT)` mantem as respostas mais NOVAS (as que clareiam
    # violacoes); truncar as mais antigas so pode gerar falso positivo, nunca
    # esconder uma violacao real (ver docstring de REPLIES_FETCH_LIMIT).
    min_candidate_ts = min((last_user_msg[cid] for cid in ids_restantes), key=_parse_ts)
    latest_reply: dict = {}
    for chunk in _chunked(ids_restantes, ID_CHUNK_SIZE):
        replies_res = (
            sb.table("messages")
            .select("conversation_id, created_at")
            .in_("conversation_id", chunk)
            .in_("role", ["assistant", "system"])
            .gte("created_at", min_candidate_ts)
            .order("created_at", desc=True)
            .limit(REPLIES_FETCH_LIMIT)
            .execute()
        )
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
        # Embed enxuto: scope_ok so le channels.mode e leads.ai_enabled — name/opt_out
        # nunca sao consumidos aqui (payload desnecessario sob paginacao/chunking).
        embed_select="id, channels!inner(mode), leads!inner(ai_enabled)",
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
        # Embed enxuto: scope_ok so le ai_enabled/human_control/opt_out — name nunca
        # e consumido aqui.
        embed_select="id, leads!inner(ai_enabled, human_control, opt_out)",
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
