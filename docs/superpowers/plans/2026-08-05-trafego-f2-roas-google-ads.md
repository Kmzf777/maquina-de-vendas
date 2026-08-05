# /trafego F2 — ROAS via Google Ads — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).
>
> **FRONTEND RULE:** Task 5 toca `frontend/src` → usar `frontend-design` + shadcn/ui.

**Goal:** Trazer o investimento (spend) por campanha do Google Ads para uma tabela `ad_spend` (sync diário) e exibir **Investimento** e **ROAS** por campanha no Relatório Campanhas.

**Architecture:** Client REST via **httpx** (padrão do projeto; sem lib gRPC). Env-gated + fail-soft: sem credenciais → tudo vira no-op e o relatório mostra "—". Sync diário faz upsert em `ad_spend`; o report lê de lá e junta por `campaign_name` == `utm_campaign` (normalizado). Só Google agora (`platform='google'`); Meta depois.

**Tech Stack:** FastAPI, httpx, Supabase, pytest; Next.js, TS, shadcn/ui.

**Credenciais (env/secrets):** já usados no projeto — `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CUSTOMER_ID`. Novos (OAuth) — `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`, `GOOGLE_ADS_LOGIN_CUSTOMER_ID`. Ler via `os.getenv` (NÃO editar `app/config.py`, que tem a classe duplicada).

**Spec:** `docs/superpowers/specs/2026-08-05-trafego-roas-google-ads-e-filtro-data-design.md` (F2).

---

## File Structure
- Create `backend/app/campaigns/google_ads.py` — client REST (token + fetch spend) + parsing puro.
- Create `backend/tests/test_google_ads.py`.
- Create `supabase/migrations/20260805_ad_spend.sql` — tabela ad_spend.
- Create `backend/app/campaigns/ad_spend_sync.py` — `sync_google_ads_spend`.
- Create `backend/scripts/sync_google_ads_spend.py` — runner do cron.
- Create `backend/tests/test_ad_spend_sync.py`.
- Modify `backend/app/campaigns/traffic_report.py` — `_spend_by_campaign` + investimento/roas em `build_campaign_report` + `traffic_report`.
- Modify `backend/tests/test_traffic_report.py` — testes de ROAS.
- Modify `frontend/src/components/trafego/campaign-report-table.tsx` — colunas Investimento + ROAS.
- Create `docs/setup/google-ads-conexao.md` — tutorial (escrito pelo controlador, fora deste fluxo de subagent).

**Contrato de dados (novas chaves em cada `row`/`total`/`channel_subtotals[canal]`):**
`investimento` (float; 0.0 exceto canal "Google Ads"), `roas` (float|None; receita÷investimento; None se investimento 0 ou canal ≠ Google).

---

## Task 1: client Google Ads (REST via httpx)

**Files:**
- Create: `backend/app/campaigns/google_ads.py`
- Test: `backend/tests/test_google_ads.py`

- [ ] **Step 1: Escrever testes (falham)**

```python
# backend/tests/test_google_ads.py
import app.campaigns.google_ads as g


def test_parse_spend_rows_maps_cost_micros():
    results = [
        {"campaign": {"id": "111", "name": "Atacado"}, "segments": {"date": "2026-08-01"},
         "metrics": {"costMicros": "1500000"}},
        {"campaign": {"id": "222", "name": "Terceirizacao"}, "segments": {"date": "2026-08-02"},
         "metrics": {"costMicros": "0"}},
    ]
    out = g.parse_spend_rows(results)
    assert out[0] == {"campaign_id": "111", "campaign_name": "Atacado", "date": "2026-08-01", "cost": 1.5}
    assert out[1]["cost"] == 0.0


def test_parse_spend_rows_skips_malformed():
    out = g.parse_spend_rows([{"segments": {"date": "2026-08-01"}}])  # sem campaign/metrics
    assert out == []


def test_google_ads_enabled_false_when_missing(monkeypatch):
    for k in g._REQUIRED_ENV:
        monkeypatch.delenv(k, raising=False)
    assert g.google_ads_enabled() is False


def test_google_ads_enabled_true_when_all_present(monkeypatch):
    for k in g._REQUIRED_ENV:
        monkeypatch.setenv(k, "x")
    assert g.google_ads_enabled() is True


def test_fetch_campaign_spend_noop_when_disabled(monkeypatch):
    for k in g._REQUIRED_ENV:
        monkeypatch.delenv(k, raising=False)
    import asyncio
    assert asyncio.run(g.fetch_campaign_spend("2026-08-01", "2026-08-31")) == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_google_ads.py -q`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementar**

```python
# backend/app/campaigns/google_ads.py
"""Client REST (httpx) do Google Ads para buscar investimento (spend) por campanha.

Env-gated + fail-soft: sem credenciais ou em erro de API → []. Não usa a lib gRPC google-ads
(consistente com o padrão httpx do MetaCloudClient). Parsing puro (parse_spend_rows) isolado
da rede para teste."""
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_REQUIRED_ENV = (
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    "GOOGLE_ADS_CUSTOMER_ID",
)
_API_VERSION = "v17"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


def google_ads_enabled() -> bool:
    return all(os.getenv(k) for k in _REQUIRED_ENV)


def parse_spend_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extrai [{campaign_id, campaign_name, date, cost}] de uma página de resultados GAQL.

    cost = costMicros / 1_000_000. Linhas sem campaign/metrics são ignoradas."""
    out: list[dict[str, Any]] = []
    for r in results or []:
        campaign = r.get("campaign") or {}
        metrics = r.get("metrics") or {}
        segments = r.get("segments") or {}
        name = campaign.get("name")
        if not name or "costMicros" not in metrics:
            continue
        try:
            cost = int(metrics.get("costMicros") or 0) / 1_000_000
        except (TypeError, ValueError):
            cost = 0.0
        out.append({
            "campaign_id": str(campaign.get("id") or ""),
            "campaign_name": name,
            "date": segments.get("date"),
            "cost": cost,
        })
    return out


async def _get_access_token() -> str | None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(_TOKEN_URL, data={
                "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
                "refresh_token": os.getenv("GOOGLE_ADS_REFRESH_TOKEN"),
                "grant_type": "refresh_token",
            })
            resp.raise_for_status()
            return resp.json().get("access_token")
    except Exception as exc:
        logger.error("google_ads: falha ao obter access_token: %s", exc)
        return None


async def fetch_campaign_spend(date_from: str, date_to: str) -> list[dict[str, Any]]:
    """Busca custo por campanha/dia entre date_from e date_to (YYYY-MM-DD).

    Env-gated (creds ausentes → []) e fail-soft (erro → []). Retorna
    [{campaign_id, campaign_name, date, cost}]."""
    if not google_ads_enabled():
        return []
    token = await _get_access_token()
    if not token:
        return []
    customer_id = (os.getenv("GOOGLE_ADS_CUSTOMER_ID") or "").replace("-", "")
    login_cid = (os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or "").replace("-", "")
    url = f"https://googleads.googleapis.com/{_API_VERSION}/customers/{customer_id}/googleAds:search"
    headers = {
        "Authorization": f"Bearer {token}",
        "developer-token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN") or "",
        "login-customer-id": login_cid,
        "Content-Type": "application/json",
    }
    gaql = (
        "SELECT campaign.id, campaign.name, segments.date, metrics.cost_micros "
        f"FROM campaign WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'"
    )
    rows: list[dict[str, Any]] = []
    page_token: str | None = None
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for _ in range(50):  # guarda anti-loop de paginação
                body: dict[str, Any] = {"query": gaql}
                if page_token:
                    body["pageToken"] = page_token
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                rows.extend(parse_spend_rows(data.get("results") or []))
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return rows
    except Exception as exc:
        logger.error("google_ads: fetch_campaign_spend falhou: %s", exc)
        return []
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend; python -m pytest tests/test_google_ads.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/google_ads.py backend/tests/test_google_ads.py
git commit -m "feat(gads): client REST httpx p/ spend por campanha (env-gated, fail-soft)"
```

---

## Task 2: migration `ad_spend`

**Files:**
- Create: `supabase/migrations/20260805_ad_spend.sql`

- [ ] **Step 1: Criar a migration**

```sql
-- supabase/migrations/20260805_ad_spend.sql
-- Investimento (spend) por campanha/dia, por plataforma. Alimentado pelo sync diário.
CREATE TABLE IF NOT EXISTS ad_spend (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  platform text NOT NULL DEFAULT 'google',
  campaign_id text,
  campaign_name text NOT NULL,
  date date NOT NULL,
  cost numeric NOT NULL DEFAULT 0,
  currency text NOT NULL DEFAULT 'BRL',
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (platform, campaign_id, date)
);

CREATE INDEX IF NOT EXISTS ad_spend_platform_name_date_idx
  ON ad_spend (platform, campaign_name, date);
```

- [ ] **Step 2: Commit** (aplicação no Supabase é manual — não roda no CI)

```bash
git add supabase/migrations/20260805_ad_spend.sql
git commit -m "feat(gads): migration da tabela ad_spend"
```

---

## Task 3: sync diário do spend

**Files:**
- Create: `backend/app/campaigns/ad_spend_sync.py`
- Create: `backend/scripts/sync_google_ads_spend.py`
- Test: `backend/tests/test_ad_spend_sync.py`

- [ ] **Step 1: Escrever testes (falham)**

```python
# backend/tests/test_ad_spend_sync.py
import app.campaigns.ad_spend_sync as s


def test_sync_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(s, "google_ads_enabled", lambda: False)
    import asyncio
    assert asyncio.run(s.sync_google_ads_spend(days=7)) == 0


def test_sync_upserts_mapped_rows(monkeypatch):
    captured = {}

    class _Q:
        def upsert(self, rows, on_conflict=None):
            captured["rows"] = rows
            captured["on_conflict"] = on_conflict
            return self
        def execute(self):
            class R: pass
            r = R(); r.data = captured["rows"]; return r

    class _SB:
        def table(self, name): return _Q()

    monkeypatch.setattr(s, "google_ads_enabled", lambda: True)
    monkeypatch.setattr(s, "get_supabase", lambda: _SB())

    async def fake_fetch(date_from, date_to):
        return [{"campaign_id": "1", "campaign_name": "Atacado", "date": "2026-08-01", "cost": 2.5}]
    monkeypatch.setattr(s, "fetch_campaign_spend", fake_fetch)

    import asyncio
    n = asyncio.run(s.sync_google_ads_spend(days=7))
    assert n == 1
    row = captured["rows"][0]
    assert row["platform"] == "google" and row["campaign_name"] == "Atacado" and row["cost"] == 2.5
    assert captured["on_conflict"] == "platform,campaign_id,date"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_ad_spend_sync.py -q`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementar**

```python
# backend/app/campaigns/ad_spend_sync.py
"""Sync diário do investimento do Google Ads para a tabela ad_spend (upsert idempotente).

Env-gated (no-op sem credenciais) e fail-soft. Rodado por cron diário via
scripts/sync_google_ads_spend.py."""
import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.campaigns.google_ads import fetch_campaign_spend, google_ads_enabled

logger = logging.getLogger(__name__)


async def sync_google_ads_spend(days: int = 30) -> int:
    """Busca o spend dos últimos `days` dias e faz upsert em ad_spend. Retorna nº de linhas."""
    if not google_ads_enabled():
        logger.info("ad_spend_sync: Google Ads sem credenciais — no-op")
        return 0
    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=days)).isoformat()
    date_to = today.isoformat()
    try:
        spend = await fetch_campaign_spend(date_from, date_to)
        if not spend:
            logger.info("ad_spend_sync: nenhum spend retornado (%s..%s)", date_from, date_to)
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = [{
            "platform": "google",
            "campaign_id": r.get("campaign_id") or None,
            "campaign_name": r.get("campaign_name"),
            "date": r.get("date"),
            "cost": r.get("cost", 0.0),
            "currency": "BRL",
            "updated_at": now_iso,
        } for r in spend if r.get("campaign_name") and r.get("date")]
        get_supabase().table("ad_spend").upsert(
            rows, on_conflict="platform,campaign_id,date"
        ).execute()
        logger.info("ad_spend_sync: upsert de %d linhas (%s..%s)", len(rows), date_from, date_to)
        return len(rows)
    except Exception as exc:
        logger.error("ad_spend_sync: falhou: %s", exc, exc_info=True)
        return 0
```

```python
# backend/scripts/sync_google_ads_spend.py
"""Runner do sync diário do Google Ads (cron). Uso: python -m scripts.sync_google_ads_spend"""
import asyncio
import logging

from app.campaigns.ad_spend_sync import sync_google_ads_spend

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    n = asyncio.run(sync_google_ads_spend(days=30))
    print(f"ad_spend sync: {n} linhas")
```

- [ ] **Step 4: Rodar e ver passar + smoke**

Run: `cd backend; python -m pytest tests/test_ad_spend_sync.py -q`  → PASS.
Run: `cd backend; python -c "import ast; ast.parse(open('scripts/sync_google_ads_spend.py').read()); print('ok')"`  → ok.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/ad_spend_sync.py backend/scripts/sync_google_ads_spend.py backend/tests/test_ad_spend_sync.py
git commit -m "feat(gads): sync diario do spend -> ad_spend (idempotente)"
```

---

## Task 4: ROAS no relatório

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py`
- Test: `backend/tests/test_traffic_report.py`

- [ ] **Step 1: Escrever testes (falham)**

```python
# adicionar em backend/tests/test_traffic_report.py
from app.campaigns.traffic_report import build_campaign_report as _bcr


def test_build_roas_only_for_google_rows():
    leads = [_lead("a", gclid="1", utm_campaign="Atacado"),
             _lead("b", fbclid="2", utm_campaign="MetaCamp")]
    sales = {"a": {"count": 1, "value": 300.0}, "b": {"count": 1, "value": 100.0}}
    spend = {"atacado": 100.0}  # normalizado (trim+lower)
    out = _bcr(leads, set(), set(), sales, mode="lead", period="30d", spend_by_campaign=spend)
    rows = {(r["channel"], r["campaign"]): r for r in out["rows"]}
    g = rows[("Google Ads", "Atacado")]
    assert g["investimento"] == 100.0 and g["roas"] == 3.0
    m = rows[("Meta Ads", "MetaCamp")]
    assert m["investimento"] == 0.0 and m["roas"] is None
    # Total ROAS considera só receita das linhas Google / investimento total
    assert out["total"]["investimento"] == 100.0
    assert out["total"]["roas"] == 3.0


def test_build_roas_none_when_no_spend():
    leads = [_lead("a", gclid="1", utm_campaign="SemSpend")]
    sales = {"a": {"count": 1, "value": 50.0}}
    out = _bcr(leads, set(), set(), sales, mode="lead", period="30d", spend_by_campaign={})
    row = out["rows"][0]
    assert row["investimento"] == 0.0 and row["roas"] is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: FAIL (TypeError: unexpected 'spend_by_campaign' / KeyError 'investimento').

- [ ] **Step 3: Implementar** — assinatura e agregação de `build_campaign_report`.

Mudar a assinatura para aceitar `spend_by_campaign` (default None):
```python
def build_campaign_report(leads, conversed_ids, closer_ids, sales_by_lead, mode, period,
                          spend_by_campaign: dict[str, float] | None = None):
```
No init de `row`, adicionar `"investimento": 0.0`. **Após** o loop que preenche os grupos (antes de calcular ticket/conversão), atribuir investimento às linhas Google:
```python
    spend_by_campaign = spend_by_campaign or {}
    for row in groups.values():
        if row["channel"] == "Google Ads":
            row["investimento"] = float(spend_by_campaign.get(row["campaign"].strip().lower(), 0.0))
```
No loop que calcula `ticket_medio`/`conversao` e soma o `total`, adicionar o `roas` por linha e acumular o total (incluindo receita só das linhas Google):
```python
    rows: list[dict[str, Any]] = []
    total = {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
             "receita": 0.0, "investimento": 0.0}
    google_receita = 0.0
    for row in groups.values():
        pedidos = row["pedidos"]
        row["ticket_medio"] = round(row["receita"] / pedidos, 2) if pedidos else 0.0
        row["conversao"] = round(row["clientes"] / row["leads"], 4) if row["leads"] else 0.0
        inv = row["investimento"]
        row["roas"] = round(row["receita"] / inv, 2) if inv else None
        if row["channel"] == "Google Ads":
            google_receita += row["receita"]
        for k in total:
            total[k] += row[k]
        rows.append(row)
```
Nas `channel_subtotals`, incluir `investimento` na soma e computar `roas` do subtotal:
```python
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
```
No final, computar o ROAS total (receita Google ÷ investimento total) e arredondar:
```python
    rows.sort(key=lambda r: (r["channel"], -r["receita"], -r["leads"]))
    total["receita"] = round(total["receita"], 2)
    total["investimento"] = round(total["investimento"], 2)
    total["roas"] = round(google_receita / total["investimento"], 2) if total["investimento"] else None
    return {"mode": mode, "period": period, "rows": rows, "total": total,
            "channel_subtotals": channel_subtotals}
```
Atualizar `_empty_report` para incluir `"investimento": 0.0` e `"roas": None` no `total`:
```python
def _empty_report(mode: str, period: str) -> dict[str, Any]:
    return {"mode": mode, "period": period, "rows": [], "channel_subtotals": {},
            "total": {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
                      "receita": 0.0, "investimento": 0.0, "roas": None}}
```

Adicionar `_spend_by_campaign` e usá-lo em `traffic_report`:
```python
def _spend_by_campaign(sb, lo: str | None, hi: str | None, platform: str = "google") -> dict[str, float]:
    """Soma cost de ad_spend por campaign_name normalizado (trim+lower), na janela. Fail-soft → {}."""
    try:
        q = sb.table("ad_spend").select("campaign_name, cost, date").eq("platform", platform)
        if lo:
            q = q.gte("date", lo[:10])
        if hi:
            q = q.lte("date", hi[:10])
        out: dict[str, float] = {}
        for r in (q.execute().data or []):
            name = (r.get("campaign_name") or "").strip().lower()
            if not name:
                continue
            try:
                out[name] = out.get(name, 0.0) + float(r.get("cost") or 0.0)
            except (TypeError, ValueError):
                pass
        return out
    except Exception as exc:
        logger.error("_spend_by_campaign falhou: %s", exc)
        return {}
```
Em `traffic_report`, após obter `sales`, buscar o spend e passá-lo:
```python
        sales = _sales_by_lead(sb, lead_ids, lo, hi, mode)
        spend = _spend_by_campaign(sb, lo, hi)
        return build_campaign_report(leads, conversed, closers, sales, mode, period,
                                     spend_by_campaign=spend)
```

- [ ] **Step 4: Rodar e ver passar + suíte**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`  → PASS.
Run: `cd backend; python -m pytest -q`  → sem regressão.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/traffic_report.py backend/tests/test_traffic_report.py
git commit -m "feat(trafego): Investimento + ROAS por campanha (Google Ads) no relatorio"
```

---

## Task 5: colunas Investimento + ROAS no front

**Files:**
- Modify: `frontend/src/components/trafego/campaign-report-table.tsx`

> **FRONTEND (obrigatório):** frontend-design + shadcn. Reusar `TH`, `tabular-nums`, paleta. Não mexer no layout de painel/sticky.

- [ ] **Step 1: Tipos** — em `CampaignRow`, `ReportTotal`, `ChannelSubtotal`, adicionar `investimento: number` e `roas: number | null`.

- [ ] **Step 2: Formatadores** — adicionar:
```tsx
const fmtRoas = (v: number | null) => (v == null ? "—" : `${v.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}x`);
```

- [ ] **Step 3: Colunas** — adicionar, entre "Receita" e "Ticket" (ou após Conversão — escolha do frontend-design, mantendo consistência): **Investimento** e **ROAS**. Regra de exibição: `investimento` só mostra R$ quando `channel === "Google Ads"` (senão "—"); `roas` usa `fmtRoas(r.roas)` ("—" quando null). Aplicar em cabeçalho, linhas de dados, subtotais e Total. Ex. célula de dados:
```tsx
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{r.channel === "Google Ads" ? fmtBRL(r.investimento) : "—"}</TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{fmtRoas(r.roas)}</TableCell>
```
No subtotal e no Total, usar `sub.investimento`/`sub.roas` e `total.investimento`/`total.roas` (o Total já traz `roas` calculado pelo backend — usar direto, não recomputar).

- [ ] **Step 4: Validar**

Run: `cd frontend; npm run type-check` → limpo.
Run: `cd frontend; npx eslint "src/components/trafego"` → limpo.
Run: `cd frontend; npm run test` → 263 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/trafego/campaign-report-table.tsx
git commit -m "feat(trafego): colunas Investimento e ROAS na tabela de campanhas"
```

---

## Self-Review (autor)
- **Cobertura do spec F2:** client REST env-gated/fail-soft → T1; tabela ad_spend → T2; sync idempotente → T3; `_spend_by_campaign` + investimento/roas (linhas/subtotais/total, ROAS total só sobre receita Google) → T4; colunas front → T5; tutorial → doc separado. ✓
- **Placeholders:** nenhum.
- **Consistência:** `parse_spend_rows`/`fetch_campaign_spend`/`google_ads_enabled`/`_REQUIRED_ENV` batem entre T1 e T3; chaves `investimento`/`roas` idênticas backend (row/total/subtotals/_empty_report) e TS (T5); junção por `campaign.strip().lower()` no report casa com a normalização de `_spend_by_campaign`.

## Ativação em produção (pós-merge — ações do usuário)
1. Aplicar `supabase/migrations/20260805_ad_spend.sql` no Supabase.
2. Setar secrets `GOOGLE_ADS_*` (6 vars) no deploy.
3. Agendar cron diário: `cd backend; python -m scripts.sync_google_ads_spend`.
4. Ver `docs/setup/google-ads-conexao.md` para obter as credenciais.
