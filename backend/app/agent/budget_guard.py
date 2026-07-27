"""Trava de orçamento diário (kill-switch) para chamadas ao LLM.

Protege contra fuga financeira: se o gasto acumulado do dia (UTC) em `token_usage`
ultrapassar o teto configurado, novas chamadas ao LLM são bloqueadas. O orchestrator
converte esse bloqueio no MESMO fallback do llm_down (encaminhar_humano ao João), então
o lead nunca é fantasmado — só deixa de queimar cota.

Configuração (env):
    LLM_DAILY_COST_LIMIT_USD   teto de custo/dia em USD. Default (env ausente) = 8 USD
    (~3x o pico diário observado em 07/2026 — FinOps P0, 12/07: o kill-switch nasceu
    desarmado e o runaway do rolling_summary queimou ~R$149 antes de detecção manual).
    `0` explícito DESLIGA o kill-switch.

Fonte de verdade: soma de `token_usage.total_cost` do dia corrente (UTC). Cache in-process
curto (_CACHE_TTL_SECS) evita uma query por chamada. FAIL-OPEN: qualquer erro de leitura
NÃO bloqueia — nunca derrubamos o atendimento por causa do medidor.

Observação: como `completion_tokens` agora inclui os thoughts_token_count (gemini_native),
`total_cost` passou a refletir o custo de output real, tornando este teto mais fiel.
"""
import logging
import os
import time
from datetime import datetime, timezone, timedelta

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_CACHE_TTL_SECS = 30
_cache: dict = {"day": None, "spend": 0.0, "at": 0.0}

# Eixo mensal (wartime 27/07): TTL longo — a soma do mês se move devagar e a query
# varre o mês inteiro, então ela não pode rodar a cada turno.
_MONTH_CACHE_TTL_SECS = 300
_month_cache: dict = {"month": None, "spend": 0.0, "at": 0.0}

# Dedup in-process dos alertas de budget (wartime T2, 10/07): 1 alerta/dia (UTC).
# A flag é checada ANTES de qualquer query — is_exceeded() roda no caminho quente de
# TODA chamada ao LLM e não pode ganhar custo de banco por causa do alarme.
# `autoresolve_day` marca o dia em que o auto-resolve da virada já rodou (1x/dia).
_alert_state: dict = {
    "exceeded_day": None, "warning_day": None, "autoresolve_day": None,
    # Eixo mensal: dedup por MÊS (não por dia) — o incidente dura o mês inteiro.
    "monthly_month": None,
}


def daily_cost_limit_usd() -> float:
    """Teto diário em USD lido do env. <= 0 explícito (ou inválido) desliga o kill-switch;
    env AUSENTE arma o default de 8 USD (FinOps P0, 12/07)."""
    try:
        return float(os.environ.get("LLM_DAILY_COST_LIMIT_USD", "8") or 0)
    except (TypeError, ValueError):
        return 0.0


def _today_utc() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d"), now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def today_spend_usd(force: bool = False) -> float:
    """Gasto do dia (UTC) somado de token_usage.total_cost, com cache curto. Fail-open → 0.0."""
    day, start = _today_utc()
    now = time.time()
    if not force and _cache["day"] == day and (now - _cache["at"]) < _CACHE_TTL_SECS:
        return _cache["spend"]
    try:
        sb = get_supabase()
        res = sb.table("token_usage").select("total_cost").gte("created_at", start).execute()
        spend = sum(float(r.get("total_cost") or 0) for r in (res.data or []))
    except Exception as exc:  # fail-open: medidor nunca bloqueia atendimento
        logger.warning("[BUDGET] falha ao ler gasto do dia — fail-open: %s", exc)
        return 0.0
    _cache.update(day=day, spend=spend, at=now)
    return spend


def monthly_alert_limit_usd() -> float:
    """Limiar de aviso do gasto MENSAL em USD. `0` explícito desliga.

    Eixo distinto do teto diário (wartime 27/07): no incidente de 19-27/07 a Valéria
    ficou 5 dias muda porque o teto MENSAL do provedor (Google AI Studio) estourou —
    e o guard diário nunca viu nada, porque o gasto de cada dia (~US$1-3) estava
    confortavelmente abaixo dos US$8 diários. Um teto mensal do provedor é atingido
    pela SOMA, não pelo pico: sem este eixo, o estouro é invisível até a IA emudecer.

    Default US$40 — ~2x o consumo real medido em 07/2026 (US$21,58/mês). Nasce ARMADO
    de propósito: o kill-switch diário nasceu desarmado e custou ~R$149 num runaway
    (FinOps P0, 12/07). Ajuste para ~80% do teto configurado no provedor.
    """
    try:
        return float(os.environ.get("LLM_MONTHLY_ALERT_USD", "40") or 0)
    except (TypeError, ValueError):
        return 0.0


def _this_month_utc() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m"), start.isoformat()


def month_spend_usd(force: bool = False) -> float:
    """Gasto do mês corrente (UTC) somado de token_usage.total_cost. Fail-open → 0.0.

    Cache mais longo que o diário: o número se move devagar e a query varre o mês
    inteiro — não pode entrar no caminho quente a cada turno.
    """
    month, start = _this_month_utc()
    now = time.time()
    if not force and _month_cache["month"] == month and (now - _month_cache["at"]) < _MONTH_CACHE_TTL_SECS:
        return _month_cache["spend"]
    try:
        sb = get_supabase()
        res = sb.table("token_usage").select("total_cost").gte("created_at", start).execute()
        spend = sum(float(r.get("total_cost") or 0) for r in (res.data or []))
    except Exception as exc:  # fail-open: medidor nunca bloqueia atendimento
        logger.warning("[BUDGET] falha ao ler gasto do mês — fail-open: %s", exc)
        return 0.0
    _month_cache.update(month=month, spend=spend, at=now)
    return spend


def fire_monthly_warning(spend: float, limit: float) -> None:
    """Aviso preventivo de gasto mensal. Dedup: 1x/mês in-process + 24h no banco."""
    month, _ = _this_month_utc()
    if _alert_state["monthly_month"] == month:
        return
    _alert_state["monthly_month"] = month
    pct = (spend / limit * 100) if limit > 0 else 0.0
    _fire_alert_deduped(
        "llm_monthly_budget_warning",
        "warning",
        "Gasto mensal de LLM cruzou o limiar de aviso",
        (
            f"Gasto do mês US${spend:.2f} atingiu {pct:.0f}% do limiar US${limit:.2f}. "
            "ATENÇÃO: o teto de gasto do provedor (Google AI Studio) é MENSAL e, ao "
            "estourar, a IA para de responder até a virada do mês — foi o que deixou a "
            "Valéria muda de 19 a 27/07/2026. Confira o teto em https://ai.studio/spend "
            "e ajuste LLM_MONTHLY_ALERT_USD para ~80% dele."
        ),
    )


def check_monthly_budget() -> None:
    """Avalia o eixo mensal e alerta se cruzou o limiar. Fail-soft, nunca levanta."""
    limit = monthly_alert_limit_usd()
    if limit <= 0:
        return
    spend = month_spend_usd()
    if spend >= limit:
        logger.warning(
            "[BUDGET] gasto MENSAL US$%.2f >= limiar US$%.2f — risco de estourar o teto "
            "do provedor (a IA emudece até a virada do mês).", spend, limit,
        )
        fire_monthly_warning(spend, limit)


def _fire_alert_deduped(alert_type: str, severity: str, title: str, message: str) -> None:
    """Cria o alerta com dedup no banco: 1 não-resolvido/24h (padrão fire_billing_alert).

    Segunda camada de dedup — protege contra multiprocessos (api + worker compartilham
    o mesmo teto, cada um com sua flag in-process). Fail-soft: se o check de dedup
    falhar, seguimos para a criação (melhor alerta duplicado que alerta nenhum);
    qualquer erro aqui é engolido — o alarme nunca pode derrubar o medidor.
    """
    try:
        from app.alerts.service import create_system_alert
        try:
            sb = get_supabase()
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            existing = (
                sb.table("system_alerts")
                .select("id")
                .eq("type", alert_type)
                .eq("resolved", False)
                .gte("created_at", cutoff)
                .limit(1)
                .execute()
            )
            if existing.data:
                return  # já existe alerta aberto nas últimas 24h — não duplica
        except Exception as exc:
            logger.warning("[BUDGET] falha no dedup de alerta %s (criando mesmo assim): %s", alert_type, exc)
        create_system_alert(alert_type, title, message, severity=severity)
    except Exception as exc:
        logger.warning("[BUDGET] falha ao disparar alerta %s (seguindo sem): %s", alert_type, exc)


def fire_budget_alert(spend: float, limit: float) -> None:
    """Alerta CRITICAL do trip do kill-switch — a ÚNICA sinalização do estouro.

    (O processor suprime o alerta llm_down quando reason="budget", então esta mensagem
    precisa ser autossuficiente: o que aconteceu, até quando, e o que o sistema está
    fazendo com os leads enquanto isso.) Dedup: flag in-process 1x/dia + banco 24h.
    """
    day, _ = _today_utc()
    if _alert_state["exceeded_day"] == day:
        return  # já alertado hoje — caminho quente sai sem tocar no banco
    _alert_state["exceeded_day"] = day
    _fire_alert_deduped(
        "llm_budget_exceeded",
        "critical",
        "Teto diário de LLM estourado — kill-switch ativado",
        (
            f"Gasto do dia US${spend:.2f} >= teto US${limit:.2f} — chamadas ao LLM bloqueadas "
            "até a virada do dia UTC; turnos estão sendo estacionados para retry automático "
            "(sem handoff cego dentro do prazo de reset). Para liberar antes, aumente "
            "LLM_DAILY_COST_LIMIT_USD e redeploy."
        ),
    )


def fire_budget_warning(spend: float, limit: float) -> None:
    """Aviso preventivo (warning) a >=80% do teto, sem trip. Dedup 1x/dia + banco 24h."""
    day, _ = _today_utc()
    if _alert_state["warning_day"] == day:
        return
    _alert_state["warning_day"] = day
    pct = (spend / limit * 100) if limit > 0 else 0.0
    _fire_alert_deduped(
        "llm_budget_warning",
        "warning",
        "Gasto de LLM em 80% do teto diário",
        (
            f"Gasto do dia US${spend:.2f} já atingiu {pct:.0f}% do teto US${limit:.2f}. "
            "Se estourar, o kill-switch bloqueia as chamadas até a virada do dia UTC."
        ),
    )


def _auto_resolve_on_new_day(day: str) -> None:
    """Virada do dia UTC com gasto < teto: resolve alertas llm_budget_* abertos.

    Detecção sem estado extra: a flag in-process de alerta pertence a um dia ANTERIOR
    ao corrente — logo o budget resetou e o incidente acabou. Roda no máximo 1x/dia
    (autoresolve_day) e é fail-soft: erro no update não afeta is_exceeded().
    """
    fired_day = _alert_state["exceeded_day"] or _alert_state["warning_day"]
    if not fired_day or fired_day == day:
        return  # nada alertado, ou o alerta é do dia corrente (incidente ainda vale)
    if _alert_state["autoresolve_day"] == day:
        return  # já resolvido hoje
    _alert_state["autoresolve_day"] = day
    _alert_state["exceeded_day"] = None
    _alert_state["warning_day"] = None
    try:
        sb = get_supabase()
        sb.table("system_alerts").update({
            "resolved": True,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }).in_("type", ["llm_budget_exceeded", "llm_budget_warning"]).eq("resolved", False).execute()
        logger.info("[BUDGET] virada do dia UTC — alertas llm_budget_* auto-resolvidos")
    except Exception as exc:
        logger.warning("[BUDGET] falha ao auto-resolver alertas de budget (seguindo sem): %s", exc)


def is_exceeded() -> bool:
    """True se o kill-switch está ligado (limite > 0) E o gasto do dia atingiu o teto."""
    limit = daily_cost_limit_usd()
    if limit <= 0:
        return False  # desligado — caminho quente sai sem tocar no banco
    spend = today_spend_usd()
    day, _ = _today_utc()
    if spend >= limit:
        logger.critical(
            "[BUDGET] KILL-SWITCH ATIVADO — gasto do dia US$%.2f >= teto US$%.2f. "
            "Bloqueando chamadas ao LLM (parking/fallback) ate a virada do dia (UTC).",
            spend, limit,
        )
        try:  # alarme é fail-soft por construção; o try é cinto-e-suspensório —
            fire_budget_alert(spend, limit)  # nada pode atrasar a resposta do guard
        except Exception as exc:
            logger.warning("[BUDGET] fire_budget_alert falhou (seguindo): %s", exc)
        return True
    try:
        _auto_resolve_on_new_day(day)
        if spend >= 0.8 * limit:
            fire_budget_warning(spend, limit)
        # Eixo mensal: o teto do PROVEDOR é mensal e não aparece no gasto diário.
        check_monthly_budget()
    except Exception as exc:
        logger.warning("[BUDGET] rotina de alerta/auto-resolve falhou (seguindo): %s", exc)
    return False
