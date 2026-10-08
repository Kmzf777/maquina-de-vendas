# backend/app/conversions/sweep.py
"""Varredura: lê o banco e enfileira em `ad_conversions` o que for elegível.

Varredura (e não trigger no banco) de propósito: venda lançada pelo Bling cai num lead
duplicado sem clique, que só é mesclado depois (caso "Jovens com uma missão", call de 01/10).
Relendo a cada 30 min, a venda entra assim que for movida para o lead certo. A idempotência é
da `dedupe_key` UNIQUE + upsert com ignore_duplicates: rodar de novo nunca duplica.
"""
import dataclasses
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.conversions.eligibility import (
    WINDOW, Click, attributed_click, build_dedupe_key, build_event_id, clicks_from_entradas,
    clicks_from_lead_fallback, parse_ts, qualified_handoff_ok, segment_for, stage_allowed,
)
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# A maior janela (Google, 90 dias): nada mais velho que isso ainda pode ser enviado.
LOOKBACK = WINDOW["google"]
PLATFORMS = ("meta", "google")
_PAGE = 1000   # teto de linhas por resposta do PostgREST
_CHUNK = 200   # ids por `.in_()`: 200 uuids ≈ 8 KB de URL, o limite seguro do repo
_TZ_BR = timezone(timedelta(hours=-3))
_OPP_QUOTE_STATUS = ["enviado", "aprovado", "convertido"]


def _ts(v: Any) -> datetime | None:
    """`parse_ts` que nunca devolve datetime sem fuso: um valor sem fuso (gravação antiga ou
    manual) é lido como UTC. Comparar naive com aware estoura TypeError e derrubaria a varredura."""
    at = parse_ts(v)
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at


def _aware(c: Click) -> Click:
    return c if c.click_at.tzinfo else dataclasses.replace(c, click_at=c.click_at.replace(tzinfo=timezone.utc))


def _sendable(platform: str, click: Click, event_at: datetime, now: datetime) -> bool:
    """Mesma regra de janela que o sender reaplica antes de enviar: a Meta recusa `event_time`
    com mais de 7 dias; o Google recusa clique com mais de 90. Enfileirar o que já está fora
    só encheria a aba de `fora_da_janela`."""
    if platform == "meta":
        return now - event_at <= WINDOW["meta"]
    return now - click.click_at <= WINDOW["google"]


def _quote_at(q: dict[str, Any]) -> datetime | None:
    """`quotes.quoted_at` é DATE (a data do documento), sem hora. Usa a hora exata de
    `created_at` quando o orçamento é do mesmo dia (ou retroativo); se foi datado para depois,
    a meia-noite (Brasília) do dia do orçamento — nunca um instante antes de ele existir."""
    criado = _ts(q.get("created_at"))
    inicio = None
    dia = q.get("quoted_at")
    if dia:
        try:
            d = dia if isinstance(dia, date) and not isinstance(dia, datetime) else date.fromisoformat(str(dia)[:10])
            inicio = datetime(d.year, d.month, d.day, tzinfo=_TZ_BR)
        except ValueError:
            inicio = None
    cands = [x for x in (criado, inicio) if x is not None]
    return max(cands) if cands else None


def opportunity_from(quotes: list[dict[str, Any]], propostas: list[dict[str, Any]]) -> datetime | None:
    """Hora da oportunidade (§5 da spec): a PRIMEIRA entre orçamento enviado/aprovado/convertido
    e entrada de um deal na etapa `proposta_enviada`."""
    ats = [_quote_at(q) for q in quotes] + [_ts(p.get("occurred_at")) for p in propostas]
    ats = [a for a in ats if a is not None]
    return min(ats) if ats else None


def _row(*, lead: dict, platform: str, stage: str, click: Click, event_at: datetime, segment: str,
         value: float | None, sale_id: str | None = None) -> dict[str, Any]:
    # Todas as linhas com as MESMAS chaves: o upsert em lote do PostgREST manda `?columns=` com a
    # união das chaves e completa a que faltar com null.
    return {
        "lead_id": lead["id"],
        "platform": platform,
        "stage": stage,
        "sale_id": sale_id,
        "click_id": click.click_id,
        "click_id_type": click.click_id_type,
        "click_at": click.click_at.isoformat(),
        "campaign_name": click.campaign_name,
        "dedupe_key": build_dedupe_key(platform, stage, click.click_id, sale_id),
        "event_at": event_at.isoformat(),
        "event_id": build_event_id(stage, lead["id"], click.click_id, sale_id),
        "segment": segment,
        "value": value,
        "currency": "BRL",
        "status": "pendente",
    }


def build_candidates(*, lead: dict[str, Any], entradas: list[dict[str, Any]], sales: list[dict[str, Any]],
                     opportunity_at: datetime | None, values: dict[tuple[str, str], float],
                     now: datetime) -> list[dict[str, Any]]:
    """Linhas candidatas de UM lead (puro). Regras da §5 da spec:

    - `lead` é o próprio clique: um evento por clique, só na plataforma dele;
    - qualificado/oportunidade/venda vão para o clique atribuído (o mais recente da plataforma
      antes do evento, dentro da janela clique→evento);
    - já era cliente → só venda; venda cancelada não entra;
    - evento fora da janela de envio (ou ainda no futuro) não é enfileirado;
    - uma linha por `dedupe_key`.
    """
    clicks = clicks_from_entradas(entradas)
    clicks += clicks_from_lead_fallback(lead, clicks)
    # Ordem cronológica: o mesmo ID repetido em duas entradas fica com a hora do 1º clique.
    clicks = sorted((_aware(c) for c in clicks), key=lambda c: c.click_at)
    segment = segment_for(lead.get("stage"))
    ja_cliente = lead.get("ja_era_cliente")

    # (stage, event_at, value, sale_id, clique próprio — só no `lead`)
    eventos: list[tuple[str, datetime, float | None, str | None, Click | None]] = []
    for c in clicks:
        eventos.append(("lead", c.click_at, values.get((segment, "lead")), None, c))
    handoff = (lead.get("metadata") or {}).get("handoff")
    if qualified_handoff_ok(handoff):
        at = _ts(handoff["at"])
        if at:
            eventos.append(("qualified", at, values.get((segment, "qualified")), None, None))
    opp = _ts(opportunity_at)
    if opp:
        eventos.append(("opportunity", opp, values.get((segment, "opportunity")), None, None))
    for s in sales:
        if (s.get("status") or "").strip().lower() == "cancelada":
            continue
        at = _ts(s.get("sold_at"))
        if at and s.get("id"):
            valor = float(s["value"]) if s.get("value") is not None else None
            eventos.append(("purchase", at, valor, s["id"], None))

    out: dict[str, dict[str, Any]] = {}
    for stage, event_at, value, sale_id, own_click in eventos:
        if not stage_allowed(stage, ja_cliente) or event_at > now:
            continue  # futuro (orçamento datado para amanhã): entra numa rodada seguinte
        for platform in PLATFORMS:
            if own_click is not None:
                click = own_click if own_click.platform == platform else None
            else:
                click = attributed_click(clicks, platform, event_at)
            if click is None or not _sendable(platform, click, event_at, now):
                continue
            r = _row(lead=lead, platform=platform, stage=stage, click=click, event_at=event_at,
                     segment=segment, value=value, sale_id=sale_id)
            out.setdefault(r["dedupe_key"], r)
    return list(out.values())


# ── I/O ─────────────────────────────────────────────────────────────────────

def _paged(query_factory) -> list[dict[str, Any]]:
    """Pagina com `.range()` até vir página incompleta. A query precisa de `.order()` estável,
    senão o Postgres pode repetir/pular linhas entre páginas."""
    rows: list[dict[str, Any]] = []
    i = 0
    while True:
        page = query_factory().range(i, i + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        i += _PAGE


def _chunks(ids: list[str]):
    for i in range(0, len(ids), _CHUNK):
        yield ids[i:i + _CHUNK]


def _candidate_lead_ids(sb, since: str) -> list[str]:
    """Leads com clique nos últimos 90 dias: pela linha do tempo e, para o lead que nunca ganhou
    `entrada`, pelos IDs de clique gravados no próprio lead."""
    ids = {r["lead_id"] for r in _paged(
        lambda: sb.table("lead_events").select("lead_id")
        .eq("event_type", "entrada").gte("occurred_at", since).order("id")) if r.get("lead_id")}
    ids |= {r["id"] for r in _paged(
        lambda: sb.table("leads").select("id").gte("created_at", since)
        .or_("ctwa_clid.not.is.null,gclid.not.is.null,gbraid.not.is.null,wbraid.not.is.null")
        .order("id")) if r.get("id")}
    return sorted(ids)


def _by_lead(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[r.get("lead_id")].append(r)
    return out


def run_sweep(now: datetime | None = None) -> int:
    """Enfileira o que for elegível. Retorna quantas linhas foram oferecidas ao upsert (as que já
    existiam são ignoradas pelo banco)."""
    now = now or datetime.now(timezone.utc)
    since = (now - LOOKBACK).isoformat()
    sb = get_supabase()
    values = {(v["segment"], v["stage"]): float(v["value"])
              for v in (sb.table("ad_conversion_values").select("segment,stage,value").execute().data or [])}
    lead_ids = _candidate_lead_ids(sb, since)
    total = novos = falhas = 0
    for bloco in _chunks(lead_ids):
        leads = _paged(lambda: sb.table("leads").select(
            "id,stage,ja_era_cliente,metadata,created_at,ctwa_clid,gclid,gbraid,wbraid"
        ).in_("id", bloco).order("id"))
        # Todas as entradas do lead, sem corte de data: o clique atribuído é o mais recente
        # ANTES do evento, e o filtro de janela é do build_candidates.
        entradas = _by_lead(_paged(lambda: sb.table("lead_events").select("id,lead_id,occurred_at,metadata")
                                   .eq("event_type", "entrada").in_("lead_id", bloco).order("id")))
        sales = _by_lead(_paged(lambda: sb.table("sales").select("id,lead_id,sold_at,value,status")
                                .in_("lead_id", bloco).gte("sold_at", since).order("id")))
        quotes = _by_lead(_paged(lambda: sb.table("quotes").select("id,lead_id,status,quoted_at,created_at")
                                 .in_("lead_id", bloco).in_("status", _OPP_QUOTE_STATUS).order("id")))
        propostas = _by_lead(_paged(lambda: sb.table("lead_events").select("id,lead_id,occurred_at")
                                    .eq("event_type", "etapa").eq("metadata->>para_key", "proposta_enviada")
                                    .in_("lead_id", bloco).order("id")))

        rows: list[dict[str, Any]] = []
        for lead in leads:
            lid = lead["id"]
            try:
                rows += build_candidates(
                    lead=lead,
                    entradas=entradas.get(lid, []),
                    sales=sales.get(lid, []),
                    opportunity_at=opportunity_from(quotes.get(lid, []), propostas.get(lid, [])),
                    values=values,
                    now=now,
                )
            except Exception:
                # Um registro com dado inesperado não pode travar a fila de todos os outros.
                falhas += 1
                logger.exception("[CONVERSOES] varredura: falha ao montar candidatos do lead %s", lid)
        if rows:
            res = sb.table("ad_conversions").upsert(rows, on_conflict="dedupe_key", ignore_duplicates=True).execute()
            total += len(rows)
            # Com ignore-duplicates o PostgREST devolve só as linhas de fato inseridas.
            if isinstance(getattr(res, "data", None), list):
                novos += len(res.data)
    logger.info("[CONVERSOES] varredura: %d leads, %d candidatos, %d novos na fila, %d leads com falha",
                len(lead_ids), total, novos, falhas)
    return total
