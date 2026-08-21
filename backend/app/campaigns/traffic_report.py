"""Relatório de campanhas (/trafego): agrega leads por canal+campanha cruzando com vendas.

Funções puras (derive_channel, build_campaign_report) isoladas do I/O p/ teste.
As funções que tocam o banco (traffic_report, campaign_leads) são fail-soft.
"""
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.db.supabase import get_supabase

_TZ = ZoneInfo("America/Sao_Paulo")

# Tokens ignorados ao comparar utm_campaign com campaign_name do Google Ads.
# Extensões de anúncio (sitelink) são sufixos de variante, não identificam campanha.
_UTM_STOP_WORDS = frozenset({"sitelink"})


def _normalize_tokens(s: str) -> frozenset[str]:
    """Tokens significativos de uma string: sem acentos, sem números, sem separadores."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[|.\-\s_/]+", " ", s)
    return frozenset(
        t for t in s.split()
        if t and not re.match(r"^\d+$", t) and t not in _UTM_STOP_WORDS
    )


def _campaign_tokens(name: str) -> frozenset[str]:
    return _normalize_tokens(name)


def resolve_campaign_id(utm_campaign: str, utm_medium: str,
                        campaigns: dict[str, dict[str, Any]]) -> str | None:
    """Resolve um slug de utm_campaign para o campaign_id da plataforma. None = não resolvido.

    `campaigns` é {campaign_id: {"name": str, "tokens": frozenset, "cost": float}}.

    Regras, da mais forte para a mais fraca — e SEM chute:
      1. nome idêntico (normalizado) → vence direto;
      2. todos os tokens do slug cabem no nome da campanha (ou vice-versa). Um só candidato → vence;
      3. vários candidatos → o utm_medium desempata (medium=pmax casa "PMAX | Atacado", e é o que
         separa a Search da PMAX quando as duas se chamam "atacado");
      4. ainda empatado → vence o nome com MENOS tokens sobrando (match mais específico), e só
         se esse mínimo for único.
    Nada disso batendo, devolve None: o lead cai na linha "(não atribuído)". Preferimos uma
    linha honesta a espalhar investimento na campanha errada."""
    slug = (utm_campaign or "").strip().lower()
    if not slug or not campaigns:
        return None
    for cid, c in campaigns.items():
        if c["name"].strip().lower() == slug:
            return cid
    utm_tokens = _normalize_tokens(slug)
    if not utm_tokens:
        return None
    candidates = [
        cid for cid, c in campaigns.items()
        if c["tokens"] and (utm_tokens <= c["tokens"] or c["tokens"] <= utm_tokens)
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    medium_tokens = _normalize_tokens(utm_medium or "")
    if medium_tokens:
        by_medium = [cid for cid in candidates if medium_tokens & campaigns[cid]["tokens"]]
        if len(by_medium) == 1:
            return by_medium[0]
        if by_medium:
            candidates = by_medium
    extras = {cid: len(campaigns[cid]["tokens"] ^ utm_tokens) for cid in candidates}
    best = min(extras.values())
    winners = [cid for cid, n in extras.items() if n == best]
    return winners[0] if len(winners) == 1 else None


logger = logging.getLogger(__name__)

_NO_CAMPAIGN = "(sem campanha)"
_CLOSER_STAGE_KEY = "qualificado"


def _s(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


# Origens (utm_source) de anúncio pago, por plataforma. A gestora de tráfego tagueia a Meta
# como 'metaads' e o Google como 'google'. Usadas quando NÃO há click-id — ex.: anúncio Meta
# que leva ao WhatsApp (sem fbclid) ou Google PMAX sem gclid. NÃO incluir 'instagram'/
# 'facebook' crus: esses são o tráfego ORGÂNICO (ex.: link da bio, utm_medium=bio).
_META_AD_SOURCES: frozenset[str] = frozenset(
    {"metaads", "meta_ads", "meta-ads", "meta", "facebook_ads", "facebookads", "fb_ads"}
)
_GOOGLE_AD_SOURCES: frozenset[str] = frozenset({"google", "googleads", "google_ads", "adwords"})
# Meios (utm_medium) pagos — desambiguam utm_source=google pago (cpc/pmax) do SEO orgânico.
_PAID_CHANNEL_MEDIUMS: frozenset[str] = frozenset(
    {"cpc", "ppc", "pmax", "performance_max", "paid", "paid_search", "paidsearch",
     "display", "cpm", "paid_social", "paidsocial"}
)


def derive_channel(lead: dict[str, Any]) -> str:
    """Canal do lead. Prioridade: click-id > utm_source de anúncio > orgânico > sem rastreio.

    Meta e Google são detectados TAMBÉM por utm_source (a gestora tagueia 'metaads'/'google'),
    porque nem todo lead pago traz click-id (Meta→WhatsApp sem fbclid, PMAX sem gclid). Google
    exige um meio pago (cpc/pmax/…) para não confundir com SEO orgânico; 'metaads' é inequívoco.
    Retorna Google Ads/Meta Ads/Orgânico/Sem rastreio.
    """
    if _s(lead.get("gclid")):
        return "Google Ads"
    if _s(lead.get("fbclid")) or _s(lead.get("ctwa_clid")):
        return "Meta Ads"
    source = _s(lead.get("utm_source")).lower()
    medium = _s(lead.get("utm_medium")).lower()
    if source in _META_AD_SOURCES:
        return "Meta Ads"
    if source in _GOOGLE_AD_SOURCES and medium in _PAID_CHANNEL_MEDIUMS:
        return "Google Ads"
    if _s(lead.get("traffic_type")).lower() == "organic" or source:
        return "Orgânico"
    return "Sem rastreio"


_UNATTRIBUTED = "(não atribuído)"


def _index_campaigns(spend):
    """Normaliza o gasto da plataforma em {campaign_id: {name, tokens, cost}}.

    A chave é o campaign_id porque é o que garante que o gasto de uma campanha entre no
    relatório UMA vez só, por mais utm_campaign diferentes que apontem para ela."""
    out = {}
    if not spend:
        return out
    # Compat: {campaign_name: cost} (formato antigo) -> sintetiza um id a partir do nome.
    items = (
        [{"campaign_id": "", "campaign_name": n, "cost": c} for n, c in spend.items()]
        if isinstance(spend, dict) else spend
    )
    for r in items:
        name = (r.get("campaign_name") or "").strip()
        if not name:
            continue
        cid = str(r.get("campaign_id") or "") or "name:" + name.lower()
        slot = out.setdefault(cid, {"name": name, "tokens": _normalize_tokens(name), "cost": 0.0})
        try:
            slot["cost"] += float(r.get("cost") or 0.0)
        except (TypeError, ValueError):
            pass
    return out


def _new_row(channel, campaign):
    return {"channel": channel, "campaign": campaign, "leads": 0, "conversas": 0, "closer": 0,
            "clientes": 0, "pedidos": 0, "receita": 0.0, "investimento": 0.0}


def build_campaign_report(
    leads: list[dict[str, Any]],
    conversed_ids: set[str],
    closer_ids: set[str],
    sales_by_lead: dict[str, dict[str, Any]],
    mode: str,
    period: str,
    spend_by_channel: dict[str, Any] | None = None,
    campaign_id_by_lead: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Agrega os leads em linhas (canal, campanha). Puro — recebe coleções já buscadas.

    - conversed_ids / closer_ids: sets de lead_id que conversaram / chegaram ao closer.
    - sales_by_lead: lead_id -> {"count": int, "value": float} (já filtrado por modo).
    - spend_by_channel: canal -> [{campaign_id, campaign_name, cost}] vindo de ad_spend.
    - campaign_id_by_lead: lead_id -> campaign_id quando a própria plataforma nos deu o
      vínculo (Meta CTWA via anuncio). Vence qualquer casamento por nome.

    O eixo do relatório é a CAMPANHA DA PLATAFORMA, não o slug de utm. Cada campanha vira uma
    linha e recebe seu gasto exatamente uma vez; os vários utm_campaign que apontam para ela
    (ex.: 'terceirizacao' e 'leads_search_terceirizacao') somam leads na MESMA linha. Antes o
    gasto era puxado do lado do lead, então cada variante de slug cobrava o custo cheio da
    campanha de novo — o investimento do Google aparecia 2,6x maior do que foi gasto.

    Invariante: para cada canal pago, soma(linhas.investimento) == gasto real da plataforma
    na janela. Campanha que gastou sem gerar lead entra com leads=0 em vez de sumir."""
    spend_by_channel = spend_by_channel or {}
    campaign_id_by_lead = campaign_id_by_lead or {}
    campaigns_by_channel = {ch: _index_campaigns(sp) for ch, sp in spend_by_channel.items()}

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    # (canal, campaign_id) -> linha, para pendurar o custo depois sem depender do rótulo.
    row_by_campaign: dict[tuple[str, str], dict[str, Any]] = {}
    resolved_cache: dict[tuple[str, str, str], str | None] = {}

    for lead in leads:
        lead_id = lead.get("id")
        channel = derive_channel(lead)
        raw_campaign = _s(lead.get("utm_campaign"))
        campaigns = campaigns_by_channel.get(channel)
        cid = None
        if campaigns:
            platform_cid = campaign_id_by_lead.get(lead_id)
            if platform_cid and platform_cid in campaigns:
                cid = platform_cid
            else:
                medium = _s(lead.get("utm_medium"))
                ck = (channel, raw_campaign.lower(), medium.lower())
                if ck not in resolved_cache:
                    resolved_cache[ck] = resolve_campaign_id(raw_campaign, medium, campaigns)
                cid = resolved_cache[ck]
        if cid:
            key = (channel, "id:" + cid)
            label = campaigns[cid]["name"]
        elif campaigns:
            # Canal pago sem campanha resolvida: não se mistura com uma campanha real, mas
            # mantém o slug no rótulo quando existe — é a pista p/ corrigir o tagueamento.
            key = (channel, "un:" + raw_campaign.lower())
            label = (_UNATTRIBUTED + " · " + raw_campaign) if raw_campaign else _UNATTRIBUTED
        else:
            key = (channel, raw_campaign.lower() or _NO_CAMPAIGN)
            label = raw_campaign or _NO_CAMPAIGN
        row = groups.get(key)
        if row is None:
            row = _new_row(channel, label)
            groups[key] = row
            if cid:
                row_by_campaign[(channel, cid)] = row
        row["leads"] += 1
        if lead_id in conversed_ids:
            row["conversas"] += 1
        if lead_id in closer_ids:
            row["closer"] += 1
        sale = sales_by_lead.get(lead_id)
        if sale:
            row["clientes"] += 1  # leads distintos que compraram (base da conversão)
            row["pedidos"] += int(sale.get("count", 0) or 0)  # nº de vendas (recompra: pode ser >1)
            row["receita"] += float(sale.get("value", 0.0) or 0.0)

    # Investimento: percorre as CAMPANHAS (não os leads), então cada custo entra uma única vez.
    # Campanha que gastou e não gerou lead ganha uma linha zerada — sumir do relatório seria
    # subestimar o investimento do canal e inflar o ROAS.
    for channel, campaigns in campaigns_by_channel.items():
        for cid, c in campaigns.items():
            row = row_by_campaign.get((channel, cid))
            if row is None:
                row = _new_row(channel, c["name"])
                groups[(channel, "id:" + cid)] = row
                row_by_campaign[(channel, cid)] = row
            row["investimento"] = round(float(c["cost"]), 2)

    rows: list[dict[str, Any]] = []
    total = {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
             "receita": 0.0, "investimento": 0.0}
    paid_receita = 0.0
    for row in groups.values():
        pedidos = row["pedidos"]
        row["ticket_medio"] = round(row["receita"] / pedidos, 2) if pedidos else 0.0
        row["conversao"] = round(row["clientes"] / row["leads"], 4) if row["leads"] else 0.0
        inv = row["investimento"]
        row["roas"] = round(row["receita"] / inv, 2) if inv else None
        if row["channel"] in campaigns_by_channel:
            paid_receita += row["receita"]
        for k in total:
            total[k] += row[k]
        rows.append(row)

    channel_subtotals: dict[str, dict[str, Any]] = {}
    for row in rows:
        sub = channel_subtotals.get(row["channel"])
        if sub is None:
            sub = {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
                   "receita": 0.0, "investimento": 0.0}
            channel_subtotals[row["channel"]] = sub
        for k in sub:
            sub[k] += row[k]
    for sub in channel_subtotals.values():
        sub["receita"] = round(sub["receita"], 2)
        sub["investimento"] = round(sub["investimento"], 2)
        sub["roas"] = round(sub["receita"] / sub["investimento"], 2) if sub["investimento"] else None

    # Não atribuído por último dentro do canal: é sobra, não a leitura principal.
    rows.sort(key=lambda r: (r["channel"], r["campaign"].startswith(_UNATTRIBUTED),
                             -r["receita"], -r["investimento"], -r["leads"]))
    total["receita"] = round(total["receita"], 2)
    total["investimento"] = round(total["investimento"], 2)
    total["roas"] = round(paid_receita / total["investimento"], 2) if total["investimento"] else None
    return {"mode": mode, "period": period, "rows": rows, "total": total,
            "channel_subtotals": channel_subtotals}


_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}
_LEAD_COLS = ("id, name, phone, created_at, gclid, fbclid, ctwa_clid, "
              "utm_source, utm_medium, utm_campaign, traffic_type")


class _MetaAdCol:
    """Flag de processo: leads.meta_ad_id existe? Desligada na primeira falha de select."""
    enabled = True


def _lead_cols() -> str:
    return _LEAD_COLS + ", meta_ad_id" if _MetaAdCol.enabled else _LEAD_COLS
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _resolve_window(period: str, date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    """Resolve a janela (lo, hi) em ISO. `date_from`/`date_to` (YYYY-MM-DD) têm precedência
    sobre `period`. Datas malformadas são ignoradas. Sem sinal → (None, None) = tudo."""
    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    lo_explicit = df if _DATE_RE.match(df) else ""
    hi_explicit = dt if _DATE_RE.match(dt) else ""
    if lo_explicit or hi_explicit:
        lo = f"{lo_explicit}T00:00:00+00:00" if lo_explicit else None
        hi = f"{hi_explicit}T23:59:59.999999+00:00" if hi_explicit else None
        return lo, hi
    days = _PERIOD_DAYS.get(period)
    if not days:
        return None, None
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(), None


def _chunks(items: list, size: int = 200):
    for i in range(0, len(items), size):
        yield items[i:i + size]


_PAGE = 1000


def _fetch_all(build_query, page: int = _PAGE) -> list[dict[str, Any]]:
    """Executa a query paginando com .range() ate a pagina vir incompleta.

    O PostgREST corta a resposta em 1.000 linhas por padrao e NAO avisa: a query volta
    "com sucesso", so que truncada. Sem isso o /trafego lia 1.000 dos 2.324 leads da janela
    de 30 dias e reportava leads, receita e ROAS sobre 43% da base.

    `build_query` e chamado a cada pagina porque o postgrest-py acumula estado no builder."""
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        data = build_query().range(offset, offset + page - 1).execute().data or []
        out.extend(data)
        if len(data) < page:
            return out
        offset += page


def _fetch_leads(sb, mode: str, lo: str | None, hi: str | None) -> list[dict[str, Any]]:
    cols = _lead_cols()

    def _leads_in(chunk):
        return _fetch_all(lambda: sb.table("leads").select(cols).in_("id", chunk))

    if mode == "sale":
        def _sales_q():
            q = sb.table("sales").select("lead_id")
            if lo:
                q = q.gte("sold_at", lo)
            if hi:
                q = q.lte("sold_at", hi)
            return q
        sale_ids = sorted({r["lead_id"] for r in _fetch_all(_sales_q) if r.get("lead_id")})
        leads: list[dict[str, Any]] = []
        for chunk in _chunks(sale_ids):
            leads.extend(_leads_in(chunk))
        return leads

    def _q():
        q = sb.table("leads").select(cols)
        if lo:
            q = q.gte("created_at", lo)
        if hi:
            q = q.lte("created_at", hi)
        return q
    try:
        return _fetch_all(_q)
    except Exception as exc:
        # A coluna meta_ad_id vem de migration; se ela ainda nao foi aplicada o PostgREST
        # rejeita o select inteiro. Degrada para o conjunto base (perde so a atribuicao de
        # campanha do Meta) em vez de zerar o relatorio.
        if _MetaAdCol.enabled:
            logger.warning("traffic_report: select com meta_ad_id falhou (%s) - migration pendente?", exc)
            _MetaAdCol.enabled = False
            return _fetch_leads(sb, mode, lo, hi)
        raise


def _conversed_ids(sb, lead_ids: list[str]) -> set[str]:
    out: set[str] = set()
    for chunk in _chunks(lead_ids):
        rows = _fetch_all(lambda c=chunk: sb.table("conversations")
                          .select("lead_id, last_customer_message_at").in_("lead_id", c))
        for r in rows:
            if r.get("last_customer_message_at") and r.get("lead_id"):
                out.add(r["lead_id"])
    return out


def _closer_ids(sb, lead_ids: list[str]) -> set[str]:
    stages = _fetch_all(lambda: sb.table("pipeline_stages").select("id, pipeline_id, key, order_index"))
    stage_by_id = {s["id"]: s for s in stages}
    qualifica_idx: dict[str, int] = {
        s["pipeline_id"]: s["order_index"]
        for s in stages if s.get("key") == _CLOSER_STAGE_KEY and s.get("order_index") is not None
    }
    out: set[str] = set()
    for chunk in _chunks(lead_ids):
        deals = _fetch_all(lambda c=chunk: sb.table("deals")
                           .select("lead_id, stage_id, pipeline_id").in_("lead_id", c))
        for d in deals:
            stage = stage_by_id.get(d.get("stage_id"))
            if not stage or stage.get("order_index") is None:
                continue
            threshold = qualifica_idx.get(d.get("pipeline_id"))
            if threshold is not None and stage["order_index"] >= threshold:
                out.add(d["lead_id"])
    return out


def _sales_by_lead(sb, lead_ids: list[str], lo: str | None, hi: str | None, mode: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(lead_ids):
        def _q(c=chunk):
            q = sb.table("sales").select("lead_id, value, sold_at").in_("lead_id", c)
            if mode == "sale" and lo:
                q = q.gte("sold_at", lo)
            if mode == "sale" and hi:
                q = q.lte("sold_at", hi)
            return q
        for r in _fetch_all(_q):
            lid = r.get("lead_id")
            if not lid:
                continue
            agg = out.setdefault(lid, {"count": 0, "value": 0.0, "last_sold_at": None})
            agg["count"] += 1
            try:
                agg["value"] += float(r.get("value") or 0.0)
            except (TypeError, ValueError):
                pass
            # Track latest sale date via ISO string comparison (safe for ISO 8601 timestamps).
            sold_at = r.get("sold_at")
            if isinstance(sold_at, str) and sold_at:
                prev = agg["last_sold_at"]
                if prev is None or sold_at > prev:
                    agg["last_sold_at"] = sold_at
    return out


def _empty_report(mode: str, period: str) -> dict[str, Any]:
    return {"mode": mode, "period": period, "rows": [], "channel_subtotals": {},
            "total": {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
                      "receita": 0.0, "investimento": 0.0, "roas": None}}


def _spend_by_campaign(sb, lo: str | None, hi: str | None, platform: str = "google") -> list[dict[str, Any]]:
    """Gasto de ad_spend agregado por CAMPANHA (id), na janela. Fail-soft -> [].

    Devolve [{campaign_id, campaign_name, cost}] em vez de {nome: custo} porque o relatorio
    ancora as linhas no campaign_id: e o id que garante que o custo entre uma vez so."""
    try:
        def _q():
            q = sb.table("ad_spend").select("campaign_id, campaign_name, cost, date").eq("platform", platform)
            if lo:
                q = q.gte("date", lo[:10])
            if hi:
                q = q.lte("date", hi[:10])
            return q
        agg: dict[str, dict[str, Any]] = {}
        for r in _fetch_all(_q):
            name = (r.get("campaign_name") or "").strip()
            if not name:
                continue
            cid = str(r.get("campaign_id") or "") or "name:" + name.lower()
            slot = agg.setdefault(cid, {"campaign_id": cid, "campaign_name": name, "cost": 0.0})
            try:
                slot["cost"] += float(r.get("cost") or 0.0)
            except (TypeError, ValueError):
                pass
        return list(agg.values())
    except Exception as exc:
        logger.error("_spend_by_campaign falhou: %s", exc)
        return []


def _spend_by_channel(sb, lo: str | None, hi: str | None) -> dict[str, list[dict[str, Any]]]:
    return {
        "Google Ads": _spend_by_campaign(sb, lo, hi, "google"),
        "Meta Ads": _spend_by_campaign(sb, lo, hi, "meta"),
    }


def _meta_campaign_by_lead(sb, leads: list[dict[str, Any]]) -> dict[str, str]:
    """lead_id -> campaign_id do Meta, via o anuncio (meta_ad_id) que trouxe o lead.

    O webhook CTWA nao diz a campanha, so o anuncio (referral.source_id); o mapa
    anuncio->campanha vem do sync do Meta Ads. Sem esse elo os leads de CTWA nao tem
    utm_campaign nenhum e ficariam todos em "(nao atribuido)". Fail-soft -> {}."""
    ad_ids = sorted({_s(l.get("meta_ad_id")) for l in leads if _s(l.get("meta_ad_id"))})
    if not ad_ids:
        return {}
    try:
        camp_by_ad: dict[str, str] = {}
        for chunk in _chunks(ad_ids):
            rows = _fetch_all(lambda c=chunk: sb.table("meta_ad_campaigns")
                              .select("ad_id, campaign_id").in_("ad_id", c))
            for r in rows:
                if r.get("ad_id") and r.get("campaign_id"):
                    camp_by_ad[str(r["ad_id"])] = str(r["campaign_id"])
        out: dict[str, str] = {}
        for l in leads:
            cid = camp_by_ad.get(_s(l.get("meta_ad_id")))
            if cid and l.get("id"):
                out[l["id"]] = cid
        return out
    except Exception as exc:
        logger.warning("_meta_campaign_by_lead falhou (migration pendente?): %s", exc)
        return {}


def _empty_summary(channel: str, campaign: str) -> dict[str, Any]:
    return {"channel": channel, "campaign": campaign, "leads": 0, "conversas": 0, "closer": 0,
            "clientes": 0, "pedidos": 0, "receita": 0.0, "ticket_medio": 0.0, "conversao": 0.0,
            "investimento": 0.0, "roas": None}


def _local_day(iso: Any) -> "date | None":
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TZ).date()
    except (ValueError, TypeError):
        return None


def _daterange_days(lo: str | None, hi: str | None, max_days: int = 92) -> list[date]:
    end = _local_day(hi) or datetime.now(_TZ).date()
    start = _local_day(lo) or (end - timedelta(days=29))
    if (end - start).days + 1 > max_days:
        start = end - timedelta(days=max_days - 1)
    days: list[date] = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


def build_campaign_timeseries(days: list[date], leads: list[dict[str, Any]],
                              sales_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Série diária: leads por created_at, vendas/receita por sold_at. Dias sem evento = 0. Puro."""
    idx = {d.isoformat(): {"date": d.isoformat(), "leads": 0, "vendas": 0, "receita": 0.0} for d in days}
    for l in leads:
        d = _local_day(l.get("created_at"))
        if d is not None and d.isoformat() in idx:
            idx[d.isoformat()]["leads"] += 1
    for s in sales_rows:
        d = _local_day(s.get("sold_at"))
        if d is not None and d.isoformat() in idx:
            idx[d.isoformat()]["vendas"] += 1
            try:
                idx[d.isoformat()]["receita"] += float(s.get("value") or 0.0)
            except (TypeError, ValueError):
                pass
    return list(idx.values())


def campaign_detail(channel: str, campaign: str, period: str = "30d", mode: str = "lead",
                    date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    """Detalhe de uma campanha: {summary, leads, timeseries}. Fail-soft."""
    try:
        sb = get_supabase()
        lo, hi = _resolve_window(period, date_from, date_to)
        all_leads = _fetch_leads(sb, mode, lo, hi)
        selected = [
            l for l in all_leads
            if derive_channel(l) == channel and (_s(l.get("utm_campaign")) or _NO_CAMPAIGN) == campaign
        ]
        if not selected:
            return {"summary": _empty_summary(channel, campaign), "leads": [], "timeseries": []}
        lead_ids = [l["id"] for l in selected if l.get("id")]
        conversed = _conversed_ids(sb, lead_ids)
        closers = _closer_ids(sb, lead_ids)
        sales = _sales_by_lead(sb, lead_ids, lo, hi, mode)
        report = build_campaign_report(
            selected, conversed, closers, sales, mode, period,
            spend_by_channel=_spend_by_channel(sb, lo, hi),
            campaign_id_by_lead=_meta_campaign_by_lead(sb, selected),
        )
        # So a linha DESTA campanha interessa: as demais linhas vem das campanhas que
        # gastaram na janela sem lead selecionado (ver build_campaign_report).
        with_leads = [r for r in report.get("rows") or [] if r["leads"] > 0]
        summary = with_leads[0] if with_leads else _empty_summary(channel, campaign)
        leads = campaign_leads(channel, campaign, period, mode, date_from, date_to)
        sales_rows: list[dict[str, Any]] = []
        for chunk in _chunks(lead_ids):
            def _sq(c=chunk):
                q = sb.table("sales").select("value, sold_at").in_("lead_id", c)
                if mode == "sale" and lo:
                    q = q.gte("sold_at", lo)
                if mode == "sale" and hi:
                    q = q.lte("sold_at", hi)
                return q
            sales_rows.extend(_fetch_all(_sq))
        timeseries = build_campaign_timeseries(_daterange_days(lo, hi), selected, sales_rows)
        return {"summary": summary, "leads": leads, "timeseries": timeseries}
    except Exception as exc:
        logger.error("campaign_detail(%s,%s) falhou: %s", channel, campaign, exc, exc_info=True)
        return {"summary": _empty_summary(channel, campaign), "leads": [], "timeseries": []}


def traffic_report(period: str = "30d", mode: str = "lead",
                   date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    """Relatório agregado por canal+campanha. Fail-soft: qualquer erro → relatório vazio."""
    try:
        sb = get_supabase()
        lo, hi = _resolve_window(period, date_from, date_to)
        leads = _fetch_leads(sb, mode, lo, hi)
        lead_ids = [l["id"] for l in leads if l.get("id")]
        if not lead_ids:
            return _empty_report(mode, period)
        conversed = _conversed_ids(sb, lead_ids)
        closers = _closer_ids(sb, lead_ids)
        sales = _sales_by_lead(sb, lead_ids, lo, hi, mode)
        return build_campaign_report(
            leads, conversed, closers, sales, mode, period,
            spend_by_channel=_spend_by_channel(sb, lo, hi),
            campaign_id_by_lead=_meta_campaign_by_lead(sb, leads),
        )
    except Exception as exc:
        logger.error("traffic_report(%s,%s) falhou: %s", period, mode, exc, exc_info=True)
        return _empty_report(mode, period)


def _stage_info_map(sb) -> dict[str, dict[str, Any]]:
    stages = _fetch_all(lambda: sb.table("pipeline_stages").select("id, key, order_index"))
    return {s["id"]: {"key": s.get("key"), "order_index": s.get("order_index")} for s in stages}


def campaign_leads(channel: str, campaign: str, period: str = "30d", mode: str = "lead",
                   date_from: str | None = None, date_to: str | None = None) -> list[dict[str, Any]]:
    """Leads de uma campanha (canal+utm_campaign) p/ o drill-down. Fail-soft: [] em erro."""
    try:
        sb = get_supabase()
        lo, hi = _resolve_window(period, date_from, date_to)
        leads = _fetch_leads(sb, mode, lo, hi)
        selected = [
            l for l in leads
            if derive_channel(l) == channel and (_s(l.get("utm_campaign")) or _NO_CAMPAIGN) == campaign
        ]
        if not selected:
            return []
        lead_ids = [l["id"] for l in selected if l.get("id")]
        conversed = _conversed_ids(sb, lead_ids)
        sales = _sales_by_lead(sb, lead_ids, lo, hi, mode)
        stage_info = _stage_info_map(sb)
        deals = []
        for chunk in _chunks(lead_ids):
            deals.extend(_fetch_all(lambda c=chunk: sb.table("deals")
                                    .select("lead_id, stage_id, created_at").in_("lead_id", c)))
        # Estágio mais avançado (maior order_index) por lead — consistente com a lógica do closer.
        best_idx: dict[str, int] = {}
        furthest_stage: dict[str, str] = {}
        for d in deals:
            lid = d.get("lead_id")
            if not lid:
                continue
            info = stage_info.get(d.get("stage_id"))
            if not info:
                continue
            oi = info.get("order_index")
            oi_val = oi if isinstance(oi, int) else -1  # None/ausente => menor prioridade
            if lid not in best_idx or oi_val > best_idx[lid]:
                best_idx[lid] = oi_val
                furthest_stage[lid] = info.get("key")
        out: list[dict[str, Any]] = []
        for l in selected:
            lid = l["id"]
            sale = sales.get(lid)
            out.append({
                "lead_id": lid, "name": l.get("name"), "phone": l.get("phone"),
                "created_at": l.get("created_at"), "utm_source": l.get("utm_source"),
                "utm_medium": l.get("utm_medium"), "utm_campaign": l.get("utm_campaign"),
                "traffic_type": l.get("traffic_type"), "conversou": lid in conversed,
                "stage": furthest_stage.get(lid),
                "comprou": bool(sale), "valor": float(sale["value"]) if sale else 0.0,
                "sold_at": sale.get("last_sold_at") if sale else None,
            })
        out.sort(key=lambda r: (not r["comprou"], r.get("created_at") or ""), reverse=False)
        return out
    except Exception as exc:
        logger.error("campaign_leads(%s,%s) falhou: %s", channel, campaign, exc, exc_info=True)
        return []
