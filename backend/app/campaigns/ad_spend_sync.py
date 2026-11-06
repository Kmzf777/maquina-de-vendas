"""Sync diário do investimento do Google Ads e Meta Ads para a tabela ad_spend (upsert idempotente).

Env-gated (no-op sem credenciais) e fail-soft. Rodado pelo tick diário do worker
(app/worker/main.py::_ad_spend_sync_tick) e sob demanda pelo botão Atualizar do /trafego;
o script scripts/sync_google_ads_spend.py continua disponível para rodar manualmente.

Fail-soft com RECIBO: um erro de API não derruba o worker, mas volta em `errors` para o botão
Atualizar. Sem isso, a versão v21 do Google Ads morreu em 11/08/2026 e o sync ficou dez dias
respondendo "0 linhas" como se fosse dia sem gasto — foi o que escondeu o bug."""
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.db.supabase import get_supabase
from app.campaigns.google_ads import fetch_campaign_spend, google_ads_enabled, AdsFetchError
from app.campaigns.meta_ads import (
    fetch_campaign_spend as meta_fetch_campaign_spend,
    fetch_ad_campaign_map,
    meta_ads_enabled,
)

logger = logging.getLogger(__name__)


def _window(days: int) -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


def _spend_rows(spend: list[dict], platform: str) -> list[dict]:
    now_iso = datetime.now(timezone.utc).isoformat()
    return [{
        "platform": platform,
        "campaign_id": r.get("campaign_id") or None,
        "campaign_name": r.get("campaign_name"),
        "date": r.get("date"),
        "cost": r.get("cost", 0.0),
        "currency": "BRL",
        "updated_at": now_iso,
    } for r in spend if r.get("campaign_name") and r.get("date")]


async def sync_google_ads_spend(days: int = 30) -> int:
    """Busca o spend dos últimos `days` dias e faz upsert em ad_spend. Retorna nº de linhas."""
    return (await _sync_google(days))[0]


async def _sync_google(days: int) -> tuple[int, str | None]:
    if not google_ads_enabled():
        logger.info("ad_spend_sync: Google Ads sem credenciais — no-op")
        return 0, None
    date_from, date_to = _window(days)
    try:
        spend = await fetch_campaign_spend(date_from, date_to)
    except AdsFetchError as exc:
        logger.error("ad_spend_sync: Google Ads falhou: %s", exc)
        return 0, str(exc)
    if not spend:
        logger.info("ad_spend_sync: nenhum spend retornado (%s..%s)", date_from, date_to)
        return 0, None
    try:
        rows = _spend_rows(spend, "google")
        get_supabase().table("ad_spend").upsert(rows, on_conflict="platform,campaign_id,date").execute()
        logger.info("ad_spend_sync: upsert de %d linhas (%s..%s)", len(rows), date_from, date_to)
        return len(rows), None
    except Exception as exc:
        logger.error("ad_spend_sync: falhou: %s", exc, exc_info=True)
        return 0, str(exc)


async def sync_meta_ads_spend(days: int = 30) -> int:
    """Busca o spend do Meta Ads e faz upsert em ad_spend (platform='meta'). Retorna nº de linhas."""
    return (await _sync_meta(days))[0]


async def _sync_meta(days: int) -> tuple[int, str | None]:
    if not meta_ads_enabled():
        logger.info("ad_spend_sync: Meta Ads sem credenciais — no-op")
        return 0, None
    date_from, date_to = _window(days)
    try:
        spend = await meta_fetch_campaign_spend(date_from, date_to)
    except AdsFetchError as exc:
        logger.error("ad_spend_sync(meta): falhou: %s", exc)
        return 0, str(exc)
    if not spend:
        logger.info("ad_spend_sync(meta): nenhum spend retornado (%s..%s)", date_from, date_to)
        return 0, None
    try:
        rows = _spend_rows(spend, "meta")
        get_supabase().table("ad_spend").upsert(rows, on_conflict="platform,campaign_id,date").execute()
        logger.info("ad_spend_sync(meta): upsert de %d linhas (%s..%s)", len(rows), date_from, date_to)
    except Exception as exc:
        logger.error("ad_spend_sync(meta): falhou: %s", exc, exc_info=True)
        return 0, str(exc)
    await _sync_meta_ad_map(date_from, date_to)
    return len(rows), None


async def _sync_meta_ad_map(date_from: str, date_to: str) -> int:
    """Upsert do mapa anúncio→campanha (meta_ad_campaigns). Fail-soft: erro aqui só degrada a
    atribuição por campanha do Meta; o investimento do canal não depende dele."""
    try:
        mapping = await fetch_ad_campaign_map(date_from, date_to)
        if not mapping:
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = [{
            "ad_id": m["ad_id"],
            "campaign_id": m["campaign_id"],
            "campaign_name": m.get("campaign_name") or "",
            "updated_at": now_iso,
        } for m in mapping]
        get_supabase().table("meta_ad_campaigns").upsert(rows, on_conflict="ad_id").execute()
        logger.info("ad_spend_sync(meta): mapa anúncio→campanha com %d entradas", len(rows))
        return len(rows)
    except Exception as exc:
        logger.error("ad_spend_sync(meta): mapa anúncio→campanha falhou: %s", exc)
        return 0


_TZ = ZoneInfo("America/Sao_Paulo")
_PLATAFORMAS = ("google", "meta")
_ALERTA_TIPO = "ad_spend_sync_failed"
DEDUP_HORAS = 12
_NOME = {"google": "Google Ads", "meta": "Meta Ads"}


def _habilitada(platform: str) -> bool:
    return google_ads_enabled() if platform == "google" else meta_ads_enabled()


def _zero_suspeito(platform: str, hoje: date | None = None) -> str | None:
    """0 linhas num dia útil com campanha ativa não é "dia sem gasto": foi assim que a v21 do
    Google morreu em 11/08/2026 sem ninguém ver. "Ativa" = houve gasto gravado em ad_spend nos
    últimos 7 dias. Devolve o motivo do aviso, ou None. Fail-soft (erro de leitura → None)."""
    hoje = hoje or datetime.now(_TZ).date()
    if hoje.weekday() >= 5:
        return None
    try:
        res = (get_supabase().table("ad_spend").select("date").eq("platform", platform)
               .gt("cost", 0).gte("date", (hoje - timedelta(days=7)).isoformat())
               .limit(1).execute())
    except Exception as exc:  # noqa: BLE001
        logger.warning("ad_spend_sync: checagem de zero suspeito falhou (%s): %s", platform, exc)
        return None
    if getattr(res, "data", None):
        return "API respondeu 0 linhas em dia útil, mas houve gasto nos últimos 7 dias"
    return None


def _registrar_rodada(platform: str, status: str, linhas: int, motivo: str | None,
                      origem: str) -> None:
    """Grava a rodada em ad_spend_sync_runs. Fail-soft: sem a tabela (migração ainda não
    aplicada) o sync segue igual, só sem o histórico."""
    try:
        get_supabase().table("ad_spend_sync_runs").insert({
            "platform": platform, "status": status, "linhas": linhas,
            "motivo": (motivo or None) and motivo[:500], "origem": origem,
        }).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ad_spend_sync: não gravou a rodada de %s: %s", platform, exc)


def ultimas_rodadas() -> dict[str, dict]:
    """Última rodada de cada plataforma: {plataforma: {status, linhas, motivo, em}}.
    Fail-soft: erro ou tabela ausente → {} (a tela só não mostra a linha)."""
    out: dict[str, dict] = {}
    for p in _PLATAFORMAS:
        try:
            res = (get_supabase().table("ad_spend_sync_runs")
                   .select("status,linhas,motivo,criado_em").eq("platform", p)
                   .order("criado_em", desc=True).limit(1).execute())
        except Exception as exc:  # noqa: BLE001
            logger.warning("ad_spend_sync: leitura das rodadas falhou (%s): %s", p, exc)
            continue
        if getattr(res, "data", None):
            r = res.data[0]
            out[p] = {"status": r.get("status"), "linhas": r.get("linhas"),
                      "motivo": r.get("motivo"), "em": r.get("criado_em")}
    return out


async def sync_all_ad_spend(days: int = 30, origem: str = "automatica") -> dict[str, object]:
    """Sincroniza Google + Meta (cada um env-gated/fail-soft) e grava cada rodada.

    Retorna {'google': n, 'meta': m, 'errors': {plataforma: motivo}, 'avisos': {plataforma:
    motivo}} — `errors` vazio significa que as APIs responderam; `avisos` marca 0 linhas
    suspeitas (dia útil com campanha ativa). 0 linhas sem erro nem aviso é dia sem gasto."""
    g, g_err = await _sync_google(days)
    m, m_err = await _sync_meta(days)
    errors: dict[str, str] = {}
    avisos: dict[str, str] = {}
    for platform, n, err in (("google", g, g_err), ("meta", m, m_err)):
        if err:
            errors[platform] = err
            _registrar_rodada(platform, "falha", 0, err, origem)
            continue
        if not _habilitada(platform):
            continue
        aviso = _zero_suspeito(platform) if n == 0 else None
        if aviso:
            avisos[platform] = aviso
            logger.warning("ad_spend_sync(%s): %s", platform, aviso)
        _registrar_rodada(platform, "aviso" if aviso else "ok", n, aviso, origem)
    return {"google": g, "meta": m, "errors": errors, "avisos": avisos}


def _ja_alertado(platform: str, horas: int = DEDUP_HORAS) -> bool:
    corte = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    res = (get_supabase().table("system_alerts").select("id")
           .eq("type", _ALERTA_TIPO).eq("resolved", False)
           .eq("metadata->>plataforma", platform)
           .gte("created_at", corte).limit(1).execute())
    return bool(getattr(res, "data", None))


def alertar_falhas(res: dict) -> list[str]:
    """Cria um system_alert por plataforma que falhou (ou voltou 0 linhas suspeitas), com dedup
    de 12 h por plataforma no estilo de bling/alertas.py. Devolve as plataformas alertadas.
    Nunca levanta: alerta não derruba o tick."""
    from app.alerts.service import create_system_alert
    alertadas: list[str] = []
    problemas = [(p, "falha", motivo) for p, motivo in (res.get("errors") or {}).items()]
    problemas += [(p, "aviso", motivo) for p, motivo in (res.get("avisos") or {}).items()]
    for platform, tipo, motivo in problemas:
        try:
            try:
                if _ja_alertado(platform):
                    continue
            except Exception:  # noqa: BLE001 — melhor alerta duplicado que nenhum
                logger.warning("ad_spend_sync: dedup do alerta falhou; gravando mesmo assim",
                               exc_info=True)
            nome = _NOME.get(platform, platform)
            titulo = (f"Investimento do {nome} não sincronizou" if tipo == "falha"
                      else f"Investimento do {nome} voltou zerado")
            create_system_alert(_ALERTA_TIPO, titulo, str(motivo), severity="warning",
                                metadata={"plataforma": platform, "motivo": str(motivo)[:500],
                                          "tipo": tipo})
            alertadas.append(platform)
        except Exception:  # noqa: BLE001
            logger.warning("ad_spend_sync: falha ao gravar o alerta de %s", platform, exc_info=True)
    return alertadas
