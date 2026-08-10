# Conectar Meta Ads (investimento/ROAS) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps usam checkbox (`- [ ]`).
>
> **FRONTEND RULE:** Task 5 toca `frontend/src` → usar `frontend-design` + shadcn/ui.

**Goal:** Buscar o spend por campanha do Meta Ads (`platform='meta'` em `ad_spend`) e exibir Investimento/ROAS também nas linhas Meta Ads do /trafego — espelhando o Google.

**Architecture:** Cliente Meta Marketing API (httpx REST, env-gated/fail-soft), sync unificado no worker + botão, e generalização do ROAS no report de "só Google" para um mapa por canal (`spend_by_channel`).

**Tech Stack:** FastAPI, httpx, Supabase, pytest; Next.js, TS, shadcn.

**Spec:** `docs/superpowers/specs/2026-08-10-meta-ads-spend-roas-design.md`. Sem migration.

---

## Task 1: cliente Meta Marketing API

**Files:**
- Create: `backend/app/campaigns/meta_ads.py`
- Test: `backend/tests/test_meta_ads.py`

- [ ] **Step 1: Testes (falham)**

```python
# backend/tests/test_meta_ads.py
import app.campaigns.meta_ads as m


def test_parse_spend_rows_maps_spend():
    data = [
        {"campaign_id": "1", "campaign_name": "Atacado WA", "spend": "12.50", "date_start": "2026-08-01", "date_stop": "2026-08-01"},
        {"campaign_id": "2", "campaign_name": "Branding", "spend": "0", "date_start": "2026-08-02", "date_stop": "2026-08-02"},
    ]
    out = m.parse_spend_rows(data)
    assert out[0] == {"campaign_id": "1", "campaign_name": "Atacado WA", "date": "2026-08-01", "cost": 12.5}
    assert out[1]["cost"] == 0.0


def test_parse_spend_rows_skips_malformed():
    assert m.parse_spend_rows([{"date_start": "2026-08-01"}]) == []


def test_meta_ads_enabled_requires_token_and_account(monkeypatch):
    for k in ("META_ADS_ACCESS_TOKEN", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"):
        monkeypatch.delenv(k, raising=False)
    assert m.meta_ads_enabled() is False
    monkeypatch.setenv("META_ADS_ACCESS_TOKEN", "t")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "123")
    assert m.meta_ads_enabled() is True


def test_fetch_campaign_spend_noop_when_disabled(monkeypatch):
    for k in ("META_ADS_ACCESS_TOKEN", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"):
        monkeypatch.delenv(k, raising=False)
    import asyncio
    assert asyncio.run(m.fetch_campaign_spend("2026-08-01", "2026-08-31")) == []


def test_normalize_act_id():
    assert m._act("123456") == "act_123456"
    assert m._act("act_123456") == "act_123456"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_meta_ads.py -q`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementar**

```python
# backend/app/campaigns/meta_ads.py
"""Client REST (httpx) da Meta Marketing API para buscar investimento (spend) por campanha.

Env-gated + fail-soft: sem credenciais ou em erro → []. Espelha o padrão de google_ads.py.
Parsing puro (parse_spend_rows) isolado da rede para teste."""
import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _token() -> str:
    return os.getenv("META_ADS_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN") or ""


def _account_id() -> str:
    return os.getenv("META_AD_ACCOUNT_ID") or ""


def _act(raw: str) -> str:
    raw = (raw or "").strip()
    return raw if raw.startswith("act_") else f"act_{raw}"


def _version() -> str:
    return os.getenv("META_API_VERSION") or "v21.0"


def meta_ads_enabled() -> bool:
    return bool(_token() and _account_id())


def parse_spend_rows(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """De insights.data → [{campaign_id, campaign_name, date, cost}]. Ignora malformados."""
    out: list[dict[str, Any]] = []
    for r in data or []:
        name = r.get("campaign_name")
        if not name or "spend" not in r:
            continue
        try:
            cost = float(r.get("spend") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        out.append({
            "campaign_id": str(r.get("campaign_id") or ""),
            "campaign_name": name,
            "date": r.get("date_start"),
            "cost": cost,
        })
    return out


async def fetch_campaign_spend(date_from: str, date_to: str) -> list[dict[str, Any]]:
    """Custo por campanha/dia entre date_from e date_to (YYYY-MM-DD). Env-gated + fail-soft → []."""
    if not meta_ads_enabled():
        return []
    url = f"https://graph.facebook.com/{_version()}/{_act(_account_id())}/insights"
    params = {
        "level": "campaign",
        "fields": "campaign_id,campaign_name,spend",
        "time_range": json.dumps({"since": date_from, "until": date_to}),
        "time_increment": "1",
        "limit": "500",
        "access_token": _token(),
    }
    rows: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            next_url: str | None = url
            first = True
            for _ in range(100):  # guarda anti-loop de paginação
                resp = await client.get(next_url, params=params if first else None)
                resp.raise_for_status()
                payload = resp.json()
                rows.extend(parse_spend_rows(payload.get("data") or []))
                next_url = (payload.get("paging") or {}).get("next")
                first = False
                if not next_url:
                    break
        return rows
    except Exception as exc:
        logger.error("meta_ads: fetch_campaign_spend falhou: %s", exc)
        return []
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend; python -m pytest tests/test_meta_ads.py -q`  → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/meta_ads.py backend/tests/test_meta_ads.py
git commit -m "feat(meta): client REST httpx p/ spend por campanha (env-gated, fail-soft)"
```

---

## Task 2: sync unificado (Meta + Google)

**Files:**
- Modify: `backend/app/campaigns/ad_spend_sync.py`
- Test: `backend/tests/test_ad_spend_sync.py`

- [ ] **Step 1: Testes (falham)**

```python
# adicionar em backend/tests/test_ad_spend_sync.py
def test_sync_meta_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(s, "meta_ads_enabled", lambda: False)
    import asyncio
    assert asyncio.run(s.sync_meta_ads_spend(days=7)) == 0


def test_sync_meta_upserts_platform_meta(monkeypatch):
    captured = {}
    class _Q:
        def upsert(self, rows, on_conflict=None):
            captured["rows"] = rows; captured["oc"] = on_conflict; return self
        def execute(self):
            class R: pass
            r = R(); r.data = captured["rows"]; return r
    class _SB:
        def table(self, name): return _Q()
    monkeypatch.setattr(s, "meta_ads_enabled", lambda: True)
    monkeypatch.setattr(s, "get_supabase", lambda: _SB())
    async def fake_fetch(a, b):
        return [{"campaign_id": "1", "campaign_name": "Atacado WA", "date": "2026-08-01", "cost": 9.0}]
    monkeypatch.setattr(s, "meta_fetch_campaign_spend", fake_fetch)
    import asyncio
    n = asyncio.run(s.sync_meta_ads_spend(days=7))
    assert n == 1 and captured["rows"][0]["platform"] == "meta" and captured["oc"] == "platform,campaign_id,date"


def test_sync_all_aggregates(monkeypatch):
    async def g(days=30): return 3
    async def m(days=30): return 2
    monkeypatch.setattr(s, "sync_google_ads_spend", g)
    monkeypatch.setattr(s, "sync_meta_ads_spend", m)
    import asyncio
    assert asyncio.run(s.sync_all_ad_spend(days=30)) == {"google": 3, "meta": 2}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_ad_spend_sync.py -q`
Expected: FAIL (AttributeError sync_meta_ads_spend / sync_all_ad_spend).

- [ ] **Step 3: Implementar** — em `ad_spend_sync.py`.

Adicionar o import (com alias p/ o teste poder monkeypatchar):
```python
from app.campaigns.meta_ads import fetch_campaign_spend as meta_fetch_campaign_spend, meta_ads_enabled
```
Adicionar as funções (espelhando `sync_google_ads_spend`):
```python
async def sync_meta_ads_spend(days: int = 30) -> int:
    """Busca o spend do Meta Ads e faz upsert em ad_spend (platform='meta'). Retorna nº de linhas."""
    if not meta_ads_enabled():
        logger.info("ad_spend_sync: Meta Ads sem credenciais — no-op")
        return 0
    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=days)).isoformat()
    date_to = today.isoformat()
    try:
        spend = await meta_fetch_campaign_spend(date_from, date_to)
        if not spend:
            logger.info("ad_spend_sync(meta): nenhum spend retornado (%s..%s)", date_from, date_to)
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = [{
            "platform": "meta",
            "campaign_id": r.get("campaign_id") or None,
            "campaign_name": r.get("campaign_name"),
            "date": r.get("date"),
            "cost": r.get("cost", 0.0),
            "currency": "BRL",
            "updated_at": now_iso,
        } for r in spend if r.get("campaign_name") and r.get("date")]
        get_supabase().table("ad_spend").upsert(rows, on_conflict="platform,campaign_id,date").execute()
        logger.info("ad_spend_sync(meta): upsert de %d linhas (%s..%s)", len(rows), date_from, date_to)
        return len(rows)
    except Exception as exc:
        logger.error("ad_spend_sync(meta): falhou: %s", exc, exc_info=True)
        return 0


async def sync_all_ad_spend(days: int = 30) -> dict[str, int]:
    """Sincroniza Google + Meta (cada um env-gated/fail-soft). Retorna {'google': n, 'meta': m}."""
    g = await sync_google_ads_spend(days=days)
    m = await sync_meta_ads_spend(days=days)
    return {"google": g, "meta": m}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend; python -m pytest tests/test_ad_spend_sync.py -q`  → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/ad_spend_sync.py backend/tests/test_ad_spend_sync.py
git commit -m "feat(meta): sync_meta_ads_spend + sync_all_ad_spend (google+meta)"
```

---

## Task 3: worker tick + endpoint /sync-ads + proxy

**Files:**
- Modify: `backend/app/worker/main.py`
- Modify: `backend/app/campaigns/traffic_router.py`
- Modify: `frontend/src/app/api/traffic/sync/route.ts`
- Test: `backend/tests/test_ad_spend_sync.py`

- [ ] **Step 1: Teste (falha)**

```python
# adicionar em backend/tests/test_ad_spend_sync.py
def test_sync_endpoint_uses_sync_all(monkeypatch):
    import app.campaigns.traffic_router as tr
    async def fake_all(days=30): return {"google": 2, "meta": 1}
    monkeypatch.setattr(tr, "sync_all_ad_spend", fake_all)
    import asyncio
    out = asyncio.run(tr.sync_ads_endpoint())
    assert out == {"google": 2, "meta": 1, "synced": 3}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_ad_spend_sync.py::test_sync_endpoint_uses_sync_all -q`
Expected: FAIL (AttributeError sync_ads_endpoint / sync_all_ad_spend import).

- [ ] **Step 3: Worker tick** (`app/worker/main.py`): trocar o corpo de `_ad_spend_sync_tick`:
```python
async def _ad_spend_sync_tick() -> None:
    from app.campaigns.ad_spend_sync import sync_all_ad_spend
    await sync_all_ad_spend(days=30)
```

- [ ] **Step 4: Endpoint** (`app/campaigns/traffic_router.py`): trocar o import e o endpoint.

No import de ad_spend_sync (hoje `from app.campaigns.ad_spend_sync import sync_google_ads_spend`), trocar por:
```python
from app.campaigns.ad_spend_sync import sync_all_ad_spend
```
Substituir o endpoint `POST /sync-google-ads` por:
```python
@router.post("/sync-ads")
async def sync_ads_endpoint():
    """Dispara o sync de investimento (Google + Meta) sob demanda (admin-only na UI)."""
    res = await sync_all_ad_spend(days=30)
    return {**res, "synced": int(res.get("google", 0)) + int(res.get("meta", 0))}
```

- [ ] **Step 5: Proxy Next** (`frontend/src/app/api/traffic/sync/route.ts`): trocar o destino do fetch de `/api/traffic/sync-google-ads` para `/api/traffic/sync-ads` (só a URL do backend muda; o resto do proxy permanece).

- [ ] **Step 6: Rodar e ver passar + suíte + import + typecheck**

Run: `cd backend; python -m pytest tests/test_ad_spend_sync.py -q` → PASS.
Run: `cd backend; python -c "import app.main; import app.worker.main"` → sem erro.
Run: `cd frontend; npm run type-check` → limpo.

- [ ] **Step 7: Commit**

```bash
git add backend/app/worker/main.py backend/app/campaigns/traffic_router.py "frontend/src/app/api/traffic/sync" backend/tests/test_ad_spend_sync.py
git commit -m "feat(meta): sync unificado no worker + endpoint /api/traffic/sync-ads"
```

---

## Task 4: ROAS por canal pago (spend_by_channel) no report

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py`
- Test: `backend/tests/test_traffic_report.py`

- [ ] **Step 1: Testes (falham)** — atualizar os testes que passam `spend_by_campaign` p/ `spend_by_channel` e adicionar Meta.

```python
# substituir/adicionar em test_traffic_report.py
def test_build_roas_google_and_meta_rows():
    leads = [_lead("a", gclid="1", utm_campaign="atacado"),
             _lead("b", fbclid="2", utm_campaign="pl_wa_01")]
    sales = {"a": {"count": 1, "value": 300.0}, "b": {"count": 1, "value": 200.0}}
    spend_by_channel = {"Google Ads": {"atacado": 100.0}, "Meta Ads": {"pl_wa_01": 50.0}}
    out = build_campaign_report(leads, set(), set(), sales, mode="lead", period="30d",
                                spend_by_channel=spend_by_channel)
    rows = {(r["channel"], r["campaign"]): r for r in out["rows"]}
    g = rows[("Google Ads", "atacado")]
    assert g["investimento"] == 100.0 and g["roas"] == 3.0
    mrow = rows[("Meta Ads", "pl_wa_01")]
    assert mrow["investimento"] == 50.0 and mrow["roas"] == 4.0
    # total ROAS = (receita Google 300 + receita Meta 200) / investimento 150 = 500/150
    assert out["total"]["investimento"] == 150.0
    assert out["total"]["roas"] == round(500.0 / 150.0, 2)
```
Atualizar os testes antigos `test_build_roas_only_for_google_rows` e `test_build_roas_none_when_no_spend` para usar `spend_by_channel={"Google Ads": {...}}` (mesma semântica; canal Meta sem mapa → investimento 0/roas None).

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: FAIL (TypeError unexpected 'spend_by_channel').

- [ ] **Step 3: Implementar** — em `build_campaign_report`:

Trocar o parâmetro:
```python
    spend_by_channel: dict[str, dict[str, float]] | None = None,
```
Trocar o bloco de atribuição de investimento (o `if row["channel"] == "Google Ads": ...`) por:
```python
    spend_by_channel = spend_by_channel or {}
    for row in groups.values():
        smap = spend_by_channel.get(row["channel"])
        if smap:
            utm_key = row["campaign"].strip().lower()
            cost = smap.get(utm_key)
            if cost is None:
                cost = _fuzzy_spend_lookup(utm_key, smap)
            row["investimento"] = float(cost or 0.0)
```
No loop de totais, trocar `google_receita` por `paid_receita` acumulando quando o canal é pago:
```python
    paid_receita = 0.0
    for row in groups.values():
        ...
        if row["channel"] in spend_by_channel:
            paid_receita += row["receita"]
        ...
```
E o total ROAS:
```python
    total["roas"] = round(paid_receita / total["investimento"], 2) if total["investimento"] else None
```
Atualizar o docstring do parâmetro (spend_by_channel: canal → {campaign_name_norm: cost}).

Em `traffic_report` e `campaign_detail`, trocar as 2 chamadas:
```python
        spend_by_channel = {
            "Google Ads": _spend_by_campaign(sb, lo, hi, "google"),
            "Meta Ads": _spend_by_campaign(sb, lo, hi, "meta"),
        }
        return build_campaign_report(leads, conversed, closers, sales, mode, period,
                                     spend_by_channel=spend_by_channel)
```
(em `campaign_detail`, idem, passando `spend_by_channel=spend_by_channel`).

- [ ] **Step 4: Rodar e ver passar + suíte**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q` → PASS.
Run: `cd backend; python -m pytest -q` → sem regressão.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/traffic_report.py backend/tests/test_traffic_report.py
git commit -m "feat(meta): ROAS por canal pago (spend_by_channel) — Google + Meta"
```

---

## Task 5: frontend mostra Investimento/ROAS p/ Meta

**Files:**
- Modify: `frontend/src/components/trafego/campaign-report-table.tsx`
- Modify: `frontend/src/components/trafego/campaign-kpis.tsx`

> **FRONTEND:** frontend-design + shadcn. Sem novas colunas — só mudar a CONDIÇÃO de exibição.

- [ ] **Step 1: Tabela** — na célula de Investimento das linhas de dados, trocar a condição
  `r.channel === "Google Ads" ? fmtBRL(r.investimento) : "—"` por
  `r.investimento > 0 ? fmtBRL(r.investimento) : "—"` (cobre Google **e** Meta; ROAS já usa `fmtRoas(r.roas)`).

- [ ] **Step 2: KPIs (página de detalhe)** — em `campaign-kpis.tsx`, os cards Investimento/ROAS
  hoje aparecem só quando `summary.channel === "Google Ads"`. Trocar a condição para
  `const hasSpend = summary.investimento > 0 || summary.roas != null;` e usar `hasSpend` no lugar de `isGoogle`.

- [ ] **Step 3: Validar**

Run: `cd frontend; npm run type-check` → limpo.
Run: `cd frontend; npx eslint "src/components/trafego"` → limpo.
Run: `cd frontend; npm run test` → 263 passed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/trafego/campaign-report-table.tsx frontend/src/components/trafego/campaign-kpis.tsx
git commit -m "feat(meta): exibe Investimento/ROAS tambem p/ Meta Ads"
```

---

## Task 6: tutorial de conexão do Meta (feito pelo controlador)
- Criar `docs/setup/meta-ads-conexao.md` (Business Manager → System User → ads_read na conta →
  gerar token → pegar Ad Account ID → setar `META_ADS_ACCESS_TOKEN` + `META_AD_ACCOUNT_ID`).
  Escrito pelo controlador (fora do fluxo de subagent) para precisão dos passos externos.

---

## Self-Review (autor)
- **Cobertura do spec:** client Meta (T1); sync meta+all (T2); worker+endpoint+proxy (T3);
  ROAS por canal pago (T4); frontend Meta (T5); tutorial (T6). ✓
- **Placeholders:** nenhum.
- **Consistência:** `spend_by_channel: dict[str, dict[str,float]]` idêntico em build/traffic_report/
  campaign_detail e nos testes; `sync_all_ad_spend`/`sync_meta_ads_spend`/`meta_ads_enabled`/
  `fetch_campaign_spend` batem entre T1/T2/T3; endpoint `/sync-ads` ↔ proxy Next.

## Ativação (usuário)
- Setar `META_ADS_ACCESS_TOKEN` + `META_AD_ACCOUNT_ID` no `.env` (api + worker). Sem migration.
- Ver `docs/setup/meta-ads-conexao.md`. Após deploy: worker sincroniza Meta no boot; botão força.
