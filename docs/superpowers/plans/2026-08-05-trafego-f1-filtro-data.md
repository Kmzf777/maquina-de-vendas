# /trafego F1 — Filtro de data avançado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).
>
> **FRONTEND RULE:** Task 4 toca `frontend/src` → usar `frontend-design` + shadcn/ui (ver memory `feedback_frontend_skill`).

**Goal:** Permitir filtrar o Relatório Campanhas por **mês** e por **período custom (de/até)**, além dos presets 7/30/90d/Tudo.

**Architecture:** O backend passa a resolver uma **janela (lo, hi)** a partir de `period` OU de `date_from`/`date_to` explícitos (estes têm precedência), e aplica limite inferior E superior nos fetches. O front oferece presets + seletor de mês + intervalo custom, montando `period` ou `date_from`/`date_to` na URL.

**Tech Stack:** FastAPI, Supabase, pytest; Next.js App Router, TS, shadcn/ui.

**Pré-requisito:** este é o F1 do spec `docs/superpowers/specs/2026-08-05-trafego-roas-google-ads-e-filtro-data-design.md`. F2 (ROAS) vem depois.

---

## File Structure
- Modify `backend/app/campaigns/traffic_report.py` — `_resolve_window` + janela (lo,hi) nos fetches e em `traffic_report`/`campaign_leads`.
- Modify `backend/tests/test_traffic_report.py` — testes de janela.
- Modify `backend/app/campaigns/traffic_router.py` — endpoints aceitam `date_from`/`date_to`.
- Modify `frontend/src/app/api/traffic/report/route.ts` e `.../leads/route.ts` — repassar `date_from`/`date_to`.
- Modify `frontend/src/app/(authenticated)/trafego/page.tsx` — controle de data (presets + mês + custom).

---

## Task 1: janela (lo, hi) no backend

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py`
- Test: `backend/tests/test_traffic_report.py`

- [ ] **Step 1: Escrever os testes (falham)**

```python
# adicionar em backend/tests/test_traffic_report.py
import re
from app.campaigns.traffic_report import _resolve_window


def test_resolve_window_preset_30d_has_lower_no_upper():
    lo, hi = _resolve_window("30d", None, None)
    assert lo is not None and hi is None
    assert re.match(r"\d{4}-\d{2}-\d{2}T", lo)


def test_resolve_window_all_is_open():
    assert _resolve_window("all", None, None) == (None, None)


def test_resolve_window_explicit_range_takes_precedence():
    lo, hi = _resolve_window("30d", "2026-08-01", "2026-08-31")
    assert lo == "2026-08-01T00:00:00+00:00"
    assert hi == "2026-08-31T23:59:59.999999+00:00"


def test_resolve_window_ignores_malformed_dates():
    # datas inválidas → cai no preset
    lo, hi = _resolve_window("7d", "nao-e-data", "")
    assert lo is not None and hi is None


def test_resolve_window_only_from():
    lo, hi = _resolve_window("all", "2026-08-10", None)
    assert lo == "2026-08-10T00:00:00+00:00" and hi is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: FAIL (ImportError: cannot import name '_resolve_window').

- [ ] **Step 3: Implementar** — em `traffic_report.py`, substituir `_period_cutoff` por `_resolve_window` e ajustar os fetches.

Adicionar (perto de `_PERIOD_DAYS`):
```python
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
```

Garantir `import re` no topo do arquivo (adicionar se ausente). Remover a função `_period_cutoff`.

Trocar a assinatura dos fetches para `(lo, hi)` e aplicar `gte(lo)` + `lte(hi)`:
```python
def _fetch_leads(sb, mode: str, lo: str | None, hi: str | None) -> list[dict[str, Any]]:
    if mode == "sale":
        q = sb.table("sales").select("lead_id")
        if lo:
            q = q.gte("sold_at", lo)
        if hi:
            q = q.lte("sold_at", hi)
        sale_ids = sorted({r["lead_id"] for r in (q.execute().data or []) if r.get("lead_id")})
        leads: list[dict[str, Any]] = []
        for chunk in _chunks(sale_ids):
            data = sb.table("leads").select(_LEAD_COLS).in_("id", chunk).execute().data or []
            leads.extend(data)
        return leads
    q = sb.table("leads").select(_LEAD_COLS)
    if lo:
        q = q.gte("created_at", lo)
    if hi:
        q = q.lte("created_at", hi)
    return q.execute().data or []


def _sales_by_lead(sb, lead_ids: list[str], lo: str | None, hi: str | None, mode: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(lead_ids):
        q = sb.table("sales").select("lead_id, value, sold_at").in_("lead_id", chunk)
        if mode == "sale" and lo:
            q = q.gte("sold_at", lo)
        if mode == "sale" and hi:
            q = q.lte("sold_at", hi)
        for r in (q.execute().data or []):
            lid = r.get("lead_id")
            if not lid:
                continue
            agg = out.setdefault(lid, {"count": 0, "value": 0.0, "last_sold_at": None})
            agg["count"] += 1
            try:
                agg["value"] += float(r.get("value") or 0.0)
            except (TypeError, ValueError):
                pass
            sold_at = r.get("sold_at")
            if isinstance(sold_at, str) and sold_at:
                prev = agg["last_sold_at"]
                if prev is None or sold_at > prev:
                    agg["last_sold_at"] = sold_at
    return out
```

Atualizar `traffic_report` e `campaign_leads` para aceitar `date_from`/`date_to` e resolver a janela:
```python
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
        return build_campaign_report(leads, conversed, closers, sales, mode, period)
    except Exception as exc:
        logger.error("traffic_report(%s,%s) falhou: %s", period, mode, exc, exc_info=True)
        return _empty_report(mode, period)
```
E em `campaign_leads` (mesmo padrão): assinatura `(channel, campaign, period="30d", mode="lead", date_from=None, date_to=None)`; trocar `cutoff = _period_cutoff(period)` por `lo, hi = _resolve_window(period, date_from, date_to)`; `_fetch_leads(sb, mode, lo, hi)` e `_sales_by_lead(sb, lead_ids, lo, hi, mode)`.

- [ ] **Step 4: Rodar e ver passar** (e ajustar testes existentes que citavam `_period_cutoff`, se houver)

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: PASS. Se algum teste antigo referenciava `_period_cutoff`, atualizá-lo para `_resolve_window` (mesma semântica de lower-bound quando sem datas).

- [ ] **Step 5: Suíte completa**

Run: `cd backend; python -m pytest -q`
Expected: PASS (sem regressão).

- [ ] **Step 6: Commit**

```bash
git add backend/app/campaigns/traffic_report.py backend/tests/test_traffic_report.py
git commit -m "feat(trafego): janela de data (lo/hi) com date_from/date_to"
```

---

## Task 2: endpoints aceitam date_from/date_to

**Files:**
- Modify: `backend/app/campaigns/traffic_router.py`
- Test: `backend/tests/test_traffic_report.py`

- [ ] **Step 1: Teste (falha)**

```python
# adicionar em backend/tests/test_traffic_report.py
def test_router_report_forwards_dates(monkeypatch):
    import app.campaigns.traffic_router as tr_router
    captured = {}
    def fake_report(period, mode, date_from=None, date_to=None):
        captured.update(period=period, mode=mode, date_from=date_from, date_to=date_to)
        return {"ok": True}
    monkeypatch.setattr(tr_router, "traffic_report", fake_report)
    import asyncio
    asyncio.run(tr_router.traffic_report_endpoint(period="30d", mode="lead",
                                                  date_from="2026-08-01", date_to="2026-08-31"))
    assert captured["date_from"] == "2026-08-01" and captured["date_to"] == "2026-08-31"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py::test_router_report_forwards_dates -q`
Expected: FAIL (TypeError: unexpected keyword 'date_from').

- [ ] **Step 3: Implementar** — `traffic_router.py`:

```python
@router.get("/report")
async def traffic_report_endpoint(period: str = "30d", mode: str = "lead",
                                  date_from: str | None = None, date_to: str | None = None):
    """Relatório agregado por canal+campanha (admin-only na UI)."""
    mode = mode if mode in ("lead", "sale") else "lead"
    return traffic_report(period=period, mode=mode, date_from=date_from, date_to=date_to)


@router.get("/leads")
async def traffic_leads_endpoint(channel: str, campaign: str, period: str = "30d", mode: str = "lead",
                                 date_from: str | None = None, date_to: str | None = None):
    """Leads de uma campanha específica (drill-down)."""
    mode = mode if mode in ("lead", "sale") else "lead"
    return {"leads": campaign_leads(channel=channel, campaign=campaign, period=period, mode=mode,
                                    date_from=date_from, date_to=date_to)}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`  → PASS.
Run: `cd backend; python -c "import app.main"`  → sem erro.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/traffic_router.py backend/tests/test_traffic_report.py
git commit -m "feat(trafego): endpoints aceitam date_from/date_to"
```

---

## Task 3: proxy routes repassam as datas

**Files:**
- Modify: `frontend/src/app/api/traffic/report/route.ts`
- Modify: `frontend/src/app/api/traffic/leads/route.ts`

- [ ] **Step 1: report/route.ts** — ler e repassar `date_from`/`date_to`:

Após `const mode = searchParams.get("mode") || "lead";` adicionar:
```typescript
  const dateFrom = searchParams.get("date_from") || "";
  const dateTo = searchParams.get("date_to") || "";
  const extra = `${dateFrom ? `&date_from=${encodeURIComponent(dateFrom)}` : ""}${dateTo ? `&date_to=${encodeURIComponent(dateTo)}` : ""}`;
```
E na URL do fetch ao backend, acrescentar `${extra}` ao final da query string existente (após `&mode=...`).

- [ ] **Step 2: leads/route.ts** — incluir `date_from`/`date_to` no `URLSearchParams`:

Onde monta `const qs = new URLSearchParams({ channel, campaign, period, mode }).toString();`, trocar por:
```typescript
  const dateFrom = searchParams.get("date_from") || "";
  const dateTo = searchParams.get("date_to") || "";
  const params: Record<string, string> = { channel, campaign, period, mode };
  if (dateFrom) params.date_from = dateFrom;
  if (dateTo) params.date_to = dateTo;
  const qs = new URLSearchParams(params).toString();
```

- [ ] **Step 3: Validar**

Run: `cd frontend; npm run type-check` → limpo.
Run: `cd frontend; npx eslint "src/app/(authenticated)/trafego" "src/app/api/traffic"` → limpo.

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/app/api/traffic"
git commit -m "feat(trafego): proxy repassa date_from/date_to ao backend"
```

---

## Task 4: controle de data no front (presets + mês + custom)

**Files:**
- Modify: `frontend/src/app/(authenticated)/trafego/page.tsx`

> **FRONTEND (obrigatório):** frontend-design + shadcn. Reusar `Select`/tokens; usar `<input type="month">` e `<input type="date">` nativos estilizados (sem adicionar lib de calendário). Não mudar o layout de painel/sticky da tabela.

- [ ] **Step 1: Estado + query** — no `TrafegoPage`, substituir o estado `period` isolado por um estado que também carrega datas, e montar a query certa:

```tsx
  const [period, setPeriod] = useState("30d");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
```
No `useEffect` do fetch, montar a query: quando `dateFrom` OU `dateTo` estiverem setados, mandar as datas (têm precedência); senão, mandar `period`:
```tsx
    const q = (dateFrom || dateTo)
      ? `mode=${mode}${dateFrom ? `&date_from=${dateFrom}` : ""}${dateTo ? `&date_to=${dateTo}` : ""}`
      : `period=${period}&mode=${mode}`;
    fetch(`/api/traffic/report?${q}`)
```
Incluir `dateFrom, dateTo` nas deps do `useEffect`. Passar `dateFrom`/`dateTo` também ao `CampaignLeadsDrawer` (ver Step 3).

- [ ] **Step 2: UI do controle** — ao lado do `Switch`, um controle com 3 modos. Referência funcional (o agente frontend-design refina o visual, mantendo a paleta):

```tsx
  const [dateMode, setDateMode] = useState<"preset" | "mes" | "custom">("preset");
  // handler do seletor de mês (YYYY-MM) → converte p/ from/to do 1º ao último dia
  const onMonth = (ym: string) => {
    if (!ym) { setDateFrom(""); setDateTo(""); return; }
    const [y, m] = ym.split("-").map(Number);
    const last = new Date(y, m, 0).getDate();
    setDateFrom(`${ym}-01`);
    setDateTo(`${ym}-${String(last).padStart(2, "0")}`);
  };
```
Render (dentro do bloco `flex items-center gap-4` do header, no lugar do `Select` atual):
```tsx
          <Select value={dateMode} onValueChange={(v) => {
            setDateMode(v as "preset" | "mes" | "custom");
            setDateFrom(""); setDateTo("");
          }}>
            <SelectTrigger className="w-[140px] text-[14px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="preset">Período</SelectItem>
              <SelectItem value="mes">Por mês</SelectItem>
              <SelectItem value="custom">Personalizado</SelectItem>
            </SelectContent>
          </Select>
          {dateMode === "preset" && (
            <Select value={period} onValueChange={setPeriod}>
              <SelectTrigger className="w-[150px] text-[14px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="7d">Últimos 7 dias</SelectItem>
                <SelectItem value="30d">Últimos 30 dias</SelectItem>
                <SelectItem value="90d">Últimos 90 dias</SelectItem>
                <SelectItem value="all">Tudo</SelectItem>
              </SelectContent>
            </Select>
          )}
          {dateMode === "mes" && (
            <input type="month" onChange={(e) => onMonth(e.target.value)}
              className="border border-[#dedbd6] rounded-[6px] px-3 py-1.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none" />
          )}
          {dateMode === "custom" && (
            <div className="flex items-center gap-2">
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                className="border border-[#dedbd6] rounded-[6px] px-2 py-1.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none" />
              <span className="text-[#7b7b78] text-[13px]">até</span>
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                className="border border-[#dedbd6] rounded-[6px] px-2 py-1.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none" />
            </div>
          )}
```

- [ ] **Step 3: Passar datas ao drawer** — o `CampaignLeadsDrawer` deve buscar leads na mesma janela. Adicionar props `dateFrom`/`dateTo` ao componente e incluí-las na query de `/api/traffic/leads` (mesmo padrão do Step 1). No `page.tsx`:
```tsx
      <CampaignLeadsDrawer
        channel={selected?.channel ?? null}
        campaign={selected?.campaign ?? null}
        period={period}
        mode={mode}
        dateFrom={dateFrom}
        dateTo={dateTo}
        onClose={() => setSelected(null)}
      />
```
E em `campaign-leads-drawer.tsx`: adicionar `dateFrom?: string; dateTo?: string` às props; na montagem da query, se `dateFrom || dateTo`, enviar as datas em vez de (ou além de) `period` — precedência das datas, igual ao report. Incluir `dateFrom, dateTo` nas deps do `useEffect`.

- [ ] **Step 4: Validar**

Run: `cd frontend; npm run type-check` → limpo.
Run: `cd frontend; npx eslint "src/app/(authenticated)/trafego" "src/components/trafego"` → limpo.
Run: `cd frontend; npm run test` → 263 passed (proxy-coverage verde).

- [ ] **Step 5: Commit**

```bash
git add "frontend/src/app/(authenticated)/trafego/page.tsx" "frontend/src/components/trafego/campaign-leads-drawer.tsx"
git commit -m "feat(trafego): filtro de data por mes e periodo custom"
```

---

## Self-Review (autor)
- **Cobertura do spec F1:** janela (lo,hi) + precedência de date_from/to → T1; endpoints → T2; proxy → T3; UI presets/mês/custom + drawer na mesma janela → T4. ✓
- **Placeholders:** nenhum.
- **Consistência:** `_resolve_window(period, date_from, date_to)` e as assinaturas `_fetch_leads(sb, mode, lo, hi)` / `_sales_by_lead(sb, lead_ids, lo, hi, mode)` batem entre T1 e os chamadores; endpoints e proxies usam os mesmos nomes `date_from`/`date_to`.

## Validação final
- `cd backend; python -m pytest -q`; frontend `npm run type-check` + `npm run test`.
