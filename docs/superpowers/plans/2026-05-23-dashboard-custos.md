# Dashboard de Custos Operacionais — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refatorar `/estatisticas` em dashboard de custos operacionais com WhatsApp (Marketing + Utilidade) e IA, usando shadcn Card/Table/Skeleton + recharts.

**Architecture:** Dois novos endpoints FastAPI em `/api/stats/whatsapp` e `/api/stats/whatsapp/daily` consultam `meta_webhook_logs` (outbound `send_template` com `success=true`) e fazem JOIN lógico com `message_templates.category` em Python para classificar MARKETING ($0.0617/msg) vs UTILITY ($0.0067/msg). O frontend chama 4 endpoints em paralelo e combina as séries diárias num único gráfico de 3 linhas.

**Tech Stack:** FastAPI + supabase-py (backend); Next.js App Router, shadcn/ui v4, recharts v3 (frontend); pytest + unittest.mock (testes).

**Spec:** `docs/superpowers/specs/2026-05-23-dashboard-custos-design.md`

---

## File Map

| Arquivo | Ação |
|---------|------|
| `backend/app/stats/router.py` | Modificar — adicionar 2 endpoints + 2 constantes de preço |
| `backend/tests/test_whatsapp_stats.py` | Criar — testes TDD para os 2 novos endpoints |
| `frontend/src/components/ui/card.tsx` | Criar via shadcn CLI |
| `frontend/src/components/ui/table.tsx` | Criar via shadcn CLI |
| `frontend/src/components/ui/skeleton.tsx` | Criar via shadcn CLI |
| `frontend/src/app/(authenticated)/estatisticas/page.tsx` | Reescrita completa |

---

## Task 1: Instalar componentes shadcn

**Files:**
- Create: `frontend/src/components/ui/card.tsx`
- Create: `frontend/src/components/ui/table.tsx`
- Create: `frontend/src/components/ui/skeleton.tsx`

- [ ] **Step 1: Adicionar os 3 componentes via CLI**

```bash
cd frontend
npx shadcn@latest add card table skeleton --yes
```

Expected: 3 arquivos criados em `src/components/ui/`.

- [ ] **Step 2: Verificar que os arquivos existem**

```bash
ls src/components/ui/
```

Expected: `card.tsx`, `table.tsx`, `skeleton.tsx` listados (junto com `button.tsx`, `badge.tsx`, etc.).

- [ ] **Step 3: Commit**

```bash
cd ..
git add frontend/src/components/ui/card.tsx frontend/src/components/ui/table.tsx frontend/src/components/ui/skeleton.tsx
git commit -m "feat(ui): add card, table, skeleton shadcn components"
```

---

## Task 2: Backend — endpoints de custo WhatsApp (TDD)

**Files:**
- Create: `backend/tests/test_whatsapp_stats.py`
- Modify: `backend/app/stats/router.py`

- [ ] **Step 1: Criar arquivo de testes**

Crie `backend/tests/test_whatsapp_stats.py` com o conteúdo:

```python
import pytest
from unittest.mock import MagicMock, patch
from datetime import date


def _make_sb(webhook_rows: list, template_rows: list) -> MagicMock:
    """Build a Supabase mock that routes by table name."""
    sb = MagicMock()

    def table_router(name: str):
        t = MagicMock()
        if name == "meta_webhook_logs":
            (
                t.select.return_value
                .eq.return_value
                .eq.return_value
                .eq.return_value
                .gte.return_value
                .lt.return_value
                .limit.return_value
                .execute.return_value
                .data
            ) = webhook_rows
        elif name == "message_templates":
            t.select.return_value.in_.return_value.execute.return_value.data = template_rows
        return t

    sb.table.side_effect = table_router
    return sb


# ---------------------------------------------------------------------------
# get_whatsapp_costs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_whatsapp_costs_empty():
    sb = _make_sb(webhook_rows=[], template_rows=[])
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_costs
        result = await get_whatsapp_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
    assert result["marketing_count"] == 0
    assert result["utility_count"] == 0
    assert result["total_whatsapp_cost"] == 0.0


@pytest.mark.asyncio
async def test_whatsapp_costs_marketing():
    webhook_rows = [
        {"payload": {"template": {"name": "campanha_maio"}}, "received_at": "2026-05-01T10:00:00"},
        {"payload": {"template": {"name": "campanha_maio"}}, "received_at": "2026-05-02T10:00:00"},
    ]
    template_rows = [{"name": "campanha_maio", "category": "MARKETING"}]
    sb = _make_sb(webhook_rows, template_rows)
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_costs
        result = await get_whatsapp_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
    assert result["marketing_count"] == 2
    assert result["marketing_cost"] == round(2 * 0.0617, 4)
    assert result["utility_count"] == 0
    assert result["utility_cost"] == 0.0


@pytest.mark.asyncio
async def test_whatsapp_costs_utility():
    webhook_rows = [
        {"payload": {"template": {"name": "followup_util"}}, "received_at": "2026-05-01T10:00:00"},
    ]
    template_rows = [{"name": "followup_util", "category": "UTILITY"}]
    sb = _make_sb(webhook_rows, template_rows)
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_costs
        result = await get_whatsapp_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
    assert result["utility_count"] == 1
    assert result["utility_cost"] == round(1 * 0.0067, 4)
    assert result["marketing_count"] == 0


@pytest.mark.asyncio
async def test_whatsapp_costs_unknown_template_fallback_marketing():
    """Template ausente em message_templates → fallback MARKETING."""
    webhook_rows = [
        {"payload": {"template": {"name": "deleted_template"}}, "received_at": "2026-05-01T10:00:00"},
    ]
    sb = _make_sb(webhook_rows=webhook_rows, template_rows=[])
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_costs
        result = await get_whatsapp_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
    assert result["marketing_count"] == 1
    assert result["utility_count"] == 0


# ---------------------------------------------------------------------------
# get_whatsapp_daily_costs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_whatsapp_daily_groups_by_date():
    webhook_rows = [
        {"payload": {"template": {"name": "camp"}}, "received_at": "2026-05-01T08:00:00"},
        {"payload": {"template": {"name": "camp"}}, "received_at": "2026-05-01T10:00:00"},
        {"payload": {"template": {"name": "camp"}}, "received_at": "2026-05-02T09:00:00"},
    ]
    template_rows = [{"name": "camp", "category": "MARKETING"}]
    sb = _make_sb(webhook_rows, template_rows)
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_daily_costs
        result = await get_whatsapp_daily_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 3))

    data = result["data"]
    assert len(data) == 2
    may1 = next(d for d in data if d["date"] == "2026-05-01")
    may2 = next(d for d in data if d["date"] == "2026-05-02")
    assert may1["marketing_cost"] == round(2 * 0.0617, 4)
    assert may2["marketing_cost"] == round(1 * 0.0617, 4)
    assert may1["utility_cost"] == 0.0
    assert may1["total"] == may1["marketing_cost"] + may1["utility_cost"]


@pytest.mark.asyncio
async def test_whatsapp_daily_fills_zero_gaps():
    """Dias sem mensagens aparecem com zeros."""
    webhook_rows = [
        {"payload": {"template": {"name": "camp"}}, "received_at": "2026-05-01T08:00:00"},
    ]
    template_rows = [{"name": "camp", "category": "MARKETING"}]
    sb = _make_sb(webhook_rows, template_rows)
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_daily_costs
        result = await get_whatsapp_daily_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 4))

    data = result["data"]
    assert len(data) == 3
    may3 = next(d for d in data if d["date"] == "2026-05-03")
    assert may3["marketing_cost"] == 0.0
    assert may3["utility_cost"] == 0.0
    assert may3["total"] == 0.0
```

- [ ] **Step 2: Rodar testes — esperar que falhem (funções ainda não existem)**

```bash
cd backend
pytest tests/test_whatsapp_stats.py -v
```

Expected: `ImportError` ou `AttributeError` — `get_whatsapp_costs` / `get_whatsapp_daily_costs` não definidos.

- [ ] **Step 3: Adicionar constantes e endpoints em `backend/app/stats/router.py`**

No final do arquivo (após o endpoint `get_top_leads`), adicione:

```python
WHATSAPP_MARKETING_PRICE = 0.0617
WHATSAPP_UTILITY_PRICE = 0.0067


@router.get("/whatsapp")
async def get_whatsapp_costs(
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Get WhatsApp template costs split by Marketing vs Utility."""
    sb = get_supabase()

    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() + timedelta(days=1)

    result = (
        sb.table("meta_webhook_logs")
        .select("payload, received_at")
        .eq("direction", "outbound")
        .eq("request_type", "send_template")
        .eq("success", True)
        .gte("received_at", start_date.isoformat())
        .lt("received_at", end_date.isoformat())
        .limit(10000)
        .execute()
    )

    rows = result.data

    template_names = {
        row["payload"]["template"]["name"]
        for row in rows
        if row.get("payload") and row["payload"].get("template") and row["payload"]["template"].get("name")
    }

    category_map: dict[str, str] = {}
    if template_names:
        templates_result = (
            sb.table("message_templates")
            .select("name, category")
            .in_("name", list(template_names))
            .execute()
        )
        category_map = {t["name"]: t["category"] for t in templates_result.data}

    marketing_count = 0
    utility_count = 0
    for row in rows:
        payload = row.get("payload") or {}
        template = payload.get("template") or {}
        name = template.get("name")
        category = category_map.get(name, "MARKETING")
        if category.upper() == "UTILITY":
            utility_count += 1
        else:
            marketing_count += 1

    marketing_cost = round(marketing_count * WHATSAPP_MARKETING_PRICE, 4)
    utility_cost = round(utility_count * WHATSAPP_UTILITY_PRICE, 4)

    return {
        "marketing_count": marketing_count,
        "marketing_cost": marketing_cost,
        "utility_count": utility_count,
        "utility_cost": utility_cost,
        "total_whatsapp_cost": round(marketing_cost + utility_cost, 4),
    }


@router.get("/whatsapp/daily")
async def get_whatsapp_daily_costs(
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Get daily WhatsApp template costs split by Marketing and Utility."""
    sb = get_supabase()

    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() + timedelta(days=1)

    result = (
        sb.table("meta_webhook_logs")
        .select("payload, received_at")
        .eq("direction", "outbound")
        .eq("request_type", "send_template")
        .eq("success", True)
        .gte("received_at", start_date.isoformat())
        .lt("received_at", end_date.isoformat())
        .limit(10000)
        .execute()
    )

    rows = result.data

    template_names = {
        row["payload"]["template"]["name"]
        for row in rows
        if row.get("payload") and row["payload"].get("template") and row["payload"]["template"].get("name")
    }

    category_map: dict[str, str] = {}
    if template_names:
        templates_result = (
            sb.table("message_templates")
            .select("name, category")
            .in_("name", list(template_names))
            .execute()
        )
        category_map = {t["name"]: t["category"] for t in templates_result.data}

    daily: dict[str, dict[str, float]] = {}
    for row in rows:
        day = row["received_at"][:10]
        payload = row.get("payload") or {}
        template = payload.get("template") or {}
        name = template.get("name")
        category = category_map.get(name, "MARKETING")
        if day not in daily:
            daily[day] = {"marketing_cost": 0.0, "utility_cost": 0.0}
        if category.upper() == "UTILITY":
            daily[day]["utility_cost"] += WHATSAPP_UTILITY_PRICE
        else:
            daily[day]["marketing_cost"] += WHATSAPP_MARKETING_PRICE

    data = []
    current = start_date
    while current < end_date:
        day_str = current.isoformat()
        d = daily.get(day_str, {"marketing_cost": 0.0, "utility_cost": 0.0})
        data.append({
            "date": day_str,
            "marketing_cost": round(d["marketing_cost"], 4),
            "utility_cost": round(d["utility_cost"], 4),
            "total": round(d["marketing_cost"] + d["utility_cost"], 4),
        })
        current += timedelta(days=1)

    return {"data": data}
```

- [ ] **Step 4: Rodar testes — devem passar**

```bash
pytest tests/test_whatsapp_stats.py -v
```

Expected:
```
PASSED tests/test_whatsapp_stats.py::test_whatsapp_costs_empty
PASSED tests/test_whatsapp_stats.py::test_whatsapp_costs_marketing
PASSED tests/test_whatsapp_stats.py::test_whatsapp_costs_utility
PASSED tests/test_whatsapp_stats.py::test_whatsapp_costs_unknown_template_fallback_marketing
PASSED tests/test_whatsapp_stats.py::test_whatsapp_daily_groups_by_date
PASSED tests/test_whatsapp_stats.py::test_whatsapp_daily_fills_zero_gaps
```

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/tests/test_whatsapp_stats.py backend/app/stats/router.py
git commit -m "feat(stats): add /whatsapp and /whatsapp/daily cost endpoints"
```

---

## Task 3: Reescrita completa da página /estatisticas

**Files:**
- Modify: `frontend/src/app/(authenticated)/estatisticas/page.tsx`

Depende de: Task 1 (shadcn components) e Task 2 (novos endpoints já documentados).

- [ ] **Step 1: Substituir o conteúdo inteiro de `page.tsx`**

Arquivo: `frontend/src/app/(authenticated)/estatisticas/page.tsx`

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

const API_BASE = "";
const MARKETING_PRICE = 0.0617;
const UTILITY_PRICE = 0.0067;

const PERIOD_OPTIONS = [
  { label: "Hoje", days: 1 },
  { label: "7 dias", days: 7 },
  { label: "30 dias", days: 30 },
];

function formatUSD(value: number): string {
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return `${d.getDate()}/${d.getMonth() + 1}`;
}

interface WhatsappSummary {
  marketing_count: number;
  marketing_cost: number;
  utility_count: number;
  utility_cost: number;
  total_whatsapp_cost: number;
}

interface AISummary {
  total_cost: number;
  total_calls: number;
  total_tokens: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
}

interface DailyAI {
  date: string;
  cost: number;
}

interface DailyWA {
  date: string;
  marketing_cost: number;
  utility_cost: number;
  total: number;
}

interface CombinedDaily {
  date: string;
  marketing: number;
  utility: number;
  ia: number;
}

export default function EstatisticasPage() {
  const [selectedPeriod, setSelectedPeriod] = useState(30);
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  const [whatsapp, setWhatsapp] = useState<WhatsappSummary | null>(null);
  const [ai, setAi] = useState<AISummary | null>(null);
  const [dailyData, setDailyData] = useState<CombinedDaily[]>([]);
  const [loading, setLoading] = useState(true);

  const getDateRange = useCallback(() => {
    if (customStart && customEnd) {
      return { start_date: customStart, end_date: customEnd };
    }
    const end = new Date();
    end.setDate(end.getDate() + 1);
    const start = new Date();
    start.setDate(start.getDate() - selectedPeriod);
    return {
      start_date: start.toISOString().slice(0, 10),
      end_date: end.toISOString().slice(0, 10),
    };
  }, [selectedPeriod, customStart, customEnd]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    const { start_date, end_date } = getDateRange();
    const params = `start_date=${start_date}&end_date=${end_date}`;

    try {
      const [aiRes, waRes, aiDailyRes, waDailyRes] = await Promise.all([
        fetch(`${API_BASE}/api/stats/costs?${params}`),
        fetch(`${API_BASE}/api/stats/whatsapp?${params}`),
        fetch(`${API_BASE}/api/stats/costs/daily?${params}`),
        fetch(`${API_BASE}/api/stats/whatsapp/daily?${params}`),
      ]);

      const [aiData, waData, aiDailyData, waDailyData] = await Promise.all([
        aiRes.json(),
        waRes.json(),
        aiDailyRes.json(),
        waDailyRes.json(),
      ]);

      setAi(aiData);
      setWhatsapp(waData);

      const aiByDate: Record<string, number> = {};
      for (const d of aiDailyData.data as DailyAI[]) {
        aiByDate[d.date] = d.cost;
      }

      const combined: CombinedDaily[] = (waDailyData.data as DailyWA[]).map(
        (d) => ({
          date: d.date,
          marketing: d.marketing_cost,
          utility: d.utility_cost,
          ia: aiByDate[d.date] ?? 0,
        })
      );

      setDailyData(combined);
    } catch (e) {
      console.error("Failed to fetch stats:", e);
    } finally {
      setLoading(false);
    }
  }, [getDateRange]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const totalCost =
    (whatsapp?.total_whatsapp_cost ?? 0) + (ai?.total_cost ?? 0);

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0">
          <Skeleton className="h-8 w-48 rounded-[4px]" />
          <Skeleton className="h-4 w-72 rounded-[4px] mt-2" />
        </div>
        <div className="p-8 flex-1 bg-[#faf9f6] space-y-6">
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-28 rounded-[8px]" />
            ))}
          </div>
          <Skeleton className="h-72 rounded-[8px]" />
          <Skeleton className="h-48 rounded-[8px]" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1
            style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }}
            className="text-[32px] font-normal text-[#111111]"
          >
            Custos Operacionais
          </h1>
          <p className="text-[14px] text-[#7b7b78] mt-0.5">WhatsApp + IA</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            {PERIOD_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                onClick={() => {
                  setSelectedPeriod(opt.days);
                  setCustomStart("");
                  setCustomEnd("");
                }}
                className={
                  selectedPeriod === opt.days && !customStart
                    ? "bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                    : "bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                }
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1.5">
            <input
              type="date"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
            />
            <span className="text-[14px] text-[#7b7b78]">a</span>
            <input
              type="date"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
            />
          </div>
        </div>
      </div>

      <div className="p-6 md:p-8 overflow-auto flex-1 bg-[#faf9f6] space-y-6">
        {/* Summary Cards */}
        <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
          <Card className="border-[#dedbd6] rounded-[8px]">
            <CardHeader className="pb-1 pt-4 px-5">
              <CardTitle className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal">
                Marketing WPP
              </CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-4">
              <p className="text-[24px] font-normal text-[#111111] leading-none">
                {formatUSD(whatsapp?.marketing_cost ?? 0)}
              </p>
              <p className="text-[12px] text-[#7b7b78] mt-1">
                {whatsapp?.marketing_count ?? 0} msgs · ${MARKETING_PRICE}/msg
              </p>
            </CardContent>
          </Card>

          <Card className="border-[#dedbd6] rounded-[8px]">
            <CardHeader className="pb-1 pt-4 px-5">
              <CardTitle className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal">
                Utilidade WPP
              </CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-4">
              <p className="text-[24px] font-normal text-[#111111] leading-none">
                {formatUSD(whatsapp?.utility_cost ?? 0)}
              </p>
              <p className="text-[12px] text-[#7b7b78] mt-1">
                {whatsapp?.utility_count ?? 0} msgs · ${UTILITY_PRICE}/msg
              </p>
            </CardContent>
          </Card>

          <Card className="border-[#dedbd6] rounded-[8px]">
            <CardHeader className="pb-1 pt-4 px-5">
              <CardTitle className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal">
                LLM / IA
              </CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-4">
              <p className="text-[24px] font-normal text-[#111111] leading-none">
                {formatUSD(ai?.total_cost ?? 0)}
              </p>
              <p className="text-[12px] text-[#7b7b78] mt-1">
                {ai?.total_calls ?? 0} chamadas ·{" "}
                {(ai?.total_tokens ?? 0).toLocaleString()} tokens
              </p>
            </CardContent>
          </Card>

          <Card className="border-transparent rounded-[8px] bg-[#111111]">
            <CardHeader className="pb-1 pt-4 px-5">
              <CardTitle className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal">
                Total Operacional
              </CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-4">
              <p className="text-[24px] font-normal text-white leading-none">
                {formatUSD(totalCost)}
              </p>
              <p className="text-[12px] text-[#7b7b78] mt-1">WPP + IA</p>
            </CardContent>
          </Card>
        </div>

        {/* Daily Cost Chart */}
        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
          <h2 className="text-[14px] font-normal text-[#111111] mb-4">
            Custo Diário (USD)
          </h2>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={dailyData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#dedbd6" />
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                tick={{ fontSize: 12, fill: "#7b7b78" }}
              />
              <YAxis
                tick={{ fontSize: 12, fill: "#7b7b78" }}
                tickFormatter={(v: number) => `$${v.toFixed(2)}`}
              />
              <Tooltip
                formatter={(value: number, name: string) => [
                  `$${Number(value).toFixed(4)}`,
                  name === "marketing"
                    ? "Marketing WPP"
                    : name === "utility"
                    ? "Utilidade WPP"
                    : "IA",
                ]}
                labelFormatter={(label: string) => formatDate(label)}
              />
              <Legend
                formatter={(value: string) =>
                  value === "marketing"
                    ? "Marketing WPP"
                    : value === "utility"
                    ? "Utilidade WPP"
                    : "IA"
                }
              />
              <Line
                type="monotone"
                dataKey="marketing"
                stroke="#111111"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="utility"
                stroke="#0bdf50"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="ia"
                stroke="#7b7b78"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Details Table */}
        <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="border-[#dedbd6] hover:bg-transparent">
                <TableHead className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal h-10">
                  Categoria
                </TableHead>
                <TableHead className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal text-right h-10">
                  Qtd.
                </TableHead>
                <TableHead className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal text-right h-10">
                  Tokens / Chamadas
                </TableHead>
                <TableHead className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal text-right h-10">
                  Custo
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow className="border-[#dedbd6] hover:bg-[#faf9f6]">
                <TableCell className="text-[14px] text-[#111111] py-3">
                  Marketing WhatsApp
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  {whatsapp?.marketing_count ?? 0} msgs
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  —
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] py-3">
                  {formatUSD(whatsapp?.marketing_cost ?? 0)}
                </TableCell>
              </TableRow>

              <TableRow className="border-[#dedbd6] hover:bg-[#faf9f6]">
                <TableCell className="text-[14px] text-[#111111] py-3">
                  Utilidade WhatsApp
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  {whatsapp?.utility_count ?? 0} msgs
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  —
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] py-3">
                  {formatUSD(whatsapp?.utility_cost ?? 0)}
                </TableCell>
              </TableRow>

              <TableRow className="border-[#dedbd6] hover:bg-[#faf9f6]">
                <TableCell className="text-[14px] text-[#111111] py-3">
                  LLM / IA
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  {ai?.total_calls ?? 0} chamadas
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  {(ai?.total_tokens ?? 0).toLocaleString()}
                  {ai && (
                    <span className="text-[11px] ml-1">
                      ({ai.total_prompt_tokens.toLocaleString()} in /{" "}
                      {ai.total_completion_tokens.toLocaleString()} out)
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] py-3">
                  {formatUSD(ai?.total_cost ?? 0)}
                </TableCell>
              </TableRow>

              <TableRow className="bg-[#faf9f6] hover:bg-[#faf9f6] border-0">
                <TableCell className="text-[14px] font-medium text-[#111111] py-3">
                  Total
                </TableCell>
                <TableCell />
                <TableCell />
                <TableCell className="text-right text-[14px] font-medium text-[#111111] py-3">
                  {formatUSD(totalCost)}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar TypeScript**

```bash
cd frontend
npx tsc --noEmit
```

Expected: sem erros de tipagem.

- [ ] **Step 3: Commit**

```bash
cd ..
git add frontend/src/app/'(authenticated)'/estatisticas/page.tsx
git commit -m "feat(estatisticas): dashboard de custos operacionais WhatsApp + IA"
```

---

## Self-Review Checklist

- [x] **Spec § Cards** → Task 3 Step 1 (4 cards: Marketing, Utilidade, LLM, Total)
- [x] **Spec § Gráfico diário combinado** → Task 3 Step 1 (LineChart com 3 linhas)
- [x] **Spec § Tabela de detalhes** → Task 3 Step 1 (Table shadcn com 3 linhas + total)
- [x] **Spec § Filtros por período** → Task 3 Step 1 (PERIOD_OPTIONS + custom date inputs)
- [x] **Spec § Loading skeletons** → Task 3 Step 1 (Skeleton para cards, chart, tabela)
- [x] **Spec § Responsividade** → Task 3 Step 1 (`grid-cols-2 sm:grid-cols-4`, `flex-wrap`)
- [x] **Spec § GET /api/stats/whatsapp** → Task 2 Step 3
- [x] **Spec § GET /api/stats/whatsapp/daily** → Task 2 Step 3
- [x] **Spec § Fallback MARKETING** → Task 2 Step 3 (`category_map.get(name, "MARKETING")`)
- [x] **Spec § shadcn card/table/skeleton** → Task 1
- [x] **Nomes consistentes:** `get_whatsapp_costs` / `get_whatsapp_daily_costs` usados identicamente nos testes e na implementação
- [x] **Sem placeholders/TBD**
