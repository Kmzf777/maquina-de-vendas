# backend/app/conversions/sender.py
"""Envia as linhas pendentes de `ad_conversions`.

Claim atômico por `claimed_at` (mesmo padrão de follow_up/scheduler._claim_followup_job):
duas réplicas do worker nunca enviam a mesma linha. Claim com mais de 10 min é considerado
abandonado (worker morreu no meio) e pode ser retomado — mas, na Meta, retomar NÃO reenvia: o
envio interrompido pode ter chegado e a Meta não deduplica (vira `erro` para conferência no
Gerenciador de Eventos). No Google é seguro reenviar (deduplica pelo `transactionId`).

Modo teste (`CONVERSIONS_TEST_MODE=true`): a Meta só mostra o evento em Test Events e o Google
só valida (`validateOnly`) — nada é registrado de verdade. Por isso um envio de teste NUNCA mexe
em `status` nem em `attempts`, dê certo ou errado: a linha continua `pendente`, o resultado fica
em `last_error`/`last_response` (marcado `modo_teste`) e ela sai de verdade quando o modo teste
for desligado.

Janela retroativa (`CONVERSIONS_BACKFILL_DAYS`, padrão 90): evento mais velho que ela vira
`fora_da_janela` sem envio. Simulação (`dry_run=True` / `simulate_sender`): conta o que sairia da
fila, sem claim, envio nem gravação.

Erro de credencial (`SendResult.auth_error`): disjuntor — a plataforma para no resto do tick e a
linha que bateu no erro não gasta tentativa (volta em 30 min). Token trocado, a fila segue.
"""
import logging
import os
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from app.conversions import google, meta
from app.conversions.eligibility import WINDOW, age_bucket, backfill_window, parse_ts
from app.conversions.types import SendResult
from app.db.paginacao import paginar
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

BACKOFF = (60, 300, 1800, 7200, 43200)  # 1 min, 5 min, 30 min, 2 h, 12 h; a 6ª falha vira erro
_STALE_CLAIM = timedelta(minutes=10)
# Em modo teste a mesma linha volta a ser testada só depois de 6 h (senão o tick de 5 min
# reenviaria a amostra inteira sem parar) e cada tick testa no máximo 10 — amostra basta.
TEST_MODE_PAUSE = timedelta(hours=6)
TEST_MODE_LIMIT = 10
AUTH_PAUSE = timedelta(minutes=30)
# A Meta recusa event_time com mais de 7 dias NA CHEGADA: 1 h de folga para request lento e
# relógio diferente (um evento fora derruba o request).
_META_MARGIN = timedelta(hours=1)
_SAVE_TRIES = 3
STALE_META_MSG = "envio interrompido — conferir no Gerenciador de Eventos antes de reenviar"
_STAGES = ("lead", "qualified", "opportunity", "purchase")
_CLIENTS = {"meta": meta, "google": google}
_sleep = time.sleep  # trocável nos testes


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _test_mode() -> bool:
    return (os.getenv("CONVERSIONS_TEST_MODE") or "").strip().lower() in ("1", "true", "yes", "on")


def outside_window(row: dict[str, Any], now: datetime, backfill: timedelta | None = None) -> bool:
    """Evento mais velho que a janela retroativa (`backfill`; padrão `backfill_window()`) não sai.
    Além disso: Meta recusa event_time > 7 dias antes do envio (aqui 7 d − 1 h de folga); Google
    recusa clique > 90 dias."""
    if now - parse_ts(row["event_at"]) > (backfill or backfill_window()):
        return True
    if row["platform"] == "meta":
        return now - parse_ts(row["event_at"]) > WINDOW["meta"] - _META_MARGIN
    return now - parse_ts(row["click_at"]) > WINDOW["google"]


def next_state(row: dict[str, Any], result: SendResult, now: datetime, *, test_mode: bool = False) -> dict[str, Any]:
    """Colunas a gravar na linha depois de um envio. Puro (sem I/O) para ser testável.

    Sem `status`/`attempts` no dict = a linha continua como estava (`pendente`, mesmas tentativas)."""
    resposta = {"modo_teste": True, "resposta": result.response} if test_mode else result.response
    if not result.ok and result.auth_error:
        # Credencial ruim não é culpa da linha: não gasta tentativa e volta em 30 min.
        return {"claimed_at": None, "last_error": result.error, "last_response": resposta,
                "next_attempt_at": (now + AUTH_PAUSE).isoformat()}
    if test_mode:
        # Teste não é envio real, nem quando dá erro: não consome a linha nem gasta tentativa.
        return {"claimed_at": None, "last_error": None if result.ok else result.error,
                "last_response": resposta, "next_attempt_at": (now + TEST_MODE_PAUSE).isoformat()}
    attempts = int(row.get("attempts") or 0) + 1
    upd: dict[str, Any] = {"attempts": attempts, "claimed_at": None, "last_response": result.response}
    if result.ok:
        upd.update(status="enviado", sent_at=now.isoformat(), last_error=None)
    elif result.permanent or attempts > len(BACKOFF):
        upd.update(status="erro", last_error=result.error)
    else:
        upd.update(status="pendente", last_error=result.error,
                   next_attempt_at=(now + timedelta(seconds=BACKOFF[attempts - 1])).isoformat())
    return upd


def _claim(sb, row_id: str, claim_at: datetime) -> bool:
    """UPDATE guardado por status + vencimento + claim livre/abandonado: só um processo vence a
    corrida. `claim_at` é a hora do próprio claim (não a do início do tick): outro worker pode ter
    reagendado a linha entre o select e aqui. Erro na query → False (não envia; o próximo tick
    tenta de novo) — nunca arrisca envio duplicado."""
    stale = (claim_at - _STALE_CLAIM).isoformat()
    try:
        res = sb.table("ad_conversions").update({"claimed_at": claim_at.isoformat()}) \
            .eq("id", row_id).eq("status", "pendente").lte("next_attempt_at", claim_at.isoformat()) \
            .or_(f"claimed_at.is.null,claimed_at.lt.{stale}").execute()
        return bool(res.data)
    except Exception as exc:
        logger.warning("[CONVERSOES] falha ao reivindicar %s: %s", row_id, exc)
        return False


def _stale_reclaim(row: dict[str, Any], claim_at: datetime) -> bool:
    """A linha estava reivindicada há mais de 10 min quando foi lida: um envio anterior foi
    interrompido no meio e o desfecho é desconhecido."""
    prev = parse_ts(row.get("claimed_at"))
    if prev is None:
        return False
    if prev.tzinfo is None:
        prev = prev.replace(tzinfo=timezone.utc)
    return claim_at - prev > _STALE_CLAIM


def _save(sb, row_id: str, upd: dict[str, Any]) -> bool:
    """Grava o resultado com até 3 tentativas. Se não gravar, a linha fica reivindicada; depois
    de 10 min ela é retomada — na Meta vira `erro` para conferência (não reenvia), no Google é
    reenviada (dedup pelo transactionId)."""
    last: Exception | None = None
    for i in range(_SAVE_TRIES):
        try:
            sb.table("ad_conversions").update(upd).eq("id", row_id).execute()
            return True
        except Exception as exc:  # noqa: BLE001 — qualquer falha do PostgREST
            last = exc
            if i < _SAVE_TRIES - 1:
                _sleep(0.5 * (i + 1))
    logger.error("[CONVERSOES] resultado de %s NÃO gravado após %d tentativas (%s): %s — a linha "
                 "fica reivindicada; na Meta será marcada erro ao ser retomada (conferir no Gerenciador "
                 "de Eventos), no Google será reenviada", row_id, _SAVE_TRIES, upd, last)
    return False


def _adiar_plataforma(sb, platform: str) -> None:
    """Disjuntor: empurra de uma vez as linhas vencidas e livres da plataforma para daqui a 30 min,
    para não ficarem girando a cada tick (nem gastam tentativa)."""
    agora = _utcnow()
    try:
        sb.table("ad_conversions").update({"next_attempt_at": (agora + AUTH_PAUSE).isoformat()}) \
            .eq("platform", platform).eq("status", "pendente").lte("next_attempt_at", agora.isoformat()) \
            .is_("claimed_at", "null").execute()
    except Exception as exc:  # noqa: BLE001 — o adiamento é otimização; o tick já parou a plataforma
        logger.warning("[CONVERSOES] falha ao adiar as linhas de %s: %s", platform, exc)


def _send(row: dict[str, Any], lead: dict[str, Any]) -> SendResult:
    """Exceção inesperada do cliente (linha malformada, bug) vira falha transitória: entra no
    backoff e acaba em `erro`, em vez de deixar a linha presa no claim e reenviada a cada 10 min."""
    try:
        return _CLIENTS[row["platform"]].send(row, lead)
    except Exception as exc:
        logger.exception("[CONVERSOES] exceção ao enviar %s", row.get("id"))
        return SendResult(ok=False, permanent=False, error=f"exceção: {exc!r}"[:500])


def _ready_platforms() -> list[str]:
    """Plataformas ligadas E configuradas. Ligada sem configuração (variável faltando, modo teste
    da Meta sem código de teste) é pulada inteira: nenhuma linha é reivindicada nem gasta
    tentativa, e o aviso se repete no log A CADA tick enquanto faltar. Ao configurar, a fila sai
    sozinha."""
    prontas = []
    for p, c in _CLIENTS.items():
        if not c.enabled():
            continue
        falta = c.missing_config()
        if falta:
            logger.warning("[CONVERSOES] %s ligada mas sem configuração (%s): nada sai da fila",
                           p, ", ".join(falta))
            continue
        prontas.append(p)
    return prontas


def _google_stages() -> list[str]:
    """Etapas do Google com ação configurada. As outras ficam na fila sem ser reivindicadas (o
    aviso se repete a cada tick)."""
    prontas = [s for s in _STAGES if google.action_configured(s)]
    faltam = [google._action_env(s) for s in _STAGES if s not in prontas]
    if faltam:
        logger.warning("[CONVERSOES] google: sem %s — as linhas dessas etapas ficam na fila",
                       ", ".join(faltam))
    return prontas


def simulate_sender(now: datetime | None = None, platforms: tuple[str, ...] = ("meta", "google"),
                    google_stages: list[str] | None = None, backfill_days: int | None = None) -> dict[str, Any]:
    """Dry-run: o que sairia da fila agora (pendente e vencido), sem claim, envio nem gravação.
    Pagina sem limite de lote: mostra o tamanho real do salto de uma ativação. Não exige a
    plataforma ligada (serve para simular ANTES de ligar)."""
    now = now or datetime.now(timezone.utc)
    backfill = backfill_window(backfill_days)
    sb = get_supabase()
    enviaria: Counter = Counter()
    fora = 0
    for platform in platforms:
        rows = paginar(lambda: sb.table("ad_conversions").select("id,platform,stage,event_at,click_at")
                       .eq("status", "pendente").eq("platform", platform)
                       .lte("next_attempt_at", now.isoformat()).order("id"))
        for r in rows:
            if platform == "google" and google_stages is not None and r["stage"] not in google_stages:
                continue
            if outside_window(r, now, backfill):
                fora += 1
            else:
                enviaria[(platform, r["stage"], age_bucket(now - parse_ts(r["event_at"])))] += 1
    return {"enviaria": dict(enviaria), "fora_da_janela": fora, "backfill_days": backfill.days}


def run_sender(now: datetime | None = None, limit: int = 100, dry_run: bool = False) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    platforms = _ready_platforms()
    counts: dict[str, Any] = {"enviado": 0, "pendente": 0, "erro": 0, "fora_da_janela": 0, "ignorado": 0}
    google_stages: list[str] = []
    if "google" in platforms:
        google_stages = _google_stages()
        if not google_stages:
            platforms.remove("google")
    if dry_run:
        # Simulação: nenhum claim, envio ou gravação — só a contagem do que sairia.
        sim = simulate_sender(now, platforms=tuple(platforms), google_stages=google_stages)["enviaria"]             if platforms else {}
        logger.info("[CONVERSOES][SIMULACAO] envio: %s", sim)
        return {**counts, "simulacao": sim}
    if not platforms:
        return counts
    backfill = backfill_window()
    test_mode = _test_mode()
    if test_mode:
        limit = min(limit, TEST_MODE_LIMIT)
    sb = get_supabase()
    # Uma consulta POR PLATAFORMA, cada uma com o seu limite: com um lote único, as linhas vencidas
    # de uma plataforma travada (disjuntor, etapa sem ação) ocupariam todas as vagas e a outra
    # nunca sairia — na Meta, até passar dos 7 dias e se perder.
    due: list[dict[str, Any]] = []
    for platform in platforms:
        q = sb.table("ad_conversions").select("*").eq("status", "pendente").eq("platform", platform)
        if platform == "google" and len(google_stages) < len(_STAGES):
            # Etapa sem ação não ocupa vaga do lote (senão 100 linhas dela travariam o Google).
            q = q.in_("stage", google_stages)
        due += q.lte("next_attempt_at", now.isoformat()).order("next_attempt_at").limit(limit).execute().data or []
    if not due:
        return counts
    lead_ids = sorted({r["lead_id"] for r in due})
    leads = {l["id"]: l for l in (sb.table("leads").select("id,email,phone,wa_id")
                                  .in_("id", lead_ids).execute().data or [])}
    sale_ids = sorted({r["sale_id"] for r in due if r.get("sale_id")})
    canceladas = set()
    if sale_ids:
        canceladas = {s["id"] for s in (sb.table("sales").select("id,status").in_("id", sale_ids)
                                        .execute().data or [])
                      if (s.get("status") or "").strip().lower() == "cancelada"}

    bloqueadas: set[str] = set()  # disjuntor: plataformas com erro de credencial neste tick
    for row in due:
        platform = row["platform"]
        if platform in bloqueadas:
            continue
        if platform == "google" and row.get("stage") not in google_stages:
            continue  # segunda trava do filtro da consulta
        claim_at = _utcnow()
        if not _claim(sb, row["id"], claim_at):
            continue
        if outside_window(row, now, backfill):
            upd = {"status": "fora_da_janela", "claimed_at": None}
        elif row.get("stage") == "purchase" and not row.get("sale_id"):
            # A venda foi apagada depois de enfileirada (FK `on delete set null`).
            upd = {"status": "ignorado", "claimed_at": None, "last_error": "venda removida antes do envio"}
        elif row.get("sale_id") in canceladas:
            upd = {"status": "ignorado", "claimed_at": None, "last_error": "venda cancelada antes do envio"}
        elif platform == "meta" and _stale_reclaim(row, claim_at):
            # Vale também em modo teste: o claim velho pode ser de um envio REAL anterior.
            logger.error("[CONVERSOES] meta %s %s: envio anterior interrompido (claim de %s) — não "
                         "reenvia; conferir no Gerenciador de Eventos", row["stage"], row["id"], row.get("claimed_at"))
            upd = {"status": "erro", "claimed_at": None, "last_error": STALE_META_MSG}
        else:
            result = _send(row, leads.get(row["lead_id"]) or {})
            upd = next_state(row, result, now, test_mode=test_mode)
            if not result.ok and result.auth_error:
                bloqueadas.add(platform)
                logger.error("[CONVERSOES] %s: erro de credencial (%s) — plataforma parada neste tick, "
                             "a linha %s não gasta tentativa", platform, result.error, row["id"])
                _adiar_plataforma(sb, platform)
            elif not result.ok:
                logger.warning("[CONVERSOES] %s %s %s falhou: %s", platform, row["stage"], row["id"], result.error)
        if _save(sb, row["id"], upd):
            counts[upd.get("status", "pendente")] += 1
    logger.info("[CONVERSOES] envio%s: %s", " (modo teste)" if test_mode else "", counts)
    return counts
