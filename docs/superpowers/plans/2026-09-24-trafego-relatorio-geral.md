# /trafego Relatório Geral — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bloco "Relatório geral" entre o cabeçalho e a tabela do `/trafego`: funil com taxas e gargalo, custo por etapa, funil por canal, tempo e qualidade.

**Architecture:** O backend acrescenta `summary` à resposta de `GET /api/traffic/report`, calculado por uma função pura (`build_report_summary`) sobre os dados que o `traffic_report` já busca. O frontend lê `report.summary` (nenhum fetch novo) e renderiza um componente recolhível.

**Tech Stack:** FastAPI + pytest (backend), Next.js App Router + Tailwind + Vitest (frontend).

Spec: `docs/superpowers/specs/2026-09-24-trafego-relatorio-geral-design.md`.

**Execução em paralelo:** A Task 1 (backend) e a Task 2 (frontend) não compartilham arquivos e dependem só do contrato do spec. Podem rodar ao mesmo tempo no MESMO working tree. **Nenhuma das duas faz commit** — o orquestrador comita no fim, para não haver corrida no `.git/index.lock`.

---

### Task 1: Backend — `build_report_summary` + `first_sold_at` + ligação

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py` (imports; `_sales_by_lead`; `_empty_report`; `traffic_report`; nova função)
- Create: `backend/tests/test_traffic_report_summary.py`

- [ ] **Step 1: Escrever os testes (falhando)**

Criar `backend/tests/test_traffic_report_summary.py`:

```python
"""Relatório geral do /trafego (bloco acima da tabela) — build_report_summary é puro."""
import app.campaigns.traffic_report as tr
from app.campaigns.traffic_report import (
    build_campaign_report, build_report_summary, _empty_report, _sales_by_lead,
)


def _t(leads=0, conversas=0, closer=0, clientes=0, pedidos=0, receita=0.0, investimento=0.0, roas=None):
    return {"leads": leads, "conversas": conversas, "closer": closer, "clientes": clientes,
            "pedidos": pedidos, "receita": receita, "investimento": investimento, "roas": roas}


def _report(total, subtotals=None, rows=None, mode="lead"):
    return {"mode": mode, "period": "30d", "rows": rows or [], "total": total,
            "channel_subtotals": subtotals or {}}


def test_empty_report_carries_summary_with_nulls():
    s = _empty_report("lead", "30d")["summary"]
    assert s["funnel"]["leads"] == 0
    assert s["funnel"]["taxa_conversa"] is None
    assert s["funnel"]["gargalo"] is None
    assert s["cost"]["cpl"] is None and s["cost"]["roas"] is None
    assert s["channels"] == []
    assert s["timing_quality"]["dias_ate_compra_mediana"] is None
    assert s["timing_quality"]["amostra_dias"] == 0


def test_funnel_rates_and_bottleneck():
    s = build_report_summary(_report(_t(leads=100, conversas=50, closer=10, clientes=5)), [], {})
    f = s["funnel"]
    assert (f["taxa_conversa"], f["taxa_closer"], f["taxa_cliente"], f["taxa_total"]) == (0.5, 0.2, 0.5, 0.05)
    assert f["gargalo"] == "closer"


def test_bottleneck_tie_picks_first_stage():
    s = build_report_summary(_report(_t(leads=100, conversas=50, closer=25, clientes=20)), [], {})
    assert s["funnel"]["gargalo"] == "conversa"


def test_cost_divides_by_paid_leads_only():
    subs = {
        "Google Ads": _t(leads=10, conversas=5, closer=2, clientes=1, receita=300.0, investimento=100.0),
        "Orgânico": _t(leads=90, conversas=60, closer=20, clientes=9, receita=900.0),
    }
    s = build_report_summary(_report(_t(leads=100, conversas=65, closer=22, clientes=10), subs), [], {})
    c = s["cost"]
    assert c["leads"] == 10 and c["clientes"] == 1
    assert (c["cpl"], c["custo_conversa"], c["custo_closer"], c["cac"]) == (10.0, 20.0, 50.0, 100.0)
    assert c["investimento"] == 100.0 and c["receita"] == 300.0 and c["roas"] == 3.0


def test_cost_is_null_without_spend():
    subs = {"Orgânico": _t(leads=5, conversas=3, closer=1, clientes=1, receita=50.0)}
    c = build_report_summary(_report(_t(leads=5, conversas=3, closer=1, clientes=1), subs), [], {})["cost"]
    assert c["investimento"] == 0.0
    assert c["cpl"] is None and c["cac"] is None and c["roas"] is None


def test_channels_fixed_order_and_empty_channel_omitted():
    subs = {
        "Sem rastreio": _t(leads=1),
        "Outro": _t(leads=1),
        "Orgânico": _t(leads=1),
        "Meta Ads": _t(),
        "Google Ads": _t(leads=2, conversas=1),
    }
    chans = build_report_summary(_report(_t(leads=5), subs), [], {})["channels"]
    assert [c["channel"] for c in chans] == ["Google Ads", "Orgânico", "Sem rastreio", "Outro"]
    assert chans[0]["taxa_conversa"] == 0.5


def test_paid_channel_with_spend_and_no_leads_is_kept():
    subs = {"Meta Ads": _t(investimento=40.0)}
    chans = build_report_summary(_report(_t(), subs), [], {})["channels"]
    assert [c["channel"] for c in chans] == ["Meta Ads"]
    assert chans[0]["taxa_conversa"] is None


def test_channel_leads_sum_to_funnel_total():
    leads = [
        {"id": "g", "gclid": "x", "created_at": "2026-09-01T12:00:00+00:00"},
        {"id": "m", "fbclid": "y", "created_at": "2026-09-01T12:00:00+00:00"},
        {"id": "n", "created_at": "2026-09-01T12:00:00+00:00"},
    ]
    report = build_campaign_report(leads, {"g", "n"}, {"g"}, {}, "lead", "30d")
    s = build_report_summary(report, leads, {})
    assert sum(c["leads"] for c in s["channels"]) == s["funnel"]["leads"] == 3


def test_days_to_purchase_median_drops_negative_and_invalid():
    leads = [
        {"id": "a", "created_at": "2026-09-01T12:00:00+00:00"},
        {"id": "b", "created_at": "2026-09-01T12:00:00Z"},
        # importado do Bling: created_at = data da importação, compra ANTERIOR -> descartado
        {"id": "c", "created_at": "2026-09-20T12:00:00+00:00"},
        {"id": "d", "created_at": "nao-e-data"},
        {"id": "e", "created_at": "2026-09-01T12:00:00+00:00"},  # sem venda
    ]
    sales = {
        "a": {"count": 1, "value": 10.0, "first_sold_at": "2026-09-11T12:00:00+00:00"},
        "b": {"count": 1, "value": 10.0, "first_sold_at": "2026-09-05T12:00:00+00:00"},
        "c": {"count": 1, "value": 10.0, "first_sold_at": "2026-08-01T12:00:00+00:00"},
        "d": {"count": 1, "value": 10.0, "first_sold_at": "2026-09-05T12:00:00+00:00"},
    }
    tq = build_report_summary(_report(_t(leads=5, clientes=4, pedidos=4)), leads, sales)["timing_quality"]
    assert tq["dias_ate_compra_mediana"] == 7.0
    assert tq["amostra_dias"] == 2


def test_repurchase_and_orders_per_client():
    leads = [{"id": "a"}, {"id": "b"}]
    sales = {"a": {"count": 2, "value": 20.0}, "b": {"count": 1, "value": 10.0}}
    tq = build_report_summary(_report(_t(leads=2, clientes=2, pedidos=3)), leads, sales)["timing_quality"]
    assert tq["pedidos_por_cliente"] == 1.5
    assert tq["recompra_pct"] == 0.5


def test_tracking_quality_percentages():
    rows = [
        {"channel": "Google Ads", "campaign": "(não atribuído) · x", "leads": 3},
        {"channel": "Google Ads", "campaign": "Search Atacado", "leads": 7},
        {"channel": "Sem rastreio", "campaign": "(sem campanha)", "leads": 5},
        {"channel": "Orgânico", "campaign": "(não atribuído) · nao-conta", "leads": 5},
    ]
    subs = {"Google Ads": _t(leads=10), "Sem rastreio": _t(leads=5), "Orgânico": _t(leads=5)}
    tq = build_report_summary(_report(_t(leads=20), subs, rows), [], {})["timing_quality"]
    assert tq["nao_atribuido_pct"] == 0.3
    assert tq["sem_rastreio_pct"] == 0.25


def test_sales_by_lead_tracks_first_sold_at(monkeypatch):
    rows = [
        {"lead_id": "a", "value": 10, "sold_at": "2026-09-10T10:00:00+00:00"},
        {"lead_id": "a", "value": 5, "sold_at": "2026-09-02T10:00:00+00:00"},
        {"lead_id": "a", "value": 1, "sold_at": "2026-09-20T10:00:00+00:00"},
    ]
    monkeypatch.setattr(tr, "_fetch_all", lambda build, page=1000: rows)
    out = _sales_by_lead(None, ["a"], None, None, "lead")
    assert out["a"]["first_sold_at"] == "2026-09-02T10:00:00+00:00"
    assert out["a"]["last_sold_at"] == "2026-09-20T10:00:00+00:00"
    assert out["a"]["count"] == 3


def test_traffic_report_includes_summary(monkeypatch):
    leads = [{"id": "a", "created_at": "2026-09-01T12:00:00+00:00"}]
    monkeypatch.setattr(tr, "get_supabase", lambda: None)
    monkeypatch.setattr(tr, "_fetch_leads", lambda sb, mode, lo, hi: leads)
    monkeypatch.setattr(tr, "_conversed_ids", lambda sb, ids: {"a"})
    monkeypatch.setattr(tr, "_closer_ids", lambda sb, ids: set())
    monkeypatch.setattr(tr, "_sales_by_lead", lambda sb, ids, lo, hi, mode: {})
    monkeypatch.setattr(tr, "_spend_by_channel", lambda sb, lo, hi: {})
    monkeypatch.setattr(tr, "_meta_campaign_by_lead", lambda sb, ls: {})
    out = tr.traffic_report("30d", "lead")
    assert out["summary"]["funnel"]["leads"] == 1
    assert out["summary"]["funnel"]["taxa_conversa"] == 1.0
```

- [ ] **Step 2: Rodar e ver falhar**

Run (em `backend/`): `python -m pytest tests/test_traffic_report_summary.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_report_summary'`.

- [ ] **Step 3: Implementar**

Em `backend/app/campaigns/traffic_report.py`:

(a) Imports — acrescentar `from statistics import median` junto dos outros imports da stdlib.

(b) Em `_sales_by_lead`, o `setdefault` passa a ser
`{"count": 0, "value": 0.0, "last_sold_at": None, "first_sold_at": None}` e, logo após o
bloco que atualiza `last_sold_at` (dentro do mesmo `if isinstance(sold_at, str) and sold_at:`):

```python
                first = agg["first_sold_at"]
                if first is None or sold_at < first:
                    agg["first_sold_at"] = sold_at
```

(c) Nova função pura, colocada logo depois de `build_campaign_report`:

```python
# --- Relatório geral (bloco acima da tabela) -------------------------------------------
_PAID_CHANNELS = ("Google Ads", "Meta Ads")
_CHANNEL_ORDER = ("Google Ads", "Meta Ads", "Orgânico", "Sem rastreio")
_FUNNEL_STAGES = ("conversa", "closer", "cliente")
_COUNT_KEYS = ("leads", "conversas", "closer", "clientes")


def _ratio(num: float, den: float, nd: int = 4) -> float | None:
    return round(num / den, nd) if den else None


def _parse_iso(v: Any) -> datetime | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _stage_rates(c: dict[str, int]) -> dict[str, float | None]:
    return {
        "taxa_conversa": _ratio(c["conversas"], c["leads"]),
        "taxa_closer": _ratio(c["closer"], c["conversas"]),
        "taxa_cliente": _ratio(c["clientes"], c["closer"]),
        "taxa_total": _ratio(c["clientes"], c["leads"]),
    }


def _counts(d: dict[str, Any]) -> dict[str, int]:
    return {k: int(d.get(k, 0) or 0) for k in _COUNT_KEYS}


def build_report_summary(report: dict[str, Any], leads: list[dict[str, Any]],
                         sales_by_lead: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Relatório geral do período — puro, deriva tudo do relatório já montado.

    Custo por etapa divide o gasto SÓ pelas contagens dos canais pagos: dividir pelo total
    (orgânico incluso) faria o CPL parecer mais barato do que é. Os dias até a 1ª compra
    descartam valores negativos — os 1.208 leads importados do Bling têm created_at = data
    da importação e compras anteriores a ela, e puxariam a mediana para baixo de zero.
    """
    total = report.get("total") or {}
    subtotals = report.get("channel_subtotals") or {}
    rows = report.get("rows") or []

    counts = _counts(total)
    rates = _stage_rates(counts)
    candidates = [(rates["taxa_" + s], i, s) for i, s in enumerate(_FUNNEL_STAGES)
                  if rates["taxa_" + s] is not None]
    funnel = {**counts, **rates, "gargalo": min(candidates)[2] if candidates else None}

    paid = dict.fromkeys(_COUNT_KEYS, 0)
    inv = rec = 0.0
    for ch in _PAID_CHANNELS:
        sub = subtotals.get(ch)
        if not sub:
            continue
        for k, v in _counts(sub).items():
            paid[k] += v
        inv += float(sub.get("investimento", 0) or 0)
        rec += float(sub.get("receita", 0) or 0)

    def _cost(den: int) -> float | None:
        return round(inv / den, 2) if inv and den else None

    cost = {"investimento": round(inv, 2), "receita": round(rec, 2),
            "roas": round(rec / inv, 2) if inv else None, **paid,
            "cpl": _cost(paid["leads"]), "custo_conversa": _cost(paid["conversas"]),
            "custo_closer": _cost(paid["closer"]), "cac": _cost(paid["clientes"])}

    order = [c for c in _CHANNEL_ORDER if c in subtotals]
    order += sorted(c for c in subtotals if c not in _CHANNEL_ORDER)
    channels: list[dict[str, Any]] = []
    for ch in order:
        sub = subtotals[ch]
        c = _counts(sub)
        inv_ch = round(float(sub.get("investimento", 0) or 0), 2)
        if c["leads"] == 0 and inv_ch == 0:
            continue
        rec_ch = round(float(sub.get("receita", 0) or 0), 2)
        channels.append({"channel": ch, **c, "receita": rec_ch, "investimento": inv_ch,
                         "roas": round(rec_ch / inv_ch, 2) if inv_ch else None,
                         **_stage_rates(c)})

    dias: list[float] = []
    recompradores = 0
    for lead in leads:
        sale = sales_by_lead.get(lead.get("id"))
        if not sale:
            continue
        if int(sale.get("count", 0) or 0) > 1:
            recompradores += 1
        created = _parse_iso(lead.get("created_at"))
        first = _parse_iso(sale.get("first_sold_at"))
        if created is None or first is None:
            continue
        d = (first - created).total_seconds() / 86400
        if d >= 0:
            dias.append(d)

    clientes = counts["clientes"]
    pedidos = int(total.get("pedidos", 0) or 0)
    nao_atribuido = sum(int(r.get("leads", 0) or 0) for r in rows
                        if r.get("channel") in _PAID_CHANNELS
                        and str(r.get("campaign", "")).startswith(_UNATTRIBUTED))
    sem_rastreio = int((subtotals.get("Sem rastreio") or {}).get("leads", 0) or 0)
    timing_quality = {
        "dias_ate_compra_mediana": round(median(dias), 1) if dias else None,
        "amostra_dias": len(dias),
        "pedidos_por_cliente": _ratio(pedidos, clientes, 2),
        "recompra_pct": _ratio(recompradores, clientes),
        "sem_rastreio_pct": _ratio(sem_rastreio, counts["leads"]),
        "nao_atribuido_pct": _ratio(nao_atribuido, paid["leads"]),
    }
    return {"funnel": funnel, "cost": cost, "channels": channels,
            "timing_quality": timing_quality}
```

(d) `_empty_report` passa a montar o dict numa variável e anexar o resumo:

```python
def _empty_report(mode: str, period: str) -> dict[str, Any]:
    report = {"mode": mode, "period": period, "rows": [], "channel_subtotals": {},
              "total": {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
                        "receita": 0.0, "investimento": 0.0, "roas": None}}
    report["summary"] = build_report_summary(report, [], {})
    return report
```

(e) Em `traffic_report`, trocar `return build_campaign_report(...)` por:

```python
        report = build_campaign_report(
            leads, conversed, closers, sales, mode, period,
            spend_by_channel=_spend_by_channel(sb, lo, hi),
            campaign_id_by_lead=_meta_campaign_by_lead(sb, leads),
        )
        report["summary"] = build_report_summary(report, leads, sales)
        return report
```

- [ ] **Step 4: Rodar e ver passar (e sem regressão)**

Run (em `backend/`): `python -m pytest tests/test_traffic_report_summary.py tests/test_traffic_report.py tests/test_traffic_report_fuso_e_meta_ad_id.py -q`
Expected: tudo PASS.

- [ ] **Step 5: NÃO comitar** — o orquestrador comita.

---

### Task 2: Frontend — lib, componente e página

**Files:**
- Create: `frontend/src/lib/traffic-summary.ts`
- Create: `frontend/src/lib/traffic-summary.test.ts`
- Create: `frontend/src/components/trafego/report-summary.tsx`
- Modify: `frontend/src/components/trafego/campaign-report-table.tsx` (exportar `CHANNEL_STYLES`)
- Modify: `frontend/src/app/(authenticated)/trafego/page.tsx`

Antes de escrever UI: invocar a skill `frontend-design:frontend-design` (preferência registrada do usuário) e a skill `dataviz` (barras do funil). Ler `page.tsx`, `campaign-report-table.tsx` e `campaign-kpis.tsx` para seguir a paleta e a tipografia.

- [ ] **Step 1: Teste da lib (falhando)**

Criar `frontend/src/lib/traffic-summary.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { collapsedLine, fmtBRLOrDash, fmtDays, fmtPctOrDash, fmtRoasOrDash, type ReportSummary } from "./traffic-summary";

const base: ReportSummary = {
  funnel: { leads: 1240, conversas: 612, closer: 188, clientes: 41, taxa_conversa: 0.4935, taxa_closer: 0.3072, taxa_cliente: 0.2181, taxa_total: 0.0331, gargalo: "cliente" },
  cost: { investimento: 0, receita: 0, roas: null, leads: 0, conversas: 0, closer: 0, clientes: 0, cpl: null, custo_conversa: null, custo_closer: null, cac: null },
  channels: [],
  timing_quality: { dias_ate_compra_mediana: null, amostra_dias: 0, pedidos_por_cliente: null, recompra_pct: null, sem_rastreio_pct: null, nao_atribuido_pct: null },
};

describe("traffic-summary", () => {
  it("formata nulo como travessão", () => {
    expect(fmtBRLOrDash(null)).toBe("—");
    expect(fmtPctOrDash(null)).toBe("—");
    expect(fmtRoasOrDash(null)).toBe("—");
    expect(fmtDays(null)).toBe("—");
  });
  it("formata valores", () => {
    expect(fmtBRLOrDash(1234.5)).toBe("R$ 1.234,50");
    expect(fmtPctOrDash(0.4936)).toBe("49.4%");
    expect(fmtRoasOrDash(3)).toBe("3,0x");
    expect(fmtDays(1)).toBe("1 dia");
    expect(fmtDays(7.5)).toBe("7,5 dias");
  });
  it("monta a linha do bloco recolhido", () => {
    expect(collapsedLine(base)).toBe("1.240 leads → 612 conversas → 188 closer → 41 clientes");
  });
});
```

(`fmtPctOrDash` usa `toFixed(1)` de propósito — é o mesmo formato da coluna Conversão da tabela logo abaixo.)

- [ ] **Step 2: Rodar e ver falhar**

Run (em `frontend/`): `npx vitest run src/lib/traffic-summary.test.ts`
Expected: FAIL — módulo `./traffic-summary` não existe.

- [ ] **Step 3: Implementar a lib**

Criar `frontend/src/lib/traffic-summary.ts`:

```ts
// Contrato de `summary` devolvido por GET /api/traffic/report (backend: build_report_summary).
// Taxas são frações 0..1; null = denominador zero (exibir "—", nunca 0).

export type SummaryStage = "conversa" | "closer" | "cliente";

export type StageRates = {
  taxa_conversa: number | null;
  taxa_closer: number | null;
  taxa_cliente: number | null;
  taxa_total: number | null;
};

export type StageCounts = { leads: number; conversas: number; closer: number; clientes: number };

export type SummaryFunnel = StageCounts & StageRates & { gargalo: SummaryStage | null };

export type SummaryCost = StageCounts & {
  investimento: number; receita: number; roas: number | null;
  cpl: number | null; custo_conversa: number | null; custo_closer: number | null; cac: number | null;
};

export type SummaryChannel = StageCounts & StageRates & {
  channel: string; receita: number; investimento: number; roas: number | null;
};

export type SummaryTiming = {
  dias_ate_compra_mediana: number | null;
  amostra_dias: number;
  pedidos_por_cliente: number | null;
  recompra_pct: number | null;
  sem_rastreio_pct: number | null;
  nao_atribuido_pct: number | null;
};

export type ReportSummary = {
  funnel: SummaryFunnel;
  cost: SummaryCost;
  channels: SummaryChannel[];
  timing_quality: SummaryTiming;
};

export const STAGE_LABEL: Record<SummaryStage, string> = {
  conversa: "Lead → Conversa",
  closer: "Conversa → Closer",
  cliente: "Closer → Cliente",
};

const DASH = "—";

export const fmtInt = (v: number) => v.toLocaleString("pt-BR");

export const fmtBRLOrDash = (v: number | null | undefined) =>
  v == null ? DASH : `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export const fmtPctOrDash = (v: number | null | undefined) =>
  v == null ? DASH : `${(v * 100).toFixed(1)}%`;

export const fmtRoasOrDash = (v: number | null | undefined) =>
  v == null ? DASH : `${v.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}x`;

export const fmtDays = (v: number | null | undefined) => {
  if (v == null) return DASH;
  if (v === 1) return "1 dia";
  return `${v.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} dias`;
};

export const collapsedLine = (s: ReportSummary) => {
  const f = s.funnel;
  return `${fmtInt(f.leads)} leads → ${fmtInt(f.conversas)} conversas → ${fmtInt(f.closer)} closer → ${fmtInt(f.clientes)} clientes`;
};
```

- [ ] **Step 4: Rodar e ver passar**

Run (em `frontend/`): `npx vitest run src/lib/traffic-summary.test.ts`
Expected: PASS (3 testes).

- [ ] **Step 5: Exportar as cores de canal**

Em `frontend/src/components/trafego/campaign-report-table.tsx`, trocar
`const CHANNEL_STYLES: Record<string, string> = {` por
`export const CHANNEL_STYLES: Record<string, string> = {`. Nada mais muda.

- [ ] **Step 6: Componente `report-summary.tsx`**

Criar `frontend/src/components/trafego/report-summary.tsx` com `"use client"` e export
`ReportSummaryPanel({ summary, mode }: { summary: ReportSummary; mode: "lead" | "sale" })`.

Requisitos (o design visual fica com a skill frontend-design, dentro destas regras):

- Card `bg-white border border-[#dedbd6] rounded-[8px]`, título "Relatório geral" (11px
  uppercase tracking-[0.6px] `#7b7b78`, como o `TH` da tabela) e botão Recolher/Expandir
  (`aria-expanded`) à direita.
- Estado `collapsed` inicial `false`; num `useEffect` lê
  `localStorage.getItem("trafego:summary-collapsed") === "1"` dentro de try/catch; o toggle
  grava `"1"`/`"0"` também em try/catch.
- **Recolhido:** só o cabeçalho, com `collapsedLine(summary)` (tabular-nums) no lugar do título.
- **Expandido — 4 faixas** (grid `grid-cols-1 lg:grid-cols-2`, gap-3; cada faixa com rótulo 11px uppercase):
  1. **Funil**: 4 barras horizontais (Leads, Conversas, Closer, Clientes), largura
     `max(2%, n / funnel.leads)`, número à direita. Entre barras, a taxa de passagem
     (`fmtPctOrDash`). A transição igual a `funnel.gargalo` ganha destaque (texto `#ff5600`
     + legenda "gargalo"). Rodapé: "Lead → cliente: {fmtPctOrDash(taxa_total)}".
     Se `mode === "sale"`: as taxas saem e aparece a nota "No modo Por venda a base já é quem
     comprou — leia o funil no modo Por lead."
  2. **Custo por etapa (Google + Meta)**: Investimento, CPL, Custo por conversa, Custo por
     closer, CAC (`fmtBRLOrDash`) e ROAS (`fmtRoasOrDash`). Se `cost.investimento === 0`:
     "Sem investimento sincronizado no período."
  3. **Canais**: uma linha por item de `summary.channels` com o badge na cor de
     `CHANNEL_STYLES[channel] ?? CHANNEL_STYLES["Sem rastreio"]`, contagens
     `leads → conversas → closer → clientes`, taxa total e receita/ROAS. Lista vazia: "Nenhum canal no período."
  4. **Tempo e qualidade**: "Até a 1ª compra (mediana)" = `fmtDays` + legenda
     "{amostra_dias} clientes"; "Pedidos por cliente" = `pedidos_por_cliente` com 2 casas pt-BR ou "—";
     "Recompra" = `fmtPctOrDash(recompra_pct)`; "Sem rastreio" = `fmtPctOrDash(sem_rastreio_pct)`;
     "Pagos sem campanha" = `fmtPctOrDash(nao_atribuido_pct)`.
- Números em `tabular-nums`; cores só da paleta da página (`#111111`, `#7b7b78`, `#dedbd6`,
  `#faf9f6`, `#ff5600` para destaque). Sem bibliotecas novas.

- [ ] **Step 7: Ligar na página**

Em `frontend/src/app/(authenticated)/trafego/page.tsx`:

(a) imports:
```ts
import { ReportSummaryPanel } from "@/components/trafego/report-summary";
import type { ReportSummary } from "@/lib/traffic-summary";
```
(b) `type Report = { mode: string; period: string; rows: CampaignRow[]; total: ReportTotal; channel_subtotals: ChannelSubtotals; summary?: ReportSummary };`
(c) Substituir o bloco `{/* Content */}` por:

```tsx
      {/* Content — rola como um todo: o resumo expandido não pode espremer a tabela */}
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-4 px-4 md:px-8 py-4 md:py-8 bg-[#faf9f6]">
        {loading ? (
          <>
            <Skeleton className="h-[220px] w-full flex-shrink-0 rounded-[8px]" />
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4 md:p-5 space-y-2">
              {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
            </div>
          </>
        ) : (
          <>
            {report?.summary && (
              <div className="flex-shrink-0">
                <ReportSummaryPanel summary={report.summary} mode={mode} />
              </div>
            )}
            <div className="bg-white border border-[#dedbd6] rounded-[8px] flex-1 min-h-[420px] flex flex-col overflow-hidden">
              <CampaignReportTable
                ...props existentes, sem alteração...
              />
            </div>
          </>
        )}
      </div>
```
(mantendo exatamente as props e o `onRowClick` atuais da `CampaignReportTable`).

- [ ] **Step 8: Verificar**

Run (em `frontend/`): `npx vitest run src/lib/traffic-summary.test.ts` → PASS;
`npx tsc --noEmit -p .` → sem erros novos nos arquivos tocados;
`npx eslint src/lib/traffic-summary.ts src/components/trafego/report-summary.tsx "src/app/(authenticated)/trafego/page.tsx" src/components/trafego/campaign-report-table.tsx` → limpo.

- [ ] **Step 9: NÃO comitar** — o orquestrador comita.

---

### Task 3: Integração (orquestrador)

- [ ] Rodar a suíte backend do tráfego e o vitest completo do frontend; `npx next build` no frontend.
- [ ] Revisar o diff (review de spec + qualidade).
- [ ] Commits separados: `feat(trafego): resumo geral no relatorio (backend)` e `feat(trafego): bloco Relatorio geral acima da tabela`.
- [ ] Não fazer push — o push para master é decisão do usuário (CLAUDE.md).
