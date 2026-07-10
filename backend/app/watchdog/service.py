"""Watchdog fim-a-fim (Etapa 1 / A1).

Contexto: o apagao de producao (01-02/07) deixou leads ate 21h sem resposta com
mensagens salvas no banco e ZERO alertas. Os alertas ja existentes (llm_down,
billing) observam EXCECOES no caminho de execucao — se o processo morre em
silencio (timer morto, handoff incompleto, `[AGENT FAILED]` generico sem alerta),
nada dispara. Este modulo observa o BANCO (verdade fim-a-fim, independente de qual
bug matou o turno):

  - Check 1 `ai_unresponsive` (caso Welita): lead mandou mensagem num canal de IA
    com a IA ligada e ninguem respondeu.
  - Check 3 `followup_jobs_stuck`: jobs de follow-up pendentes com fire_at muito no
    passado — o scheduler parou de rodar.
  - Check 5 `handoff_sla_breach` (caso Juliana, 02/07): lead mandou mensagem no
    canal humano (pos-handoff, vendedor ja assumiu) e ficou mais de 20min sem
    resposta do vendedor. Cobre o caso em que "o Joao visualiza e nao responde"
    (human_control=true, o estado ESPERADO pos-handoff) — sem este check, ficaria
    1h46 invisivel, como aconteceu com a Juliana.
  - Check 6 `cadence_dead` (incidente 26/06→09/07): a Valeria conversou nas
    ultimas 24h mas NENHUM follow_up_job foi criado no periodo — a CRIACAO de
    jobs morreu (constraint 23514 engolida como warning por 13 dias). O Check 3
    nao enxerga essa classe porque ele so olha jobs que EXISTEM e estao presos;
    quando o insert falha, nao ha job nenhum para ficar preso.

Roda como task asyncio no lifespan de main.py, espelhando o padrao de run_flusher
(app/buffer/flusher.py): loop infinito, sleep entre ticks, cancelado no shutdown.
Cada check e uma funcao SINCRONA pura (testavel sem o loop); o isolamento de falha
(um check quebrado nao derruba os outros) e responsabilidade do loop, no
try/except por item.
"""
import asyncio
import logging
import os
from datetime import datetime, time, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from app.alerts.service import create_system_alert
from app.buffer.recovery import recover_orphaned_buffers
from app.config import get_settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# --- Constantes (sem numeros magicos inline) -----------------------------------
WATCHDOG_INTERVAL_SECONDS = 60
AI_UNRESPONSIVE_GRACE_MINUTES = 5
# Piso da janela de candidatas de _find_unanswered_conversations (helper compartilhado)
# -- leva o nome do Check 1 porque foi o caso motivador (Welita).
AI_UNRESPONSIVE_LOOKBACK_HOURS = 24
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

# --- Check 5 (handoff_sla_breach, caso Juliana 02/07) ---------------------------
# SLA de resposta HUMANA pos-handoff: quanto tempo uma msg do lead no canal humano
# pode ficar sem resposta do vendedor antes de virar alerta.
HANDOFF_SLA_MINUTES = 20
# Mesma logica do lookback dos Checks 1/2: limita a janela de deteccao para nao
# re-alertar violacoes antiquissimas (o dedup por conversa ja cobre re-alertas
# recentes; o lookback cobre o caso de uma conversa esquecida ha dias).
HANDOFF_SLA_LOOKBACK_HOURS = 24
# Dedup POR CONVERSA (nao global como ALERT_DEDUP_HOURS/_alert_recently_fired) —
# ver _handoff_sla_alerted_conversation_ids.
HANDOFF_SLA_DEDUP_HOURS = 2
# Janela util do check (8h-20h, America/Sao_Paulo): fora dela o vendedor humano nao
# esta necessariamente de plantao — o check retorna 0 SEM consultar o banco (evita
# ruido fora de hora e round-trips desnecessarios de madrugada).
SLA_WINDOW_START = time(8, 0)
SLA_WINDOW_END = time(20, 0)
_SP_TZ = ZoneInfo("America/Sao_Paulo")
# Teto explicito do fetch de conversas candidatas (Check 5 e uma unica query, sem a
# paginacao de 3 passos dos Checks 1/2 — ver _find_unanswered_conversations). Sem um
# predicado server-side em last_customer_message_at, o max-rows DEFAULT do PostgREST
# (~1000) truncaria silenciosamente sob volume alto — corte invisivel, nao um erro
# (review final da Etapa 1/Frente B). Os filtros `.not_.is_`/`.gte` abaixo reduzem o
# resultado ANTES desse teto (defesa primaria); os filtros Python de lookback/SLA/
# dedup permanecem como defesa em profundidade.
HANDOFF_SLA_FETCH_LIMIT = 1000

# --- Check 6 (cadence_dead, incidente 26/06→09/07) -------------------------------
# A cadencia 4-touch ficou MORTA por 13 dias (26/06→09/07): a constraint 23514
# fazia o INSERT em follow_up_jobs falhar como warning engolido — os jobs NUNCA
# eram criados, entao o Check 3 (followup_jobs_stuck), que olha jobs EXISTENTES com
# fire_at velho, nunca teve o que olhar. O detector correto e a COMBINACAO
# "operacao viva + zero criacao": mensagens `assistant` novas provam que a Valeria
# conversou (nao e um dia sem trafego), e zero linhas novas em follow_up_jobs no
# mesmo periodo provam que NENHUM caminho de agendamento (cadencia 4-touch,
# handoff_rescue, lp_welcome, ai_scheduled_return, nudge...) gravou nada — a
# assinatura exata dos 13 dias de silencio.
CADENCE_DEAD_LOOKBACK_HOURS = 24
# Dedup mais largo que o ALERT_DEDUP_HOURS global (1h): cadencia morta e um estado
# ESTRUTURAL que nao muda de hora em hora — 1 alerta nao-resolvido por 24h evita
# 12 criticals/dia (cada critical acorda WhatsApp+Sentry via T2) enquanto o fix
# nao sobe.
CADENCE_DEAD_DEDUP_HOURS = 24
# Teto do fetch do breakdown de jobs do QA diario (_qa_jobs_breakdown) — mesma
# disciplina dos outros fetches do watchdog: nunca uma query sem limite explicito.
# 2000 jobs/dia e uma ordem de grandeza acima do volume atual.
QA_JOBS_FETCH_LIMIT = 2000

# Mesmo padrao de app/follow_up/service.py:13 — escopa Check 3 ao ambiente atual
# (dev/production) para nao misturar jobs de teste com os reais.
_ENV_TAG = "dev" if get_settings().is_dev_env else "production"


def _parse_ts(value) -> datetime:
    """Converte um timestamp do Supabase (string ISO, sufixo `Z` ou `+00:00`, ou já
    um `datetime`) num `datetime` aware. NUNCA compare timestamps como string —
    offset e precisao de microsegundos variam entre linhas; sempre parseie antes.
    """
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _embed_one(value) -> dict:
    """Normaliza um embed to-one do PostgREST que pode voltar como dict OU como lista de
    1 elemento (a cardinalidade inferida varia entre relacionamentos/versões). Sempre
    devolve o dict subjacente (ou {} quando ausente/vazio) para o acesso `.get(...)` do
    scope_ok NUNCA estourar `AttributeError` num shape de lista.

    Bug real (auditoria 04/07): o Check 1 (`ai_unresponsive`) fazia
    `(row.get("channels") or {}).get("mode")`; quando `channels` voltava como
    `[{"mode": "ai"}]`, o `.get` estourava e derrubava o check INTEIRO a cada tick
    (engolido pelo try/except do loop) — por isso ele nunca disparou em produção (0
    alertas) apesar de violações reais como a do Alessandro (IA ligada, 4h sem resposta).
    """
    if isinstance(value, list):
        return value[0] if value else {}
    return value or {}


def _chunked(seq: list, n: int):
    """Divide `seq` em fatias de tamanho `n` (a ultima fatia pode ser menor).

    Usado pelos passos 2/3 de `_find_unanswered_conversations` para evitar um unico
    `.in_()` com centenas/milhares de UUIDs (URL gigante).
    """
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _alert_recently_fired(alert_type: str, dedup_hours: int = ALERT_DEDUP_HOURS) -> bool:
    """True se ja existe um alerta `alert_type` NAO resolvido criado nas ultimas
    `dedup_hours` horas (default: ALERT_DEDUP_HOURS=1, o padrao dos checks 1/3).

    Dedup espelhando o padrao de `processor._fire_llm_down_alert` /
    `alerts.service.fire_billing_alert`. `dedup_hours` existe para alertas de
    estado ESTRUTURAL (ex.: `cadence_dead`, dedup de 24h) que nao devem re-alertar
    a cada hora. Fail-open: erro ao consultar -> False (nao bloqueia o alerta —
    foi o silencio, nao um alerta duplicado, que deixou o apagao de 01-02/07
    invisivel).
    """
    try:
        sb = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=dedup_hours)).isoformat()
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


# Passo 1 tem dois caminhos: a RPC agregada (get_last_user_msg_per_conversation,
# 1 linha/conversa) e o fallback paginado historico. `_RPC_AGG_DISABLED` evita
# re-tentar (e re-logar) a RPC a cada tick quando ela nao existe/falha: a primeira
# falha desliga a RPC pela vida do processo e passamos a usar so o fallback ate o
# proximo restart (que ocorre no deploy, ja com a migration aplicada). O fallback e
# correto por construcao, entao desligar a RPC e conservador — nunca perigoso.
_RPC_AGG_DISABLED = False


def _last_user_msg_via_rpc(sb, since_iso: str, until_iso: str):
    """Ultima msg do contato por conversa via agregacao no Postgres (GROUP BY).

    Retorna {conversation_id: created_at_iso} em sucesso, ou None para sinalizar
    "indisponivel — use o fallback paginado". NUNCA levanta: qualquer erro (funcao
    ausente/PGRST202, rede, cache de schema) vira None. Preserva a janela
    [since, until] e e mais completa que a paginacao (sem teto de linhas).
    """
    global _RPC_AGG_DISABLED
    if _RPC_AGG_DISABLED:
        return None
    try:
        res = sb.rpc(
            "get_last_user_msg_per_conversation",
            {"p_since": since_iso, "p_until": until_iso},
        ).execute()
        return {r["conversation_id"]: r["last_user_at"] for r in (res.data or [])}
    except Exception as exc:
        _RPC_AGG_DISABLED = True
        logger.warning(
            "[WATCHDOG] RPC de agregacao indisponivel (%s) — fallback paginado ate o "
            "proximo restart; aplique 20260707_watchdog_last_user_msg_rpc.sql",
            type(exc).__name__,
        )
        return None


def _last_user_msg_paginated(sb, since_iso: str, until_iso: str) -> dict:
    """Fallback historico (rede de seguranca): le candidatas paginadas e reduz ao
    max(created_at) por conversation_id em Python. Caminho coberto pelos testes de
    paginacao — mantido integralmente."""
    last_user_msg: dict = {}
    offset = 0
    for _ in range(CANDIDATE_MAX_PAGES):
        page_res = (
            sb.table("messages")
            .select("conversation_id, created_at")
            .eq("role", "user")
            .gte("created_at", since_iso)
            .lte("created_at", until_iso)
            # Tiebreaker (review P3 minor): duas mensagens com o MESMO created_at
            # (comum em bursts inseridos no mesmo milissegundo) nao tem ordem
            # garantida so por created_at — sem uma chave secundaria deterministica,
            # a mesma linha pode aparecer em duas paginas OU sumir entre elas quando
            # o offset avanca. `id` (PK, unico) fecha o empate de forma estavel.
            .order("created_at", desc=True)
            .order("id", desc=True)
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
    return last_user_msg


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

    # Passo 1 — última mensagem do contato por conversa na janela.
    # Preferimos a agregação server-side (RPC get_last_user_msg_per_conversation):
    # devolve 1 linha/conversa em vez de ler até 5.000 linhas cruas por tick — o
    # maior corte de egress do backend. A RPC é semanticamente idêntica ao loop
    # paginado (é o mesmo GROUP BY) e mais completa (sem o teto de páginas). Se ela
    # não existir ainda (migration não aplicada) ou falhar, caímos no caminho
    # paginado histórico — a rede de segurança NUNCA depende da RPC estar lá.
    last_user_msg = _last_user_msg_via_rpc(sb, lookback_cutoff, grace_cutoff)
    if last_user_msg is None:
        last_user_msg = _last_user_msg_paginated(sb, lookback_cutoff, grace_cutoff)

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
            _embed_one(row.get("channels")).get("mode") == "ai"
            and _embed_one(row.get("leads")).get("ai_enabled") is True
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


def check_stuck_followup_jobs(now: datetime) -> int:
    """Check 3 — jobs de follow-up pendentes com fire_at muito no passado (scheduler parado)."""
    sb = get_supabase()
    cutoff = (now - timedelta(hours=STUCK_JOB_HOURS)).isoformat()
    # Inclui 'processing' além de 'pending': desde o claim atômico do follow-up
    # (scheduler._claim_followup_job) um job pode ficar preso em 'processing' se o worker
    # morrer após reivindicar. A crash-recovery devolve p/ 'pending' após 5min, MAS se o
    # próprio worker estiver morto ela não roda — então 'processing' antigo também sinaliza
    # scheduler parado e não pode ficar invisível a este check.
    res = (
        sb.table("follow_up_jobs")
        .select("id, job_type, fire_at")
        .in_("status", ["pending", "processing"])
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


def _within_sla_window(now: datetime) -> bool:
    """True se `now` (UTC) cai na janela util do Check 5 (SLA_WINDOW_START-
    SLA_WINDOW_END, America/Sao_Paulo). Fora dela, `check_handoff_sla` retorna 0 SEM
    tocar o banco — fora desse horario o vendedor humano nao esta necessariamente de
    plantao, e alertar so geraria ruido (alem de round-trips desnecessarios ao
    Supabase de madrugada).
    """
    local = now.astimezone(_SP_TZ)
    return SLA_WINDOW_START <= local.time() < SLA_WINDOW_END


def _handoff_sla_alerted_conversation_ids(now: datetime) -> set:
    """Conversation_ids ja cobertos por um alerta `handoff_sla_breach` criado nas
    ultimas HANDOFF_SLA_DEDUP_HOURS horas — QUALQUER `resolved` (diferente do dedup
    global dos outros checks, `_alert_recently_fired`, que so olha resolved=False e
    trata o alerta inteiro como uma unidade). Aqui o dedup e POR CONVERSA: uma
    conversa ja alertada recentemente (resolvida ou nao) nao deve re-alertar a cada
    tick, mas isso nao pode silenciar uma conversa NOVA que viola no mesmo tick —
    foi exatamente esse tipo de silencio (1h46 sem nenhum alerta) que deixou o caso
    Juliana (02/07) invisivel. Fail-open: erro na leitura -> conjunto vazio (nunca
    suprime um alerta por falha de infra).
    """
    try:
        sb = get_supabase()
        cutoff = (now - timedelta(hours=HANDOFF_SLA_DEDUP_HOURS)).isoformat()
        existing = (
            sb.table("system_alerts")
            .select("metadata")
            .eq("type", "handoff_sla_breach")
            .gte("created_at", cutoff)
            .execute()
        )
        ids: set = set()
        for row in existing.data or []:
            md = row.get("metadata") or {}
            ids.update(md.get("conversation_ids") or [])
        return ids
    except Exception as exc:
        logger.warning(
            "[WATCHDOG] falha ao checar dedup por conversa de handoff_sla_breach: %s", exc
        )
        return set()


def _last_customer_message_is_reaction(sb, conversation_id: str) -> bool:
    """True se a ÚLTIMA mensagem do lead nesta conversa é uma REAÇÃO (👍 etc.).

    Reação após a resposta do vendedor é encerramento social, não pergunta pendente —
    contá-la como "mensagem sem resposta" gera SLA falso (caso Nayara 10/07: 👍 no
    áudio do João disparou handoff_sla_breach 80min depois). Consultada SÓ para
    conversas já em violação (N pequeno). Fail-open: erro → False (na dúvida o alerta
    fica — ruído é melhor que a cegueira que escondeu o caso Juliana).
    """
    try:
        res = (
            sb.table("messages")
            .select("message_type")
            .eq("conversation_id", conversation_id)
            .eq("role", "user")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return bool(res.data) and res.data[0].get("message_type") == "reaction"
    except Exception as exc:
        logger.warning(
            "[WATCHDOG] falha ao checar reação-tail conv=%s: %s — fail-open",
            conversation_id, exc,
        )
        return False


def check_handoff_sla(now: datetime) -> int:
    """Check 5 (caso Juliana, 02/07) — SLA de resposta HUMANA pos-handoff.

    Juliana mandou mensagem no canal do Joao (pos-handoff, vendedor ja assumiu a
    conversa) e ficou 1h46 sem resposta — "o Joao visualiza e nao responde" — e
    ZERO alertas dispararam. Este e o caso do pos-handoff: human_control=true e o
    estado ESPERADO (a ponte da Frente B1), entao um lead que responde ao vendedor
    e fica sem retorno so e visto por este check, que fecha a lacuna observando
    diretamente as colunas `conversations.last_customer_message_at`/
    `last_seller_response_at` (mantidas por fluxo/trigger ja existentes — nao
    precisa ler `messages`).

    So roda dentro da janela util (ver `_within_sla_window`) — fora dela retorna 0
    sem consultar o banco. Retorna o total de conversas em violacao (dedup por
    conversa so decide o que entra no ALERTA, nao o que e reportado aqui — mesmo
    contrato dos Checks 1/2/`_alert_recently_fired`).
    """
    if not _within_sla_window(now):
        return 0

    lookback_floor = now - timedelta(hours=HANDOFF_SLA_LOOKBACK_HOURS)
    sla_threshold = timedelta(minutes=HANDOFF_SLA_MINUTES)

    # Push-down server-side (review final da Etapa 1/Frente B, Item 3): sem estes
    # filtros a query trazia TODA conversa em canal humano, sujeita ao corte
    # silencioso do max-rows do PostgREST (~1000) sob volume alto — ver
    # HANDOFF_SLA_FETCH_LIMIT. `.not_.is_` descarta quem nunca recebeu mensagem do
    # cliente (equivalente ao `if not raw_customer_ts: continue` abaixo, so que
    # antes do limit) e `.gte` aplica o MESMO piso de lookback usado no filtro
    # Python logo a seguir — os filtros Python continuam rodando (defesa em
    # profundidade: nunca dependa so do predicado do banco).
    sb = get_supabase()
    res = (
        sb.table("conversations")
        .select(
            "id, lead_id, last_customer_message_at, last_seller_response_at, "
            "channels!inner(mode), leads!inner(name)"
        )
        .eq("channels.mode", "human")
        .not_.is_("last_customer_message_at", "null")
        .gte("last_customer_message_at", lookback_floor.isoformat())
        .limit(HANDOFF_SLA_FETCH_LIMIT)
        .execute()
    )

    violated: list[str] = []
    lead_names: dict[str, str] = {}
    for row in res.data or []:
        raw_customer_ts = row.get("last_customer_message_at")
        if not raw_customer_ts:
            continue
        customer_ts = _parse_ts(raw_customer_ts)
        if customer_ts < lookback_floor:
            continue
        if now - customer_ts <= sla_threshold:
            continue
        raw_seller_ts = row.get("last_seller_response_at")
        if raw_seller_ts and _parse_ts(raw_seller_ts) >= customer_ts:
            continue  # vendedor respondeu DEPOIS da ultima msg do lead — ok
        conv_id = row["id"]
        if _last_customer_message_is_reaction(sb, conv_id):
            continue  # 👍 pos-resposta e encerramento social, nao pergunta pendente
        violated.append(conv_id)
        lead_names[conv_id] = ((row.get("leads") or {}).get("name") or "").strip()

    n = len(violated)
    if n:
        logger.warning("[WATCHDOG] handoff_sla_breach: %d conversa(s) em violacao", n)
        already_alerted = _handoff_sla_alerted_conversation_ids(now)
        new_violations = [cid for cid in violated if cid not in already_alerted]
        if new_violations:
            first_names = [
                lead_names[cid].split()[0] for cid in new_violations if lead_names.get(cid)
            ]
            example = ", ".join(first_names[:3]) if first_names else "sem nome"
            create_system_alert(
                "handoff_sla_breach",
                "Lead aguardando resposta humana pós-handoff",
                f"{len(new_violations)} conversa(s) no canal humano com mensagem do "
                f"lead sem resposta há mais de {HANDOFF_SLA_MINUTES}min (ex.: {example}). "
                "Casos reais: Juliana 02/07 ('o João visualiza e não responde').",
                severity="warning",
                metadata={"conversation_ids": new_violations[:10]},
            )
    return n


def check_cadence_dead(now: datetime) -> int:
    """Check 6 (incidente 26/06→09/07) — a criação de follow_up_jobs morreu.

    A cadência 4-touch ficou 13 dias sem rodar porque uma constraint (23514) fazia
    o INSERT em follow_up_jobs falhar como warning engolido: os jobs nunca eram
    CRIADOS, então o Check 3 (que olha jobs existentes presos há 2h) nunca disparou.
    Este check observa a assinatura correta — operação viva + zero criação:

      (a) janela útil 08h-20h America/Sao_Paulo (mesma do Check 5): de madrugada é
          normal não criar job, e um critical acordaria o operador à toa;
      (b) existe pelo menos 1 mensagem `assistant` nas últimas 24h — a Valéria
          conversou, então os caminhos que agendam follow-up TIVERAM oportunidade;
      (c) ZERO linhas criadas em follow_up_jobs (env atual) no mesmo período.

    Fail-open no sentido de NÃO alertar: diferente do dedup (onde o silêncio era o
    inimigo), uma falha transitória de query aqui não é evidência de cadência morta
    — alertar critical em cima de erro de leitura seria falso positivo (e o
    critical do T2 dispara WhatsApp+Sentry). Erro de query → loga warning, retorna 0.

    Retorna o nº de alertas criados neste tick (0 ou 1 — o dedup de 24h decide).
    """
    if not _within_sla_window(now):
        return 0

    cutoff = (now - timedelta(hours=CADENCE_DEAD_LOOKBACK_HOURS)).isoformat()
    try:
        sb = get_supabase()
        alive = (
            sb.table("messages")
            .select("id")
            .eq("role", "assistant")
            .gte("created_at", cutoff)
            .limit(1)
            .execute()
        )
        if not alive.data:
            return 0  # dia sem tráfego — sem operação viva não há sinal de cadência morta
        jobs = (
            sb.table("follow_up_jobs")
            .select("id")
            .eq("env_tag", _ENV_TAG)
            .gte("created_at", cutoff)
            .limit(1)
            .execute()
        )
        if jobs.data:
            return 0  # pelo menos 1 job criado na janela — a criação está viva
    except Exception as exc:
        logger.warning(
            "[WATCHDOG] check_cadence_dead: falha de query — sem alerta neste tick "
            "(fail-open): %s", exc
        )
        return 0

    logger.warning(
        "[WATCHDOG] cadence_dead: operação viva (assistant nas últimas %dh) e ZERO "
        "follow_up_jobs criados (env=%s)",
        CADENCE_DEAD_LOOKBACK_HOURS, _ENV_TAG,
    )
    if _alert_recently_fired("cadence_dead", dedup_hours=CADENCE_DEAD_DEDUP_HOURS):
        return 0
    create_system_alert(
        "cadence_dead",
        "Cadência de follow-up morta",
        f"A Valéria conversou nas últimas {CADENCE_DEAD_LOOKBACK_HOURS}h (há mensagens "
        f"assistant novas), mas ZERO jobs foram criados em follow_up_jobs no mesmo "
        f"período (env={_ENV_TAG}). Essa é a assinatura do incidente de 26/06→09/07, "
        "quando a constraint 23514 engoliu os INSERTs como warning por 13 dias e "
        "nenhum follow-up foi agendado. Verifique os caminhos de agendamento "
        "(cadência 4-touch, handoff_rescue, lp_welcome, ai_scheduled_return) e os "
        "warnings de INSERT nos logs do backend/worker.",
        severity="critical",
        metadata={
            "lookback_hours": CADENCE_DEAD_LOOKBACK_HOURS,
            "env_tag": _ENV_TAG,
        },
    )
    return 1


# --- QA diário de aderência (Onda 2, 09/07) --------------------------------------
# Janela de publicação (07:00-08:00 America/Sao_Paulo): 1 relatório D-1 por dia.
QA_WINDOW_START = time(7, 0)
QA_WINDOW_END = time(8, 0)


def _qa_already_published_today(now: datetime) -> bool:
    """True se já existe um daily_qa_report criado HOJE (dia BRT). Fail-open=True em
    erro de leitura: na dúvida NÃO republica (é telemetria, não segurança)."""
    try:
        local = now.astimezone(_SP_TZ)
        day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        res = (
            get_supabase().table("system_alerts")
            .select("id")
            .eq("type", "daily_qa_report")
            .gte("created_at", day_start.astimezone(timezone.utc).isoformat())
            .limit(1)
            .execute()
        )
        return isinstance(res.data, list) and bool(res.data)
    except Exception as exc:
        logger.warning("[WATCHDOG] dedup do daily_qa falhou: %s — não republica", exc)
        return True


def _qa_count(build_query) -> int:
    """Executa uma query count='exact' construída por `build_query(sb)`. -1 em falha
    (indicador quebrado não derruba o relatório)."""
    try:
        res = build_query(get_supabase()).execute()
        return int(res.count or 0)
    except Exception as exc:
        logger.warning("[WATCHDOG] métrica do daily_qa falhou: %s", exc)
        return -1


def _qa_jobs_breakdown(start: str, end: str):
    """Breakdown por `job_type` dos follow_up_jobs de D-1: CRIADOS (created_at na
    janela) e EXECUTADOS (status='sent' com sent_at na janela — 'sent' é o estado
    terminal de sucesso do scheduler, ver follow_up/scheduler._update_job_status).

    Motivação (incidente 26/06→09/07): o QA reportava só `followups_enviados`
    agregado — um tipo inteiro de job podia sumir (a cadência 4-touch morreu por 13
    dias) sem que o número agregado denunciasse. O histograma diário por tipo é o
    detector HUMANO de "um tipo sumiu"; o detector automático em tempo real é o
    check_cadence_dead. Retorna {job_type: {"criados": n, "executados": n}} ou -1
    em falha (padrão dos indicadores do QA: um indicador quebrado não derruba o
    relatório).
    """
    try:
        sb = get_supabase()
        created_rows = (
            sb.table("follow_up_jobs").select("job_type")
            .eq("env_tag", _ENV_TAG)
            .gte("created_at", start).lt("created_at", end)
            .limit(QA_JOBS_FETCH_LIMIT).execute()
        ).data or []
        sent_rows = (
            sb.table("follow_up_jobs").select("job_type")
            .eq("env_tag", _ENV_TAG)
            .eq("status", "sent")
            .gte("sent_at", start).lt("sent_at", end)
            .limit(QA_JOBS_FETCH_LIMIT).execute()
        ).data or []
        breakdown: dict = {}
        for row in created_rows:
            job_type = row.get("job_type") or "standard"
            slot = breakdown.setdefault(job_type, {"criados": 0, "executados": 0})
            slot["criados"] += 1
        for row in sent_rows:
            job_type = row.get("job_type") or "standard"
            slot = breakdown.setdefault(job_type, {"criados": 0, "executados": 0})
            slot["executados"] += 1
        return breakdown
    except Exception as exc:
        logger.warning("[WATCHDOG] breakdown de jobs do daily_qa falhou: %s", exc)
        return -1


def _fmt_jobs_breakdown(breakdown) -> str:
    """Renderiza o breakdown de jobs compacto p/ a mensagem do QA
    ("standard 12/10, handoff_rescue 3/3" = criados/executados). Tolerante a -1
    (indisponível, padrão dos indicadores) e a dict vazio (nenhum job no dia —
    sinal que o check_cadence_dead cobre em tempo real, não só no relatório)."""
    if not isinstance(breakdown, dict):
        return "indisponível (-1)"
    if not breakdown:
        return "nenhum"
    return ", ".join(
        f"{job_type} {counts['criados']}/{counts['executados']}"
        for job_type, counts in sorted(breakdown.items())
    )


def _qa_collect_metrics(now: datetime) -> dict:
    """Consolida os indicadores de D-1 (dia BRT anterior, convertido p/ UTC)."""
    local = now.astimezone(_SP_TZ)
    day_end_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_local = day_end_local - timedelta(days=1)
    start = day_start_local.astimezone(timezone.utc).isoformat()
    end = day_end_local.astimezone(timezone.utc).isoformat()

    def _msgs(q, **eqs):
        def build(sb):
            query = sb.table("messages").select("id", count="exact") \
                .gte("created_at", start).lt("created_at", end)
            for k, v in eqs.items():
                query = query.eq(k, v)
            if q:
                query = query.like("content", q)
            return query
        return build

    def _distinct_leads(like_pattern: str) -> int:
        """Leads DISTINTOS com o marcador na janela — imune a re-execuções do retry
        do agente (incidente 09/07: registrar_numero_errado gravado 4x no mesmo lead)."""
        try:
            res = (
                get_supabase().table("messages").select("lead_id")
                .eq("role", "system").like("content", like_pattern)
                .gte("created_at", start).lt("created_at", end)
                .limit(1000).execute()
            )
            rows = res.data if isinstance(res.data, list) else []
            return len({r.get("lead_id") for r in rows if r.get("lead_id")})
        except Exception as exc:
            logger.warning("[WATCHDOG] métrica distinct do daily_qa falhou: %s", exc)
            return -1

    return {
        "respostas_ia": _qa_count(_msgs(None, role="assistant", sent_by="agent")),
        "followups_enviados": _qa_count(_msgs(None, role="assistant", sent_by="followup")),
        "inbounds": _qa_count(_msgs(None, role="user")),
        # Só o marcador de handoff em si: cada encaminhar_humano grava DUAS system
        # messages ("Lead encaminhado..." + "cartão de contato enviado") — o LIKE
        # amplo dobrava a contagem (relatório de 10/07 mostrou 14 p/ 7 reais).
        "handoffs": _qa_count(_msgs("[encaminhar_humano] Lead encaminhado%", role="system")),
        "optouts": _qa_count(_msgs("[registrar_optout]%", role="system")),
        "numero_errado_marcados": _distinct_leads("[registrar_numero_errado]%"),
        "indicacoes": _qa_count(_msgs("[registrar_indicacao]%", role="system")),
        "perguntas_repetidas_corrigidas": _qa_count(
            lambda sb: sb.table("token_usage").select("id", count="exact")
            .eq("call_type", "response_retry")
            .gte("created_at", start).lt("created_at", end)
        ),
        "dossies_atualizados": _qa_count(
            lambda sb: sb.table("leads").select("id", count="exact")
            .not_.is_("rolling_summary", "null")
            .gte("rolling_summary_updated_at", start).lt("rolling_summary_updated_at", end)
        ),
        "disparos_enviados": _qa_count(
            lambda sb: sb.table("broadcast_leads").select("id", count="exact")
            .gte("sent_at", start).lt("sent_at", end)
        ),
        # Histograma diário de follow_up_jobs por tipo (criados/executados) — o
        # detector humano da classe "um job_type sumiu" (incidente 26/06→09/07).
        "jobs_por_tipo": _qa_jobs_breakdown(start, end),
    }


def check_daily_qa(now: datetime) -> bool:
    """Publica o relatório diário de QA conversacional (D-1) em system_alerts.

    Consolida os sinais que as guardas da Onda 1 espalham pelo banco (handoffs,
    opt-outs, correções de pergunta repetida, dossiês, disparos) num único alerta
    informativo por dia — o pulso de aderência que a auditoria de 08/07 teve que
    reconstruir na mão. Fora da janela 07-08h BRT retorna False SEM tocar o banco.
    """
    local = now.astimezone(_SP_TZ)
    if not (QA_WINDOW_START <= local.time() < QA_WINDOW_END):
        return False
    if _qa_already_published_today(now):
        return False
    metrics = _qa_collect_metrics(now)
    dia = (local - timedelta(days=1)).strftime("%d/%m/%Y")
    resumo = (
        f"QA diário {dia}: {metrics['respostas_ia']} respostas da IA e "
        f"{metrics['followups_enviados']} follow-ups para {metrics['inbounds']} mensagens de leads; "
        f"{metrics['handoffs']} handoffs, {metrics['optouts']} opt-outs, "
        f"{metrics['perguntas_repetidas_corrigidas']} perguntas repetidas corrigidas pela guarda; "
        f"{metrics['dossies_atualizados']} dossiês atualizados; "
        f"{metrics['disparos_enviados']} templates disparados; "
        f"{metrics['numero_errado_marcados']} números marcados como errados e "
        f"{metrics['indicacoes']} indicações registradas. "
        # Breakdown por job_type (criados/executados) — `.get` tolerante porque o
        # relatório não pode quebrar se a chave faltar num metrics antigo/parcial.
        f"Jobs 24h (criados/executados): {_fmt_jobs_breakdown(metrics.get('jobs_por_tipo', -1))}. "
        "(-1 = indicador indisponível)"
    )
    create_system_alert(
        "daily_qa_report",
        f"QA diário da Valéria — {dia}",
        resumo,
        severity="info",
        metadata={"metrics": metrics, "dia": dia},
    )
    logger.info("[WATCHDOG] daily_qa_report publicado (%s)", dia)
    return True


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
            await asyncio.to_thread(check_stuck_followup_jobs, now)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[WATCHDOG] check check_stuck_followup_jobs falhou: %s", exc, exc_info=True)

        try:
            await asyncio.to_thread(check_handoff_sla, now)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[WATCHDOG] check check_handoff_sla falhou: %s", exc, exc_info=True)

        try:
            await asyncio.to_thread(check_cadence_dead, now)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[WATCHDOG] check check_cadence_dead falhou: %s", exc, exc_info=True)

        try:
            await asyncio.to_thread(check_daily_qa, now)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[WATCHDOG] check check_daily_qa falhou: %s", exc, exc_info=True)

        try:
            await recover_orphaned_buffers(app.state.redis, require_no_deadline=True, source="watchdog")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[WATCHDOG] recover_orphaned_buffers falhou: %s", exc, exc_info=True)

        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
