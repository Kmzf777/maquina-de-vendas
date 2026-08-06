# /trafego — Página de detalhe da campanha — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps usam checkbox (`- [ ]`).
>
> **FRONTEND RULE:** Toda task que toque `frontend/src` DEVE usar `frontend-design` + shadcn/ui (ver memory `feedback_frontend_skill`). recharts@3 já está instalado (usado no dashboard).

**Goal:** Trocar o drawer lateral por uma página `/trafego/campanha` com KPIs, gráfico (recharts) e a lista completa de leads da campanha.

**Architecture:** Endpoint dedicado `/api/traffic/campaign` retorna `{summary, leads, timeseries}` reusando a lógica de agregação. A página lê channel/campaign/período via query params, renderiza KPIs + gráfico + tabela; a tabela principal passa a navegar em vez de abrir o drawer.

**Tech Stack:** FastAPI, Supabase, pytest; Next.js App Router, TS, shadcn/ui, recharts.

**Spec:** `docs/superpowers/specs/2026-08-06-trafego-pagina-detalhe-campanha-design.md`.

---

## File Structure
- Modify `backend/app/campaigns/traffic_report.py` — `campaign_detail` + timeseries puro + `_empty_summary`.
- Modify `backend/tests/test_traffic_report.py` — testes.
- Modify `backend/app/campaigns/traffic_router.py` — endpoint `/api/traffic/campaign`.
- Create `frontend/src/app/api/traffic/campaign/route.ts` — proxy admin-gated.
- Create `frontend/src/components/trafego/campaign-kpis.tsx`, `campaign-timeseries.tsx`, `campaign-leads-table.tsx`.
- Create `frontend/src/app/(authenticated)/trafego/campanha/page.tsx` — página de detalhe.
- Modify `frontend/src/app/(authenticated)/trafego/page.tsx` — navegar em vez de abrir drawer.
- Delete `frontend/src/components/trafego/campaign-leads-drawer.tsx`.

**Contrato:** `CampaignDetail = { summary: CampaignRow, leads: CampaignLead[], timeseries: {date,leads,vendas,receita}[] }`.

---

## Task 1: backend `campaign_detail` + timeseries

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py`
- Test: `backend/tests/test_traffic_report.py`

- [ ] **Step 1: Testes (falham)**

```python
# adicionar em backend/tests/test_traffic_report.py
from datetime import date
from app.campaigns.traffic_report import build_campaign_timeseries, _empty_summary


def test_empty_summary_has_all_keys():
    s = _empty_summary("Google Ads", "atacado")
    for k in ("channel","campaign","leads","conversas","closer","clientes","pedidos",
              "receita","ticket_medio","conversao","investimento","roas"):
        assert k in s
    assert s["channel"] == "Google Ads" and s["campaign"] == "atacado"
    assert s["leads"] == 0 and s["roas"] is None


def test_build_campaign_timeseries_buckets_by_day():
    days = [date(2026, 8, 1), date(2026, 8, 2)]
    leads = [{"created_at": "2026-08-01T10:00:00+00:00"},
             {"created_at": "2026-08-01T12:00:00+00:00"},
             {"created_at": "2026-08-02T09:00:00+00:00"}]
    sales = [{"value": 100.0, "sold_at": "2026-08-02T15:00:00+00:00"}]
    ts = build_campaign_timeseries(days, leads, sales)
    by = {p["date"]: p for p in ts}
    assert by["2026-08-01"]["leads"] == 2 and by["2026-08-01"]["vendas"] == 0
    assert by["2026-08-02"]["leads"] == 1 and by["2026-08-02"]["vendas"] == 1
    assert by["2026-08-02"]["receita"] == 100.0


def test_campaign_detail_end_to_end(monkeypatch):
    import app.campaigns.traffic_report as tr
    tables = {
        "leads": [{"id": "a", "gclid": "1", "fbclid": "", "ctwa_clid": "", "utm_source": "",
                   "utm_campaign": "atacado", "traffic_type": "paid", "name": "Ana", "phone": "5511",
                   "created_at": "2026-08-01T10:00:00+00:00"}],
        "conversations": [], "deals": [], "pipeline_stages": [], "ad_spend": [],
        "sales": [{"lead_id": "a", "value": 200.0, "sold_at": "2026-08-02T10:00:00+00:00"}],
    }
    # Fake supabase reutilizando o _FakeSupabase já existente nos testes deste arquivo.
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    out = tr.campaign_detail("Google Ads", "atacado", period="30d", mode="lead")
    assert out["summary"]["channel"] == "Google Ads"
    assert out["summary"]["leads"] == 1
    assert isinstance(out["leads"], list) and out["leads"][0]["lead_id"] == "a"
    assert isinstance(out["timeseries"], list)
```

> Nota: este teste reusa `_FakeSupabase` já definido no arquivo (Task 3 do plano original de traffic). Se a assinatura do fake não suportar `lte`/`gte`, ele já os ignora (retorna todas as linhas) — suficiente aqui.

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: FAIL (ImportError build_campaign_timeseries/_empty_summary).

- [ ] **Step 3: Implementar** — em `traffic_report.py`.

Garantir imports no topo:
```python
from datetime import date  # somar aos imports datetime existentes
from zoneinfo import ZoneInfo
```
E constante (perto de `_TZ`/topo do módulo; se `_TZ` não existir, criar):
```python
_TZ = ZoneInfo("America/Sao_Paulo")
```

Adicionar as funções:
```python
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
        spend = _spend_by_campaign(sb, lo, hi)
        report = build_campaign_report(selected, conversed, closers, sales, mode, period,
                                       spend_by_campaign=spend)
        summary = report["rows"][0] if report.get("rows") else _empty_summary(channel, campaign)
        leads = campaign_leads(channel, campaign, period, mode, date_from, date_to)
        sales_rows: list[dict[str, Any]] = []
        for chunk in _chunks(lead_ids):
            q = sb.table("sales").select("value, sold_at").in_("lead_id", chunk)
            if mode == "sale" and lo:
                q = q.gte("sold_at", lo)
            if mode == "sale" and hi:
                q = q.lte("sold_at", hi)
            sales_rows.extend(q.execute().data or [])
        timeseries = build_campaign_timeseries(_daterange_days(lo, hi), selected, sales_rows)
        return {"summary": summary, "leads": leads, "timeseries": timeseries}
    except Exception as exc:
        logger.error("campaign_detail(%s,%s) falhou: %s", channel, campaign, exc, exc_info=True)
        return {"summary": _empty_summary(channel, campaign), "leads": [], "timeseries": []}
```

- [ ] **Step 4: Rodar e ver passar + suíte**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`  → PASS.
Run: `cd backend; python -m pytest -q`  → sem regressão.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/traffic_report.py backend/tests/test_traffic_report.py
git commit -m "feat(trafego): campaign_detail (summary+leads+timeseries)"
```

---

## Task 2: endpoint `/api/traffic/campaign`

**Files:**
- Modify: `backend/app/campaigns/traffic_router.py`
- Test: `backend/tests/test_traffic_report.py`

- [ ] **Step 1: Teste (falha)**

```python
def test_router_exposes_campaign_path():
    from app.campaigns.traffic_router import router
    assert "/api/traffic/campaign" in {r.path for r in router.routes}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py::test_router_exposes_campaign_path -q`
Expected: FAIL.

- [ ] **Step 3: Implementar** — em `traffic_router.py`, importar e adicionar:

```python
from app.campaigns.traffic_report import traffic_report, campaign_leads, campaign_detail


@router.get("/campaign")
async def traffic_campaign_endpoint(channel: str, campaign: str, period: str = "30d",
                                    mode: str = "lead", date_from: str | None = None,
                                    date_to: str | None = None):
    """Detalhe completo de uma campanha (KPIs + leads + série). Admin-only na UI."""
    mode = mode if mode in ("lead", "sale") else "lead"
    return campaign_detail(channel=channel, campaign=campaign, period=period, mode=mode,
                           date_from=date_from, date_to=date_to)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q` → PASS.
Run: `cd backend; python -c "import app.main"` → sem erro.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/traffic_router.py backend/tests/test_traffic_report.py
git commit -m "feat(trafego): endpoint /api/traffic/campaign"
```

---

## Task 3: proxy Next admin-gated `/api/traffic/campaign`

**Files:**
- Create: `frontend/src/app/api/traffic/campaign/route.ts`

- [ ] **Step 1: Criar o proxy** (espelhar `report/route.ts`, incluindo date_from/date_to)

```typescript
// frontend/src/app/api/traffic/campaign/route.ts
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
  const dateFrom = searchParams.get("date_from") || "";
  const dateTo = searchParams.get("date_to") || "";
  const params: Record<string, string> = { channel, campaign, period, mode };
  if (dateFrom) params.date_from = dateFrom;
  if (dateTo) params.date_to = dateTo;
  const qs = new URLSearchParams(params).toString();
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  try {
    const resp = await fetch(`${backendUrl}/api/traffic/campaign?${qs}`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "campaign_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "campaign_unreachable" }, { status: 502 });
  }
}
```

- [ ] **Step 2: Validar**

Run: `cd frontend; npm run type-check` → limpo.
Run: `cd frontend; npx eslint "src/app/api/traffic"` → limpo.

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/api/traffic/campaign"
git commit -m "feat(trafego): proxy admin-gated /api/traffic/campaign"
```

---

## Task 4: componentes + página de detalhe (shadcn + recharts)

**Files:**
- Create: `frontend/src/components/trafego/campaign-leads-table.tsx`
- Create: `frontend/src/components/trafego/campaign-kpis.tsx`
- Create: `frontend/src/components/trafego/campaign-timeseries.tsx`
- Create: `frontend/src/app/(authenticated)/trafego/campanha/page.tsx`

> **FRONTEND (obrigatório):** usar `frontend-design` + shadcn/ui. Paleta do projeto
> (`#ff5600`, `#111111`, `#faf9f6`, `#dedbd6`, `#7b7b78`, `#0bdf50`). recharts para o gráfico
> (ver `frontend/src/components/dashboard/*` como referência de uso). Manter consistência com
> o `campaign-report-table.tsx` (badge de canal, `tabular-nums`, formatação pt-BR). O código
> abaixo é base funcional correta; refine o visual conforme a skill sem mudar o contrato.

- [ ] **Step 1: Tabela de leads completa + busca** — `campaign-leads-table.tsx`. Exporta o
  type `CampaignLead` (movido do drawer que será removido). Colunas: Lead (nome/telefone),
  Origem (Pago/Orgânico), utm_source, utm_medium, Etapa, Conversou (Sim/Não), Entrada (data),
  Venda (data + valor). Input de busca (client-side) filtrando por `name`/`phone`. Estados de
  loading (skeleton) e vazio ("Nenhum lead nesta campanha."). Usar shadcn `Table`, `Input`,
  `Skeleton`, e um badge de origem (reaproveitar o `OriginBadge` do drawer antigo).

```tsx
"use client";
import { useState } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";

export type CampaignLead = {
  lead_id: string; name: string | null; phone: string | null; created_at: string | null;
  utm_source: string | null; utm_medium: string | null; utm_campaign: string | null;
  traffic_type: string | null; conversou: boolean; stage: string | null;
  comprou: boolean; valor: number; sold_at: string | null;
};
const fmtBRL = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
const fmtDate = (v: string | null) => { if (!v) return "—"; try { return new Date(v).toLocaleDateString("pt-BR"); } catch { return "—"; } };

function OriginBadge({ trafficType }: { trafficType: string | null }) {
  const isPaid = trafficType === "paid", isOrganic = trafficType === "organic";
  const style = isPaid ? "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20"
    : isOrganic ? "bg-[#0bdf50]/10 text-[#0f9d43] border-[#0bdf50]/20"
    : "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]";
  return <span className={`inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-[4px] border whitespace-nowrap ${style}`}>{isPaid ? "Pago" : isOrganic ? "Orgânico" : "—"}</span>;
}

export function CampaignLeadsTable({ leads }: { leads: CampaignLead[] }) {
  const [q, setQ] = useState("");
  const norm = (s: string) => s.toLowerCase();
  const filtered = q ? leads.filter(l => norm(`${l.name ?? ""} ${l.phone ?? ""}`).includes(norm(q))) : leads;
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
      <div className="p-3 border-b border-[#dedbd6]">
        <Input placeholder="Buscar por nome ou telefone…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs text-[14px]" />
      </div>
      <div className="overflow-auto">
        <Table>
          <TableHeader><TableRow className="hover:bg-transparent">
            {["Lead","Origem","Fonte","Meio","Etapa","Conversou","Entrada","Venda"].map(h =>
              <TableHead key={h} className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78] whitespace-nowrap">{h}</TableHead>)}
          </TableRow></TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow><TableCell colSpan={8} className="text-center text-[14px] text-[#7b7b78] py-8">Nenhum lead nesta campanha.</TableCell></TableRow>
            ) : filtered.map(l => (
              <TableRow key={l.lead_id} className="border-[#dedbd6] hover:bg-[#faf9f6]">
                <TableCell className="text-[14px] text-[#111111] font-medium max-w-[200px] truncate">{l.name || l.phone || l.lead_id}</TableCell>
                <TableCell><OriginBadge trafficType={l.traffic_type} /></TableCell>
                <TableCell className="text-[13px] text-[#7b7b78]">{l.utm_source || "—"}</TableCell>
                <TableCell className="text-[13px] text-[#7b7b78]">{l.utm_medium || "—"}</TableCell>
                <TableCell className="text-[13px] text-[#7b7b78]">{l.stage || "—"}</TableCell>
                <TableCell className="text-[13px] text-[#7b7b78]">{l.conversou ? "Sim" : "Não"}</TableCell>
                <TableCell className="text-[13px] tabular-nums text-[#7b7b78]">{fmtDate(l.created_at)}</TableCell>
                <TableCell className={`text-[13px] tabular-nums ${l.comprou ? "text-[#111111] font-medium" : "text-[#7b7b78]"}`}>{l.comprou ? <><span className="text-[#7b7b78] font-normal">{fmtDate(l.sold_at)} </span>{fmtBRL(l.valor)}</> : "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: KPI cards** — `campaign-kpis.tsx`. Recebe `summary: CampaignRow` (importar o
  type de `@/components/trafego/campaign-report-table`). Grid responsivo de cards (nº grande +
  rótulo). Mostrar Investimento e ROAS **apenas** quando `summary.channel === "Google Ads"`.

```tsx
"use client";
import type { CampaignRow } from "@/components/trafego/campaign-report-table";
const fmtBRL = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
const fmtInt = (v: number) => v.toLocaleString("pt-BR");
const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
const fmtRoas = (v: number | null) => v == null ? "—" : `${v.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}x`;

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
      <div className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">{label}</div>
      <div className="text-[22px] md:text-[26px] font-normal text-[#111111] mt-1 tabular-nums" style={{ letterSpacing: "-0.5px" }}>{value}</div>
    </div>
  );
}

export function CampaignKpis({ summary }: { summary: CampaignRow }) {
  const isGoogle = summary.channel === "Google Ads";
  const cards: { label: string; value: string }[] = [
    { label: "Leads", value: fmtInt(summary.leads) },
    { label: "Conversas", value: fmtInt(summary.conversas) },
    { label: "Foi pro closer", value: fmtInt(summary.closer) },
    { label: "Clientes", value: fmtInt(summary.clientes) },
    { label: "Pedidos", value: fmtInt(summary.pedidos) },
    { label: "Receita", value: fmtBRL(summary.receita) },
    { label: "Ticket médio", value: fmtBRL(summary.ticket_medio) },
    { label: "Conversão", value: fmtPct(summary.conversao) },
    ...(isGoogle ? [
      { label: "Investimento", value: fmtBRL(summary.investimento) },
      { label: "ROAS", value: fmtRoas(summary.roas) },
    ] : []),
  ];
  return <div className="grid grid-cols-2 md:grid-cols-4 gap-3">{cards.map(c => <Card key={c.label} {...c} />)}</div>;
}
```

- [ ] **Step 3: Gráfico** — `campaign-timeseries.tsx` com recharts. Recebe
  `data: {date,leads,vendas,receita}[]`. Barras de Leads + linha de Vendas por dia (ou duas
  barras). Reusar o padrão de `frontend/src/components/dashboard` (imports de recharts).
  Container responsivo, paleta do projeto.

```tsx
"use client";
import { ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
export type TsPoint = { date: string; leads: number; vendas: number; receita: number };
export function CampaignTimeseries({ data }: { data: TsPoint[] }) {
  const fmtDay = (d: string) => { try { return new Date(d + "T00:00:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }); } catch { return d; } };
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
      <div className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Evolução (leads × vendas por dia)</div>
      <div style={{ width: "100%", height: 240 }}>
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke="#f0ede8" vertical={false} />
            <XAxis dataKey="date" tickFormatter={fmtDay} tick={{ fontSize: 11, fill: "#7b7b78" }} tickLine={false} axisLine={{ stroke: "#dedbd6" }} minTickGap={16} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#7b7b78" }} tickLine={false} axisLine={false} width={28} />
            <Tooltip labelFormatter={fmtDay} contentStyle={{ borderRadius: 8, border: "1px solid #dedbd6", fontSize: 12 }} />
            <Bar dataKey="leads" name="Leads" fill="#ff5600" radius={[3, 3, 0, 0]} maxBarSize={22} />
            <Line dataKey="vendas" name="Vendas" stroke="#0bdf50" strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Página** — `trafego/campanha/page.tsx`. Lê query params (`useSearchParams`),
  gate admin (`useCurrentRole`), faz fetch de `/api/traffic/campaign?…`, renderiza cabeçalho
  com "← Voltar" (link para `/trafego`), `CampaignKpis`, `CampaignTimeseries`, `CampaignLeadsTable`.
  Envolver em `<Suspense>` (por causa de `useSearchParams`).

```tsx
"use client";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCurrentRole } from "@/hooks/use-current-role";
import { Skeleton } from "@/components/ui/skeleton";
import type { CampaignRow } from "@/components/trafego/campaign-report-table";
import { CampaignKpis } from "@/components/trafego/campaign-kpis";
import { CampaignTimeseries, type TsPoint } from "@/components/trafego/campaign-timeseries";
import { CampaignLeadsTable, type CampaignLead } from "@/components/trafego/campaign-leads-table";

type Detail = { summary: CampaignRow; leads: CampaignLead[]; timeseries: TsPoint[] };
const CHANNEL_STYLES: Record<string, string> = {
  "Google Ads": "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20",
  "Meta Ads": "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20",
  "Orgânico": "bg-[#0bdf50]/10 text-[#0f9d43] border-[#0bdf50]/20",
  "Sem rastreio": "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
};

function Inner() {
  const sp = useSearchParams();
  const { role, loading: roleLoading } = useCurrentRole();
  const channel = sp.get("channel") || "";
  const campaign = sp.get("campaign") || "";
  const period = sp.get("period") || "30d";
  const mode = sp.get("mode") || "lead";
  const dateFrom = sp.get("date_from") || "";
  const dateTo = sp.get("date_to") || "";
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (roleLoading || role !== "admin") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    const params: Record<string, string> = { channel, campaign, period, mode };
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    fetch(`/api/traffic/campaign?${new URLSearchParams(params).toString()}`)
      .then(r => r.json()).then((d: Detail) => setDetail(d)).catch(() => setDetail(null)).finally(() => setLoading(false));
  }, [channel, campaign, period, mode, dateFrom, dateTo, role, roleLoading]);

  const backQs = new URLSearchParams({ ...(period ? { period } : {}), mode, ...(dateFrom ? { date_from: dateFrom } : {}), ...(dateTo ? { date_to: dateTo } : {}) }).toString();
  if (!roleLoading && role !== "admin") return <div className="p-8 text-[14px] text-[#7b7b78]">Acesso restrito a administradores.</div>;

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-4 md:py-5 flex-shrink-0">
        <Link href={`/trafego?${backQs}`} className="text-[13px] text-[#7b7b78] hover:text-[#111111] transition-colors">← Voltar</Link>
        <div className="flex items-center gap-3 mt-2">
          <span className={`inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-[4px] border ${CHANNEL_STYLES[channel] ?? CHANNEL_STYLES["Sem rastreio"]}`}>{channel}</span>
          <h1 style={{ letterSpacing: "-0.6px" }} className="text-[22px] md:text-[28px] font-normal text-[#111111]">{campaign}</h1>
        </div>
      </div>
      <div className="flex-1 overflow-auto px-4 md:px-8 py-4 md:py-6 bg-[#faf9f6] space-y-5">
        {loading || !detail ? (
          <div className="space-y-4"><div className="grid grid-cols-2 md:grid-cols-4 gap-3">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-20 w-full" />)}</div><Skeleton className="h-60 w-full" /><Skeleton className="h-72 w-full" /></div>
        ) : (
          <>
            <CampaignKpis summary={detail.summary} />
            <CampaignTimeseries data={detail.timeseries} />
            <CampaignLeadsTable leads={detail.leads} />
          </>
        )}
      </div>
    </div>
  );
}

export default function CampaignDetailPage() {
  return <Suspense><Inner /></Suspense>;
}
```

- [ ] **Step 5: Validar**

Run: `cd frontend; npm run type-check` → limpo.
Run: `cd frontend; npx eslint "src/app/(authenticated)/trafego" "src/components/trafego" "src/app/api/traffic"` → limpo.

- [ ] **Step 6: Commit**

```bash
git add "frontend/src/app/(authenticated)/trafego/campanha" "frontend/src/components/trafego/campaign-kpis.tsx" "frontend/src/components/trafego/campaign-timeseries.tsx" "frontend/src/components/trafego/campaign-leads-table.tsx"
git commit -m "feat(trafego): pagina de detalhe da campanha (KPIs + grafico + tabela)"
```

---

## Task 5: navegação da tabela principal + remover drawer

**Files:**
- Modify: `frontend/src/app/(authenticated)/trafego/page.tsx`
- Delete: `frontend/src/components/trafego/campaign-leads-drawer.tsx`

> **FRONTEND:** frontend-design + shadcn.

- [ ] **Step 1: Navegar em vez de abrir drawer** — em `trafego/page.tsx`:
  - Importar `useRouter` de `next/navigation`.
  - Remover o import e o uso de `CampaignLeadsDrawer`, e o estado `selected`.
  - Trocar o `onRowClick` da `CampaignReportTable` para navegar, preservando os filtros:
```tsx
  const router = useRouter();
  const goToCampaign = (channel: string, campaign: string) => {
    const params: Record<string, string> = { channel, campaign, period, mode };
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    router.push(`/trafego/campanha?${new URLSearchParams(params).toString()}`);
  };
```
  e passar `onRowClick={(r) => goToCampaign(r.channel, r.campaign)}` para a tabela. Remover o `<CampaignLeadsDrawer .../>` do JSX.

- [ ] **Step 2: Deletar o drawer**

```bash
git rm frontend/src/components/trafego/campaign-leads-drawer.tsx
```
(Se algum outro arquivo importava o `CampaignLead` do drawer, apontar para
`@/components/trafego/campaign-leads-table`.)

- [ ] **Step 3: Validar**

Run: `cd frontend; npm run type-check` → limpo (sem referências ao drawer removido).
Run: `cd frontend; npx eslint "src/app/(authenticated)/trafego" "src/components/trafego"` → limpo.
Run: `cd frontend; npm run test` → 263 passed (proxy-coverage verde; `/trafego` e `/api/traffic` já cobertos).

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/app/(authenticated)/trafego/page.tsx"
git commit -m "feat(trafego): clique na campanha abre a pagina de detalhe (remove drawer)"
```

---

## Self-Review (autor)
- **Cobertura do spec:** endpoint dedicado summary+leads+timeseries → T1/T2; proxy admin → T3;
  página KPIs+gráfico+tabela+busca + componentes isolados → T4; navegação + remoção do drawer → T5. ✓
- **Placeholders:** nenhum.
- **Consistência de tipos:** `CampaignDetail = {summary: CampaignRow, leads: CampaignLead[], timeseries: TsPoint[]}`; `CampaignLead` movido p/ `campaign-leads-table.tsx` e reusado na página; `CampaignRow` importado de `campaign-report-table`; `campaign_detail`/`build_campaign_timeseries`/`_empty_summary` batem entre T1 e T2. Backend `summary` = `rows[0]` do `build_campaign_report` → mesmas chaves de `CampaignRow`.

## Validação final
- `cd backend; python -m pytest -q`; `cd frontend; npm run type-check` + `npm run test`.
