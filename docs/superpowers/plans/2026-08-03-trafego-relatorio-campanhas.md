# Relatório Campanhas (`/trafego`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **FRONTEND RULE (projeto):** Qualquer task que toque `frontend/src` DEVE usar a skill `frontend-design` E componentes **shadcn/ui** (`@/components/ui/*`) antes de escrever código. Ao despachar subagent de frontend, instrua isso explicitamente. Se `frontend-design` não estiver registrada no Skill tool, ler o SKILL.md do cache de plugins (ver memory `feedback_frontend_skill`).

**Goal:** Página administrativa `/trafego` ("Relatório Campanhas") que agrega leads por canal+campanha (UTMs/click-ids já capturados) cruzando com vendas registradas, com drill-down de leads.

**Architecture:** Backend Python puro (funções de agregação testáveis) + funções I/O fail-soft sobre Supabase, expostas por 2 endpoints `/api/traffic/*`. Frontend Next.js (App Router) com proxy admin-gated e página que reusa shadcn/ui.

**Tech Stack:** FastAPI, Supabase (postgrest), pytest; Next.js App Router, TypeScript, shadcn/ui, Tailwind.

---

## File Structure

**Backend (novo/modificado):**
- Create `backend/app/campaigns/traffic_report.py` — derivação de canal + agregação (puras) + I/O fail-soft.
- Create `backend/app/campaigns/traffic_router.py` — endpoints `GET /api/traffic/report` e `/api/traffic/leads`.
- Modify `backend/app/main.py` — registrar `traffic_router`.
- Create `backend/tests/test_traffic_report.py` — testes.

**Frontend (novo/modificado):**
- Create `frontend/src/app/api/traffic/report/route.ts` — proxy admin-gated.
- Create `frontend/src/app/api/traffic/leads/route.ts` — proxy admin-gated.
- Create `frontend/src/app/(authenticated)/trafego/page.tsx` — página.
- Create `frontend/src/components/trafego/campaign-report-table.tsx` — tabela de campanhas.
- Create `frontend/src/components/trafego/campaign-leads-drawer.tsx` — drill-down (Sheet).
- Modify `frontend/src/components/sidebar.tsx` — item de navegação admin-only.

**Convenções de dados (usar idênticas em todas as tasks):**

Canal (`derive_channel`) retorna exatamente um de: `"Google Ads"`, `"Meta Ads"`, `"Orgânico"`, `"Direto"`.

Linha do relatório (dict):
```json
{"channel": str, "campaign": str, "leads": int, "conversas": int, "closer": int,
 "vendas": int, "receita": float, "ticket_medio": float, "conversao": float}
```

Payload do relatório:
```json
{"mode": "lead"|"sale", "period": str, "rows": [<linha>...],
 "total": {"leads": int, "conversas": int, "closer": int, "vendas": int, "receita": float}}
```

Lead do drill-down (dict):
```json
{"lead_id": str, "name": str|null, "phone": str|null, "created_at": str|null,
 "utm_source": str|null, "utm_medium": str|null, "utm_campaign": str|null,
 "traffic_type": str|null, "conversou": bool, "stage": str|null,
 "comprou": bool, "valor": float}
```

---

## Task 1: `derive_channel` (função pura)

**Files:**
- Create: `backend/app/campaigns/traffic_report.py`
- Test: `backend/tests/test_traffic_report.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_traffic_report.py
from app.campaigns.traffic_report import derive_channel


def test_derive_channel_google_by_gclid():
    assert derive_channel({"gclid": "abc"}) == "Google Ads"


def test_derive_channel_meta_by_fbclid():
    assert derive_channel({"fbclid": "x"}) == "Meta Ads"


def test_derive_channel_meta_by_ctwa():
    assert derive_channel({"ctwa_clid": "x"}) == "Meta Ads"


def test_derive_channel_gclid_wins_over_fbclid():
    assert derive_channel({"gclid": "g", "fbclid": "f"}) == "Google Ads"


def test_derive_channel_organic_by_traffic_type():
    assert derive_channel({"traffic_type": "organic"}) == "Orgânico"


def test_derive_channel_organic_by_utm_source():
    assert derive_channel({"utm_source": "instagram"}) == "Orgânico"


def test_derive_channel_direto_when_no_signal():
    assert derive_channel({}) == "Direto"


def test_derive_channel_ignores_empty_strings():
    assert derive_channel({"gclid": "", "fbclid": "  ", "utm_source": ""}) == "Direto"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: FAIL (ModuleNotFoundError / ImportError: cannot import name 'derive_channel').

- [ ] **Step 3: Implementar**

```python
# backend/app/campaigns/traffic_report.py
"""Relatório de campanhas (/trafego): agrega leads por canal+campanha cruzando com vendas.

Funções puras (derive_channel, build_campaign_report) isoladas do I/O p/ teste.
As funções que tocam o banco (traffic_report, campaign_leads) são fail-soft.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("America/Sao_Paulo")
_NO_CAMPAIGN = "(sem campanha)"
_CLOSER_STAGE_KEY = "qualificado"


def _s(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def derive_channel(lead: dict[str, Any]) -> str:
    """Canal do lead por prioridade de click-id. Retorna Google Ads/Meta Ads/Orgânico/Direto."""
    if _s(lead.get("gclid")):
        return "Google Ads"
    if _s(lead.get("fbclid")) or _s(lead.get("ctwa_clid")):
        return "Meta Ads"
    if _s(lead.get("traffic_type")).lower() == "organic" or _s(lead.get("utm_source")):
        return "Orgânico"
    return "Direto"
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/traffic_report.py backend/tests/test_traffic_report.py
git commit -m "feat(trafego): derive_channel por click-id"
```

---

## Task 2: `build_campaign_report` (agregação pura)

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py`
- Test: `backend/tests/test_traffic_report.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
# adicionar em backend/tests/test_traffic_report.py
from app.campaigns.traffic_report import build_campaign_report


def _lead(id, **kw):
    base = {"id": id, "utm_campaign": None, "gclid": "", "fbclid": "", "ctwa_clid": "",
            "utm_source": "", "traffic_type": None}
    base.update(kw)
    return base


def test_build_groups_by_channel_and_campaign():
    leads = [
        _lead("a", gclid="1", utm_campaign="black"),
        _lead("b", gclid="2", utm_campaign="black"),
        _lead("c", fbclid="3", utm_campaign="promo"),
    ]
    out = build_campaign_report(leads, set(), set(), {}, mode="lead", period="30d")
    rows = {(r["channel"], r["campaign"]): r for r in out["rows"]}
    assert rows[("Google Ads", "black")]["leads"] == 2
    assert rows[("Meta Ads", "promo")]["leads"] == 1


def test_build_null_campaign_becomes_placeholder():
    leads = [_lead("a", gclid="1")]
    out = build_campaign_report(leads, set(), set(), {}, mode="lead", period="30d")
    assert out["rows"][0]["campaign"] == "(sem campanha)"


def test_build_metrics_conversas_closer_vendas_receita():
    leads = [_lead("a", gclid="1", utm_campaign="black"),
             _lead("b", gclid="2", utm_campaign="black")]
    sales_by_lead = {"a": {"count": 1, "value": 100.0}}
    out = build_campaign_report(leads, {"a"}, {"a", "b"}, sales_by_lead, mode="lead", period="30d")
    row = out["rows"][0]
    assert row["conversas"] == 1
    assert row["closer"] == 2
    assert row["vendas"] == 1
    assert row["receita"] == 100.0
    assert row["ticket_medio"] == 100.0
    assert row["conversao"] == 0.5


def test_build_ticket_and_conversao_zero_safe():
    leads = [_lead("a", gclid="1", utm_campaign="x")]
    out = build_campaign_report(leads, set(), set(), {}, mode="lead", period="30d")
    row = out["rows"][0]
    assert row["ticket_medio"] == 0.0
    assert row["conversao"] == 0.0


def test_build_total_aggregates_all_rows():
    leads = [_lead("a", gclid="1", utm_campaign="x"),
             _lead("b", fbclid="2", utm_campaign="y")]
    sales_by_lead = {"a": {"count": 1, "value": 50.0}, "b": {"count": 2, "value": 30.0}}
    out = build_campaign_report(leads, {"a"}, {"a"}, sales_by_lead, mode="lead", period="30d")
    assert out["total"] == {"leads": 2, "conversas": 1, "closer": 1, "vendas": 3, "receita": 80.0}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: FAIL (ImportError: cannot import name 'build_campaign_report').

- [ ] **Step 3: Implementar**

```python
# adicionar em backend/app/campaigns/traffic_report.py
def build_campaign_report(
    leads: list[dict[str, Any]],
    conversed_ids: set[str],
    closer_ids: set[str],
    sales_by_lead: dict[str, dict[str, Any]],
    mode: str,
    period: str,
) -> dict[str, Any]:
    """Agrega os leads em linhas (canal, campanha). Puro — recebe coleções já buscadas.

    - conversed_ids / closer_ids: sets de lead_id que conversaram / chegaram ao closer.
    - sales_by_lead: lead_id -> {"count": int, "value": float} (já filtrado por modo).
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for lead in leads:
        lead_id = lead.get("id")
        channel = derive_channel(lead)
        campaign = _s(lead.get("utm_campaign")) or _NO_CAMPAIGN
        key = (channel, campaign)
        row = groups.get(key)
        if row is None:
            row = {"channel": channel, "campaign": campaign, "leads": 0, "conversas": 0,
                   "closer": 0, "vendas": 0, "receita": 0.0}
            groups[key] = row
        row["leads"] += 1
        if lead_id in conversed_ids:
            row["conversas"] += 1
        if lead_id in closer_ids:
            row["closer"] += 1
        sale = sales_by_lead.get(lead_id)
        if sale:
            row["vendas"] += int(sale.get("count", 0))
            row["receita"] += float(sale.get("value", 0.0) or 0.0)

    rows: list[dict[str, Any]] = []
    total = {"leads": 0, "conversas": 0, "closer": 0, "vendas": 0, "receita": 0.0}
    for row in groups.values():
        vendas = row["vendas"]
        row["ticket_medio"] = round(row["receita"] / vendas, 2) if vendas else 0.0
        row["conversao"] = round(row["vendas"] / row["leads"], 4) if row["leads"] else 0.0
        for k in total:
            total[k] += row[k]
        rows.append(row)

    rows.sort(key=lambda r: (r["channel"], -r["receita"], -r["leads"]))
    total["receita"] = round(total["receita"], 2)
    return {"mode": mode, "period": period, "rows": rows, "total": total}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: PASS (todas as de Task 1 + Task 2).

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/traffic_report.py backend/tests/test_traffic_report.py
git commit -m "feat(trafego): build_campaign_report (agregação por canal+campanha)"
```

---

## Task 3: I/O `traffic_report` e `campaign_leads` (fail-soft)

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py`
- Test: `backend/tests/test_traffic_report.py`

Notas de implementação:
- `_period_cutoff(period)`: `"7d"/"30d"/"90d"` → ISO do início da janela (UTC); `"all"`/desconhecido → `None`.
- `_closer_ids(...)`: para cada pipeline, o `order_index` do stage `qualificado`; um lead é closer se algum deal seu tem `stage` com `order_index >= ` o do `qualificado` no MESMO pipeline.
- Chunk de `.in_(...)` em blocos de 200 ids (`_chunks`).
- Tudo fail-soft: exceção em qualquer fetch → segue com coleção vazia (nunca levanta).

- [ ] **Step 1: Escrever os testes que falham (supabase falso)**

```python
# adicionar em backend/tests/test_traffic_report.py
import app.campaigns.traffic_report as tr


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def not_(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def execute(self):
        class R: pass
        r = R(); r.data = self._rows; return r


class _FakeSupabase:
    def __init__(self, tables):
        self._tables = tables
    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))


def test_traffic_report_lead_mode_end_to_end(monkeypatch):
    tables = {
        "leads": [
            {"id": "a", "gclid": "1", "fbclid": "", "ctwa_clid": "", "utm_source": "",
             "utm_campaign": "black", "traffic_type": "paid", "created_at": "2026-08-01T00:00:00Z"},
        ],
        "conversations": [{"lead_id": "a", "last_customer_message_at": "2026-08-02T00:00:00Z"}],
        "deals": [{"lead_id": "a", "stage_id": "s2", "pipeline_id": "p1"}],
        "pipeline_stages": [
            {"id": "s1", "pipeline_id": "p1", "key": "entrada", "order_index": 0},
            {"id": "s2", "pipeline_id": "p1", "key": "qualificado", "order_index": 1},
        ],
        "sales": [{"lead_id": "a", "value": 200.0, "sold_at": "2026-08-03T00:00:00Z"}],
    }
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    out = tr.traffic_report(period="30d", mode="lead")
    row = out["rows"][0]
    assert (row["channel"], row["campaign"]) == ("Google Ads", "black")
    assert row["conversas"] == 1 and row["closer"] == 1 and row["vendas"] == 1
    assert row["receita"] == 200.0


def test_traffic_report_failsoft_on_error(monkeypatch):
    class _Boom:
        def table(self, *a, **k): raise RuntimeError("db down")
    monkeypatch.setattr(tr, "get_supabase", lambda: _Boom())
    out = tr.traffic_report(period="30d", mode="lead")
    assert out["rows"] == [] and out["total"]["leads"] == 0


def test_campaign_leads_filters_by_channel_and_campaign(monkeypatch):
    tables = {
        "leads": [
            {"id": "a", "name": "Ana", "phone": "5511", "gclid": "1", "fbclid": "",
             "ctwa_clid": "", "utm_source": "", "utm_medium": "cpc", "utm_campaign": "black",
             "traffic_type": "paid", "created_at": "2026-08-01T00:00:00Z"},
            {"id": "b", "name": "Bob", "phone": "5512", "gclid": "", "fbclid": "2",
             "ctwa_clid": "", "utm_source": "", "utm_medium": "cpc", "utm_campaign": "black",
             "traffic_type": "paid", "created_at": "2026-08-01T00:00:00Z"},
        ],
        "conversations": [], "deals": [], "pipeline_stages": [], "sales": [],
    }
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    leads = tr.campaign_leads(channel="Google Ads", campaign="black", period="30d", mode="lead")
    assert [l["lead_id"] for l in leads] == ["a"]
    assert leads[0]["comprou"] is False
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: FAIL (ImportError: cannot import name 'traffic_report' / 'campaign_leads').

- [ ] **Step 3: Implementar**

```python
# adicionar em backend/app/campaigns/traffic_report.py
_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}
_LEAD_COLS = ("id, name, phone, created_at, gclid, fbclid, ctwa_clid, "
              "utm_source, utm_medium, utm_campaign, traffic_type")


def _period_cutoff(period: str) -> str | None:
    days = _PERIOD_DAYS.get(period)
    if not days:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _chunks(items: list, size: int = 200):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _fetch_leads(sb, mode: str, cutoff: str | None) -> list[dict[str, Any]]:
    if mode == "sale":
        q = sb.table("sales").select("lead_id")
        if cutoff:
            q = q.gte("sold_at", cutoff)
        sale_ids = sorted({r["lead_id"] for r in (q.execute().data or []) if r.get("lead_id")})
        leads: list[dict[str, Any]] = []
        for chunk in _chunks(sale_ids):
            data = sb.table("leads").select(_LEAD_COLS).in_("id", chunk).execute().data or []
            leads.extend(data)
        return leads
    q = sb.table("leads").select(_LEAD_COLS)
    if cutoff:
        q = q.gte("created_at", cutoff)
    return q.execute().data or []


def _conversed_ids(sb, lead_ids: list[str]) -> set[str]:
    out: set[str] = set()
    for chunk in _chunks(lead_ids):
        rows = (sb.table("conversations").select("lead_id, last_customer_message_at")
                .in_("lead_id", chunk).execute().data or [])
        for r in rows:
            if r.get("last_customer_message_at") and r.get("lead_id"):
                out.add(r["lead_id"])
    return out


def _closer_ids(sb, lead_ids: list[str]) -> set[str]:
    stages = sb.table("pipeline_stages").select("id, pipeline_id, key, order_index").execute().data or []
    stage_by_id = {s["id"]: s for s in stages}
    qualifica_idx: dict[str, int] = {
        s["pipeline_id"]: s["order_index"]
        for s in stages if s.get("key") == _CLOSER_STAGE_KEY and s.get("order_index") is not None
    }
    out: set[str] = set()
    for chunk in _chunks(lead_ids):
        deals = (sb.table("deals").select("lead_id, stage_id, pipeline_id")
                 .in_("lead_id", chunk).execute().data or [])
        for d in deals:
            stage = stage_by_id.get(d.get("stage_id"))
            if not stage or stage.get("order_index") is None:
                continue
            threshold = qualifica_idx.get(d.get("pipeline_id"))
            if threshold is not None and stage["order_index"] >= threshold:
                out.add(d["lead_id"])
    return out


def _sales_by_lead(sb, lead_ids: list[str], cutoff: str | None, mode: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(lead_ids):
        q = sb.table("sales").select("lead_id, value, sold_at").in_("lead_id", chunk)
        if mode == "sale" and cutoff:
            q = q.gte("sold_at", cutoff)
        for r in (q.execute().data or []):
            lid = r.get("lead_id")
            if not lid:
                continue
            agg = out.setdefault(lid, {"count": 0, "value": 0.0})
            agg["count"] += 1
            try:
                agg["value"] += float(r.get("value") or 0.0)
            except (TypeError, ValueError):
                pass
    return out


def _empty_report(mode: str, period: str) -> dict[str, Any]:
    return {"mode": mode, "period": period, "rows": [],
            "total": {"leads": 0, "conversas": 0, "closer": 0, "vendas": 0, "receita": 0.0}}


def traffic_report(period: str = "30d", mode: str = "lead") -> dict[str, Any]:
    """Relatório agregado por canal+campanha. Fail-soft: qualquer erro → relatório vazio."""
    try:
        sb = get_supabase()
        cutoff = _period_cutoff(period)
        leads = _fetch_leads(sb, mode, cutoff)
        lead_ids = [l["id"] for l in leads if l.get("id")]
        if not lead_ids:
            return _empty_report(mode, period)
        conversed = _conversed_ids(sb, lead_ids)
        closers = _closer_ids(sb, lead_ids)
        sales = _sales_by_lead(sb, lead_ids, cutoff, mode)
        return build_campaign_report(leads, conversed, closers, sales, mode, period)
    except Exception as exc:
        logger.error("traffic_report(%s,%s) falhou: %s", period, mode, exc, exc_info=True)
        return _empty_report(mode, period)


def _stage_label_map(sb) -> dict[str, str]:
    stages = sb.table("pipeline_stages").select("id, key").execute().data or []
    return {s["id"]: s.get("key") for s in stages}


def campaign_leads(channel: str, campaign: str, period: str = "30d", mode: str = "lead") -> list[dict[str, Any]]:
    """Leads de uma campanha (canal+utm_campaign) p/ o drill-down. Fail-soft: [] em erro."""
    try:
        sb = get_supabase()
        cutoff = _period_cutoff(period)
        leads = _fetch_leads(sb, mode, cutoff)
        selected = [
            l for l in leads
            if derive_channel(l) == channel and (_s(l.get("utm_campaign")) or _NO_CAMPAIGN) == campaign
        ]
        if not selected:
            return []
        lead_ids = [l["id"] for l in selected if l.get("id")]
        conversed = _conversed_ids(sb, lead_ids)
        sales = _sales_by_lead(sb, lead_ids, cutoff, mode)
        stage_labels = _stage_label_map(sb)
        deals = []
        for chunk in _chunks(lead_ids):
            deals.extend(sb.table("deals").select("lead_id, stage_id, created_at")
                         .in_("lead_id", chunk).execute().data or [])
        latest_stage: dict[str, str] = {}
        for d in sorted(deals, key=lambda x: x.get("created_at") or ""):
            if d.get("lead_id"):
                latest_stage[d["lead_id"]] = stage_labels.get(d.get("stage_id"))
        out: list[dict[str, Any]] = []
        for l in selected:
            lid = l["id"]
            sale = sales.get(lid)
            out.append({
                "lead_id": lid, "name": l.get("name"), "phone": l.get("phone"),
                "created_at": l.get("created_at"), "utm_source": l.get("utm_source"),
                "utm_medium": l.get("utm_medium"), "utm_campaign": l.get("utm_campaign"),
                "traffic_type": l.get("traffic_type"), "conversou": lid in conversed,
                "stage": latest_stage.get(lid),
                "comprou": bool(sale), "valor": float(sale["value"]) if sale else 0.0,
            })
        out.sort(key=lambda r: (not r["comprou"], r.get("created_at") or ""), reverse=False)
        return out
    except Exception as exc:
        logger.error("campaign_leads(%s,%s) falhou: %s", channel, campaign, exc, exc_info=True)
        return []
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: PASS (todas).

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/traffic_report.py backend/tests/test_traffic_report.py
git commit -m "feat(trafego): traffic_report e campaign_leads (I/O fail-soft)"
```

---

## Task 4: Router FastAPI `/api/traffic` + registro

**Files:**
- Create: `backend/app/campaigns/traffic_router.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_traffic_report.py`

- [ ] **Step 1: Escrever o teste que falha (router importável e monta as rotas)**

```python
# adicionar em backend/tests/test_traffic_report.py
def test_router_exposes_expected_paths():
    from app.campaigns.traffic_router import router
    paths = {r.path for r in router.routes}
    assert "/api/traffic/report" in paths
    assert "/api/traffic/leads" in paths
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py::test_router_exposes_expected_paths -q`
Expected: FAIL (ModuleNotFoundError: app.campaigns.traffic_router).

- [ ] **Step 3: Implementar o router**

```python
# backend/app/campaigns/traffic_router.py
from fastapi import APIRouter

from app.campaigns.traffic_report import traffic_report, campaign_leads

router = APIRouter(prefix="/api/traffic", tags=["traffic"])


@router.get("/report")
async def traffic_report_endpoint(period: str = "30d", mode: str = "lead"):
    """Relatório agregado por canal+campanha (admin-only na UI)."""
    mode = mode if mode in ("lead", "sale") else "lead"
    return traffic_report(period=period, mode=mode)


@router.get("/leads")
async def traffic_leads_endpoint(channel: str, campaign: str, period: str = "30d", mode: str = "lead"):
    """Leads de uma campanha específica (drill-down)."""
    mode = mode if mode in ("lead", "sale") else "lead"
    return {"leads": campaign_leads(channel=channel, campaign=campaign, period=period, mode=mode)}
```

- [ ] **Step 4: Registrar no main.py**

Em `backend/app/main.py`, ao lado de `from app.campaigns.conversions_router import router as conversions_router` (linha ~125), adicionar:
```python
from app.campaigns.traffic_router import router as traffic_router
```
E ao lado de `app.include_router(conversions_router)` (procure onde `conversions_router` é incluído; se não houver, inclua junto aos demais `app.include_router(...)` ~linha 138):
```python
app.include_router(traffic_router)
```

- [ ] **Step 5: Rodar e ver passar + smoke import do app**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: PASS.
Run: `cd backend; python -c "import app.main"`
Expected: sem erro (app importa com o router registrado).

- [ ] **Step 6: Commit**

```bash
git add backend/app/campaigns/traffic_router.py backend/app/main.py backend/tests/test_traffic_report.py
git commit -m "feat(trafego): endpoints /api/traffic/report e /leads"
```

---

## Task 5: Next.js proxy routes admin-gated

**Files:**
- Create: `frontend/src/app/api/traffic/report/route.ts`
- Create: `frontend/src/app/api/traffic/leads/route.ts`

Padrão idêntico a `frontend/src/app/api/conversions/dashboard/route.ts` (gate `role === "admin"`).

- [ ] **Step 1: Criar o proxy do relatório**

```typescript
// frontend/src/app/api/traffic/report/route.ts
import { getCurrentUser } from "@/lib/supabase/pipeline-access";

export async function GET(req: Request) {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const period = searchParams.get("period") || "30d";
  const mode = searchParams.get("mode") || "lead";
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  try {
    const resp = await fetch(`${backendUrl}/api/traffic/report?period=${encodeURIComponent(period)}&mode=${encodeURIComponent(mode)}`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "report_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "report_unreachable" }, { status: 502 });
  }
}
```

- [ ] **Step 2: Criar o proxy do drill-down**

```typescript
// frontend/src/app/api/traffic/leads/route.ts
import { getCurrentUser } from "@/lib/supabase/pipeline-access";

export async function GET(req: Request) {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const channel = searchParams.get("channel") || "";
  const campaign = searchParams.get("campaign") || "";
  const period = searchParams.get("period") || "30d";
  const mode = searchParams.get("mode") || "lead";
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  const qs = new URLSearchParams({ channel, campaign, period, mode }).toString();
  try {
    const resp = await fetch(`${backendUrl}/api/traffic/leads?${qs}`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "leads_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "leads_unreachable" }, { status: 502 });
  }
}
```

- [ ] **Step 3: Verificar typecheck/lint**

Run: `cd frontend; npx tsc --noEmit`
Expected: sem erros novos nesses arquivos.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/api/traffic/
git commit -m "feat(trafego): proxy admin-gated /api/traffic/report e /leads"
```

---

## Task 6: Item de navegação no sidebar (admin-only)

**Files:**
- Modify: `frontend/src/components/sidebar.tsx`

> **FRONTEND:** aplicar frontend-design + shadcn. Este é só um item de nav — seguir o padrão exato dos itens existentes (mesma estrutura `{href, label, icon, roles}`).

- [ ] **Step 1: Adicionar o item ao grupo "Dados"**

Em `frontend/src/components/sidebar.tsx`, dentro do grupo `label: "Dados"` (array `items`, ~linha 90), adicionar como primeiro item:
```tsx
{
  href: "/trafego",
  label: "Relatório Campanhas",
  icon: <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" /></svg>,
  roles: ["admin"],
},
```

- [ ] **Step 2: Verificar que o item só aparece p/ admin**

Confirmar visualmente/no código que a renderização já respeita `roles` (o sidebar filtra por `item.roles?.includes(role)` — se não filtrar, adicionar o filtro seguindo o padrão dos itens `roles: ["admin"]` já existentes de `/estatisticas` e `/config`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/sidebar.tsx
git commit -m "feat(trafego): item de navegação Relatório Campanhas (admin)"
```

---

## Task 7: Página `/trafego` + tabela + drill-down (shadcn)

**Files:**
- Create: `frontend/src/app/(authenticated)/trafego/page.tsx`
- Create: `frontend/src/components/trafego/campaign-report-table.tsx`
- Create: `frontend/src/components/trafego/campaign-leads-drawer.tsx`

> **FRONTEND (obrigatório):** invocar a skill `frontend-design` E usar shadcn/ui (`@/components/ui/table`, `sheet`, `badge`, `select`, `switch`, `skeleton`). Seguir a paleta do projeto (`#ff5600`, `#111111`, `#faf9f6`, `#dedbd6`, `#7b7b78`) e o layout de cabeçalho/abas de `campanhas/page.tsx`. O código abaixo é funcionalmente correto e serve de base; refine o visual conforme a skill, sem inventar estética nova.

- [ ] **Step 1: Tabela de campanhas**

```tsx
// frontend/src/components/trafego/campaign-report-table.tsx
"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

export type CampaignRow = {
  channel: string; campaign: string; leads: number; conversas: number;
  closer: number; vendas: number; receita: number; ticket_medio: number; conversao: number;
};

const fmtBRL = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;

export function CampaignReportTable({ rows, onRowClick }: {
  rows: CampaignRow[];
  onRowClick: (r: CampaignRow) => void;
}) {
  if (rows.length === 0) {
    return <p className="text-[14px] text-[#7b7b78] py-8 text-center">Nenhuma campanha no período.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Canal</TableHead>
          <TableHead>Campanha</TableHead>
          <TableHead className="text-right">Leads</TableHead>
          <TableHead className="text-right">Conversas</TableHead>
          <TableHead className="text-right">Closer</TableHead>
          <TableHead className="text-right">Vendas</TableHead>
          <TableHead className="text-right">Receita</TableHead>
          <TableHead className="text-right">Ticket</TableHead>
          <TableHead className="text-right">Conversão</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r, i) => (
          <TableRow key={`${r.channel}-${r.campaign}-${i}`} className="cursor-pointer" onClick={() => onRowClick(r)}>
            <TableCell><Badge variant="outline">{r.channel}</Badge></TableCell>
            <TableCell className="text-[#111111]">{r.campaign}</TableCell>
            <TableCell className="text-right">{r.leads}</TableCell>
            <TableCell className="text-right">{r.conversas}</TableCell>
            <TableCell className="text-right">{r.closer}</TableCell>
            <TableCell className="text-right">{r.vendas}</TableCell>
            <TableCell className="text-right">{fmtBRL(r.receita)}</TableCell>
            <TableCell className="text-right">{fmtBRL(r.ticket_medio)}</TableCell>
            <TableCell className="text-right">{fmtPct(r.conversao)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 2: Drawer de drill-down (Sheet)**

```tsx
// frontend/src/components/trafego/campaign-leads-drawer.tsx
"use client";

import { useEffect, useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

export type CampaignLead = {
  lead_id: string; name: string | null; phone: string | null; created_at: string | null;
  utm_source: string | null; utm_medium: string | null; utm_campaign: string | null;
  traffic_type: string | null; conversou: boolean; stage: string | null;
  comprou: boolean; valor: number;
};

const fmtBRL = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;

export function CampaignLeadsDrawer({ channel, campaign, period, mode, onClose }: {
  channel: string | null; campaign: string | null; period: string; mode: string; onClose: () => void;
}) {
  const [leads, setLeads] = useState<CampaignLead[]>([]);
  const [loading, setLoading] = useState(false);
  const open = channel !== null && campaign !== null;

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    const qs = new URLSearchParams({ channel: channel!, campaign: campaign!, period, mode }).toString();
    fetch(`/api/traffic/leads?${qs}`)
      .then(r => r.json())
      .then(d => setLeads(Array.isArray(d.leads) ? d.leads : []))
      .catch(() => setLeads([]))
      .finally(() => setLoading(false));
  }, [open, channel, campaign, period, mode]);

  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{channel} · {campaign}</SheetTitle>
        </SheetHeader>
        {loading ? (
          <div className="space-y-2 mt-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
        ) : leads.length === 0 ? (
          <p className="text-[14px] text-[#7b7b78] py-8 text-center">Nenhum lead nesta campanha.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Lead</TableHead>
                <TableHead>Origem</TableHead>
                <TableHead>Etapa</TableHead>
                <TableHead>Conversou</TableHead>
                <TableHead className="text-right">Comprou</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {leads.map((l) => (
                <TableRow key={l.lead_id}>
                  <TableCell className="text-[#111111]">{l.name || l.phone || l.lead_id}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{l.traffic_type === "paid" ? "Pago" : l.traffic_type === "organic" ? "Orgânico" : "—"}</Badge>
                  </TableCell>
                  <TableCell>{l.stage || "—"}</TableCell>
                  <TableCell>{l.conversou ? "Sim" : "Não"}</TableCell>
                  <TableCell className="text-right">{l.comprou ? fmtBRL(l.valor) : "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 3: Página `/trafego`**

```tsx
// frontend/src/app/(authenticated)/trafego/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useCurrentRole } from "@/hooks/use-current-role";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { CampaignReportTable, type CampaignRow } from "@/components/trafego/campaign-report-table";
import { CampaignLeadsDrawer } from "@/components/trafego/campaign-leads-drawer";

type Report = { mode: string; period: string; rows: CampaignRow[]; total: { leads: number; conversas: number; closer: number; vendas: number; receita: number } };

export default function TrafegoPage() {
  const { role, loading: roleLoading } = useCurrentRole();
  const [period, setPeriod] = useState("30d");
  const [mode, setMode] = useState<"lead" | "sale">("lead");
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<{ channel: string; campaign: string } | null>(null);

  useEffect(() => {
    if (roleLoading || role !== "admin") return;
    setLoading(true);
    fetch(`/api/traffic/report?period=${period}&mode=${mode}`)
      .then(r => r.json())
      .then((d: Report) => setReport(d))
      .catch(() => setReport(null))
      .finally(() => setLoading(false));
  }, [period, mode, role, roleLoading]);

  if (!roleLoading && role !== "admin") {
    return <div className="p-8 text-[14px] text-[#7b7b78]">Acesso restrito a administradores.</div>;
  }

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-4 md:py-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between flex-shrink-0">
        <div>
          <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[24px] md:text-[32px] font-normal text-[#111111]">Relatório Campanhas</h1>
          <p className="text-[13px] md:text-[14px] text-[#7b7b78] mt-0.5">Rastreio de campanhas e leads por origem, cruzado com vendas registradas</p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-[13px] text-[#7b7b78]">Por venda</span>
            <Switch checked={mode === "sale"} onCheckedChange={(c) => setMode(c ? "sale" : "lead")} />
          </div>
          <Select value={period} onValueChange={setPeriod}>
            <SelectTrigger className="w-[130px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="7d">Últimos 7 dias</SelectItem>
              <SelectItem value="30d">Últimos 30 dias</SelectItem>
              <SelectItem value="90d">Últimos 90 dias</SelectItem>
              <SelectItem value="all">Tudo</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="flex-1 overflow-auto px-4 md:px-8 py-4 md:py-8 bg-[#faf9f6]">
        {loading ? (
          <div className="space-y-2">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
        ) : (
          <div className="bg-white border border-[#dedbd6] rounded-[8px] p-2 md:p-4">
            <CampaignReportTable
              rows={report?.rows ?? []}
              onRowClick={(r) => setSelected({ channel: r.channel, campaign: r.campaign })}
            />
          </div>
        )}
      </div>

      <CampaignLeadsDrawer
        channel={selected?.channel ?? null}
        campaign={selected?.campaign ?? null}
        period={period}
        mode={mode}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
```

- [ ] **Step 4: Typecheck e build**

Run: `cd frontend; npx tsc --noEmit`
Expected: sem erros.
Run (se a task `Run All Dev` estiver disponível, subir o dev e abrir `/trafego` como admin): a página carrega, filtro de período e toggle funcionam, clicar numa campanha abre o drawer com os leads.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/(authenticated)/trafego/ frontend/src/components/trafego/
git commit -m "feat(trafego): página Relatório Campanhas com drill-down (shadcn)"
```

---

## Self-Review (feito pelo autor do plano)

- **Cobertura do spec:** canal por click-id (T1) ✓ · agrupamento canal+campanha, métricas leads/conversas/closer/vendas/receita/ticket/conversão (T2) ✓ · período por entrada×venda + fail-soft + closer por `order_index` de `qualificado` (T3) ✓ · endpoints (T4) ✓ · gate admin (T5) ✓ · nav (T6) ✓ · layout campanhas+drill-down (T7) ✓ · fora de escopo (captura nova, ROAS) não incluído ✓.
- **Placeholders:** nenhum — todo passo tem código/comando concreto.
- **Consistência de tipos:** `CampaignRow`/`Report` no front espelham as chaves do dict do backend (`channel, campaign, leads, conversas, closer, vendas, receita, ticket_medio, conversao`, `total`); `CampaignLead` espelha o dict de `campaign_leads`. `derive_channel` retorna os 4 rótulos usados no agrupamento e no filtro do drill-down.

## Notas de validação pós-implementação
- Rodar suíte backend completa: `cd backend; python -m pytest -q` (garantir 0 regressões).
- Confirmar em navegador real como admin (memory pede validação runtime): filtros, toggle, drawer, e que não-admin recebe "Acesso restrito".
