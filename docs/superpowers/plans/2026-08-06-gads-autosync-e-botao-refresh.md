# Google Ads auto-sync (worker) + botão de refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps usam checkbox (`- [ ]`).
>
> **FRONTEND RULE:** Task 3 toca `frontend/src` → usar `frontend-design` + shadcn/ui.

**Goal:** O backend roda o sync do Google Ads sozinho (tick diário no worker, sem cron) + um botão "Atualizar" no /trafego dispara o sync sob demanda e recarrega.

**Architecture:** Reusa `sync_google_ads_spend` (já existe, env-gated/fail-soft/idempotente). Peça 1: registrar um tick `run_periodic` de 24h em `TASK_SPECS`. Peça 2: endpoint `POST /api/traffic/sync-google-ads` + proxy Next admin-gated + botão no header.

**Tech Stack:** FastAPI, pytest; Next.js, TS, shadcn.

**Spec:** `docs/superpowers/specs/2026-08-06-gads-autosync-e-botao-refresh-design.md`.

---

## Task 1: auto-sync no worker + endpoint manual

**Files:**
- Modify: `backend/app/worker/main.py`
- Modify: `backend/app/campaigns/traffic_router.py`
- Test: `backend/tests/test_ad_spend_sync.py`

- [ ] **Step 1: Testes (falham)**

```python
# adicionar em backend/tests/test_ad_spend_sync.py
def test_worker_registers_ad_spend_sync_tick():
    from app.worker.main import TASK_SPECS
    names = {spec[0] for spec in TASK_SPECS}
    assert "ad-spend-sync" in names
    spec = next(s for s in TASK_SPECS if s[0] == "ad-spend-sync")
    # (name, kind, fn, interval)
    assert spec[1] == "periodic"
    assert callable(spec[2])
    assert spec[3] == 86400


def test_sync_endpoint_calls_sync(monkeypatch):
    import app.campaigns.traffic_router as tr_router
    called = {}
    async def fake_sync(days=30):
        called["days"] = days
        return 5
    monkeypatch.setattr(tr_router, "sync_google_ads_spend", fake_sync)
    import asyncio
    out = asyncio.run(tr_router.sync_google_ads_endpoint())
    assert out == {"synced": 5}
    assert called["days"] == 30
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_ad_spend_sync.py -q`
Expected: FAIL (ImportError TASK_SPECS name / AttributeError sync_google_ads_endpoint).

- [ ] **Step 3: Implementar — worker** (`app/worker/main.py`): adicionar o tick e a entrada.

Após `_reconcile_tick` (antes de `TASK_SPECS`):
```python
async def _ad_spend_sync_tick() -> None:
    from app.campaigns.ad_spend_sync import sync_google_ads_spend
    await sync_google_ads_spend(days=30)
```
E acrescentar ao final da lista `TASK_SPECS`:
```python
    ("ad-spend-sync", "periodic", _ad_spend_sync_tick, 86400),
```

- [ ] **Step 4: Implementar — endpoint** (`app/campaigns/traffic_router.py`): importar o sync e adicionar o endpoint.

No topo, somar ao import de campaigns:
```python
from app.campaigns.ad_spend_sync import sync_google_ads_spend
```
E adicionar o endpoint:
```python
@router.post("/sync-google-ads")
async def sync_google_ads_endpoint():
    """Dispara o sync do investimento do Google Ads sob demanda (admin-only na UI)."""
    synced = await sync_google_ads_spend(days=30)
    return {"synced": synced}
```

- [ ] **Step 5: Rodar e ver passar + suíte + import**

Run: `cd backend; python -m pytest tests/test_ad_spend_sync.py -q` → PASS.
Run: `cd backend; python -m pytest -q` → sem regressão.
Run: `cd backend; python -c "import app.main; import app.campaign.worker"` → sem erro.

- [ ] **Step 6: Commit**

```bash
git add backend/app/worker/main.py backend/app/campaigns/traffic_router.py backend/tests/test_ad_spend_sync.py
git commit -m "feat(gads): auto-sync diario no worker + endpoint POST /api/traffic/sync-google-ads"
```

---

## Task 2: proxy Next admin-gated `/api/traffic/sync`

**Files:**
- Create: `frontend/src/app/api/traffic/sync/route.ts`

- [ ] **Step 1: Criar o proxy (POST)**

```typescript
// frontend/src/app/api/traffic/sync/route.ts
import { getCurrentUser } from "@/lib/supabase/pipeline-access";

export async function POST() {
  try {
    const { role } = await getCurrentUser();
    if (role !== "admin") return Response.json({ error: "forbidden" }, { status: 403 });
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  try {
    const resp = await fetch(`${backendUrl}/api/traffic/sync-google-ads`, { method: "POST", cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "sync_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "sync_unreachable" }, { status: 502 });
  }
}
```

- [ ] **Step 2: Validar**

Run: `cd frontend; npm run type-check` → limpo.
Run: `cd frontend; npx eslint "src/app/api/traffic"` → limpo.

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/api/traffic/sync"
git commit -m "feat(gads): proxy admin-gated POST /api/traffic/sync"
```

---

## Task 3: botão "Atualizar" no /trafego

**Files:**
- Modify: `frontend/src/app/(authenticated)/trafego/page.tsx`

> **FRONTEND (obrigatório):** frontend-design + shadcn. Reusar tokens/paleta; botão discreto no
> header, ao lado dos filtros. Não mudar o layout de painel/sticky da tabela.

- [ ] **Step 1: Estado + handler** — no `TrafegoPage`, adicionar:

```tsx
  const [syncing, setSyncing] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [toast, setToast] = useState<string | null>(null);

  const handleRefresh = async () => {
    setSyncing(true);
    try {
      const r = await fetch("/api/traffic/sync", { method: "POST" });
      const d = await r.json().catch(() => ({}));
      if (typeof d.synced === "number") {
        setToast(d.synced > 0 ? `${d.synced} linha(s) de investimento sincronizadas` : "Sem dados novos do Google Ads");
      } else {
        setToast("Não foi possível sincronizar agora");
      }
    } catch {
      setToast("Não foi possível sincronizar agora");
    } finally {
      setSyncing(false);
      setRefreshTick((t) => t + 1); // força o refetch do report
      setTimeout(() => setToast(null), 6000);
    }
  };
```
Incluir `refreshTick` nas deps do `useEffect` que faz o fetch do report (para o botão recarregar os dados após o sync).

- [ ] **Step 2: Botão no header** — dentro do bloco `flex items-center gap-4` do header (junto do
  `Switch`/filtros de data), adicionar:

```tsx
          <button
            onClick={handleRefresh}
            disabled={syncing}
            className="inline-flex items-center gap-1.5 bg-transparent text-[#111111] border border-[#111111] px-3 py-1.5 rounded-[4px] text-[13px] md:text-[14px] transition-transform hover:scale-105 active:scale-[0.9] disabled:opacity-50"
          >
            <svg className={`w-4 h-4 ${syncing ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992V4.356M2.985 19.644v-4.992h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.99v4.99" /></svg>
            {syncing ? "Atualizando…" : "Atualizar"}
          </button>
```

- [ ] **Step 3: Toast** — antes do fechamento do container raiz, renderizar o toast quando houver:

```tsx
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#111111] text-white text-[13px] px-4 py-3 rounded-[6px] shadow-lg">{toast}</div>
      )}
```

- [ ] **Step 4: Validar**

Run: `cd frontend; npm run type-check` → limpo.
Run: `cd frontend; npx eslint "src/app/(authenticated)/trafego" "src/app/api/traffic"` → limpo.
Run: `cd frontend; npm run test` → 263 passed (proxy-coverage verde; `/api/traffic` já no matcher).

- [ ] **Step 5: Commit**

```bash
git add "frontend/src/app/(authenticated)/trafego/page.tsx"
git commit -m "feat(gads): botao Atualizar (sync sob demanda + reload) no /trafego"
```

---

## Self-Review (autor)
- **Cobertura do spec:** tick diário no worker → T1; endpoint manual → T1; proxy admin → T2;
  botão Atualizar (sync + reload) + toast → T3. ✓
- **Placeholders:** nenhum.
- **Consistência:** `sync_google_ads_spend(days=30)` usado no tick (T1) e no endpoint (T1),
  `async`, retorna int; o proxy (T2) chama `/api/traffic/sync-google-ads`; o botão (T3) chama
  `/api/traffic/sync`. `TASK_SPECS` tupla `(name, kind, fn, interval)` = mesma forma das existentes.

## Validação final
- `cd backend; python -m pytest -q`; frontend `npm run type-check` + `npm run test`.
## Pós-deploy
- O worker roda o sync no boot → `ad_spend` popula → ROAS aparece. O botão força na hora.
