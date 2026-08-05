# /trafego recompra + ciclo de reposição — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.
>
> **FRONTEND RULE:** Qualquer task que toque `frontend/src` DEVE usar a skill `frontend-design` + shadcn/ui. Se a skill não carregar, ler o SKILL.md do cache (ver memory `feedback_frontend_skill`).

**Goal:** Adicionar visibilidade de recompra no Relatório Campanhas (coluna Clientes + Pedidos) e implementar o ciclo de reposição (todo `fechado_ganho` gera nova oportunidade + backfill).

**Architecture:** C muda a agregação pura `build_campaign_report` (backend) e a tabela (frontend). D adiciona um helper `ensure_reposicao_deal` idempotente (via `create_deal(dedupe_open=True)`) disparado por todos os caminhos que levam um deal a `fechado_ganho` (trigger `deal_stage_enter`, evento `sale_created`, `mark_deal_won`) + script de backfill.

**Tech Stack:** FastAPI, Supabase, pytest; Next.js App Router, TypeScript, shadcn/ui.

**Pré-requisito:** as peças A (rename Direto→Sem rastreio) e B (datas no drill-down) já estão implementadas (commits de3a0942, 0d500601). Este plano parte desse estado.

---

## File Structure

- Modify `backend/app/campaigns/traffic_report.py` — `build_campaign_report` (C: clientes+pedidos).
- Modify `backend/tests/test_traffic_report.py` — atualizar/adicionar testes de C.
- Modify `frontend/src/components/trafego/campaign-report-table.tsx` — colunas Clientes+Pedidos (C).
- Create `backend/app/leads/reposicao.py` — `ensure_reposicao_deal` + `deal_is_won` (D).
- Create `backend/tests/test_reposicao.py` — testes de D.
- Modify `backend/app/automation/triggers.py` — hooks `deal_stage_enter`(fechado_ganho) e `sale_created` (D).
- Modify `backend/app/leads/router.py` — hook em `mark_lead_won` (D).
- Create `backend/scripts/backfill_reposicao_deals.py` — backfill (D).

**Contrato de dados C (novas chaves em cada `row`, `total`, `channel_subtotals[canal]`):**
`clientes` (= antigo `vendas`: leads distintos que compraram), `pedidos` (nº de vendas, soma dos counts). `ticket_medio = receita/pedidos`; `conversao = clientes/leads`.

---

## Task 1 (C): `build_campaign_report` — clientes + pedidos

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py:46-92`
- Test: `backend/tests/test_traffic_report.py`

- [ ] **Step 1: Atualizar/escrever testes (falham)**

Substituir o corpo de `test_build_metrics_conversas_closer_vendas_receita` e adicionar um teste de recompra. Localize os testes existentes que citam `vendas` e ajuste-os:

```python
def test_build_metrics_clientes_pedidos_receita():
    leads = [_lead("a", gclid="1", utm_campaign="black"),
             _lead("b", gclid="2", utm_campaign="black")]
    sales_by_lead = {"a": {"count": 1, "value": 100.0}}
    out = build_campaign_report(leads, {"a"}, {"a", "b"}, sales_by_lead, mode="lead", period="30d")
    row = out["rows"][0]
    assert row["conversas"] == 1
    assert row["closer"] == 2
    assert row["clientes"] == 1
    assert row["pedidos"] == 1
    assert row["receita"] == 100.0
    assert row["ticket_medio"] == 100.0
    assert row["conversao"] == 0.5


def test_build_repeat_purchase_counts_pedidos_not_clientes():
    # 1 lead que comprou 2x: clientes=1, pedidos=2, ticket=receita/2, conversao=clientes/leads
    leads = [_lead("a", gclid="1", utm_campaign="x")]
    sales_by_lead = {"a": {"count": 2, "value": 300.0}}
    out = build_campaign_report(leads, set(), set(), sales_by_lead, mode="lead", period="30d")
    row = out["rows"][0]
    assert row["clientes"] == 1
    assert row["pedidos"] == 2
    assert row["receita"] == 300.0
    assert row["ticket_medio"] == 150.0
    assert row["conversao"] == 1.0


def test_build_total_and_subtotals_have_clientes_and_pedidos():
    leads = [_lead("a", gclid="1", utm_campaign="x"),
             _lead("b", fbclid="2", utm_campaign="y")]
    sales_by_lead = {"a": {"count": 1, "value": 50.0}, "b": {"count": 2, "value": 30.0}}
    out = build_campaign_report(leads, {"a"}, {"a"}, sales_by_lead, mode="lead", period="30d")
    assert out["total"] == {"leads": 2, "conversas": 1, "closer": 1,
                            "clientes": 2, "pedidos": 3, "receita": 80.0}
    assert out["channel_subtotals"]["Google Ads"] == {
        "leads": 1, "conversas": 1, "closer": 1, "clientes": 1, "pedidos": 1, "receita": 50.0}
    assert out["channel_subtotals"]["Meta Ads"] == {
        "leads": 1, "conversas": 0, "closer": 0, "clientes": 1, "pedidos": 2, "receita": 30.0}
```

Remova/ajuste os testes antigos que assertavam a chave `vendas` (ex.: `test_build_total_aggregates_all_rows`, `test_build_channel_subtotals`, `test_build_metrics_conversas_closer_vendas_receita`) — substitua pelas versões acima (mesmos cenários, chaves novas).

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: FAIL (KeyError 'clientes'/'pedidos' ou assert de chave `vendas`).

- [ ] **Step 3: Implementar** — substituir `build_campaign_report` (linhas 46-92) por:

```python
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for lead in leads:
        lead_id = lead.get("id")
        channel = derive_channel(lead)
        campaign = _s(lead.get("utm_campaign")) or _NO_CAMPAIGN
        key = (channel, campaign)
        row = groups.get(key)
        if row is None:
            row = {"channel": channel, "campaign": campaign, "leads": 0, "conversas": 0,
                   "closer": 0, "clientes": 0, "pedidos": 0, "receita": 0.0}
            groups[key] = row
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

    rows: list[dict[str, Any]] = []
    total = {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0, "receita": 0.0}
    for row in groups.values():
        pedidos = row["pedidos"]
        row["ticket_medio"] = round(row["receita"] / pedidos, 2) if pedidos else 0.0
        row["conversao"] = round(row["clientes"] / row["leads"], 4) if row["leads"] else 0.0
        for k in total:
            total[k] += row[k]
        rows.append(row)

    channel_subtotals: dict[str, dict[str, Any]] = {}
    for row in rows:
        sub = channel_subtotals.get(row["channel"])
        if sub is None:
            sub = {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0, "receita": 0.0}
            channel_subtotals[row["channel"]] = sub
        for k in sub:
            sub[k] += row[k]
    for sub in channel_subtotals.values():
        sub["receita"] = round(sub["receita"], 2)

    rows.sort(key=lambda r: (r["channel"], -r["receita"], -r["leads"]))
    total["receita"] = round(total["receita"], 2)
    return {"mode": mode, "period": period, "rows": rows, "total": total,
            "channel_subtotals": channel_subtotals}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend; python -m pytest tests/test_traffic_report.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/traffic_report.py backend/tests/test_traffic_report.py
git commit -m "feat(trafego): metricas Clientes + Pedidos (recompra) no relatorio"
```

---

## Task 2 (C): tabela do relatório — colunas Clientes + Pedidos

**Files:**
- Modify: `frontend/src/components/trafego/campaign-report-table.tsx`

> **FRONTEND:** usar frontend-design + shadcn. Manter o estilo atual (constante `TH`, `tabular-nums`, paleta). Só adicionar/renomear colunas; não mudar o layout de painel/sticky.

- [ ] **Step 1: Tipos** — em `CampaignRow`, renomear `vendas` → `clientes` e adicionar `pedidos: number`. Em `ReportTotal` e `ChannelSubtotal`, idem (`vendas`→`clientes`, `+pedidos`). Resultado:

```tsx
export type CampaignRow = {
  channel: string; campaign: string; leads: number; conversas: number;
  closer: number; clientes: number; pedidos: number; receita: number; ticket_medio: number; conversao: number;
};
export type ReportTotal = { leads: number; conversas: number; closer: number; clientes: number; pedidos: number; receita: number };
export type ChannelSubtotal = { leads: number; conversas: number; closer: number; clientes: number; pedidos: number; receita: number };
```

- [ ] **Step 2: Cabeçalho** — trocar a coluna "Vendas" por **"Clientes"** e adicionar **"Pedidos"** logo depois. Nova ordem de `TableHead`: Canal, Campanha, Leads, Conversas, Closer, **Clientes**, **Pedidos**, Receita, Ticket, Conversão. Ex.:

```tsx
          <TableHead className={`${TH} text-right`}>Clientes</TableHead>
          <TableHead className={`${TH} text-right`}>Pedidos</TableHead>
```
(no lugar do antigo `<TableHead ...>Vendas</TableHead>`, e o de Pedidos inserido em seguida.)

- [ ] **Step 3: Linha de dados** — trocar a célula `{fmtInt(r.vendas)}` por duas células:

```tsx
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{fmtInt(r.clientes)}</TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{fmtInt(r.pedidos)}</TableCell>
```

- [ ] **Step 4: Subtotal e Total** — nas linhas de subtotal por canal e no `TableFooter` (Total), trocar a célula de `sub.vendas`/`total.vendas` por duas células (clientes e pedidos), mantendo o mesmo estilo das demais células numéricas daquela linha. Ex. no subtotal:

```tsx
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtInt(sub.clientes)}</TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtInt(sub.pedidos)}</TableCell>
```
E no Total (mesmo padrão, classe `text-[14px]`). Os `colSpan={2}` dos rótulos "Subtotal · canal" e "Total" continuam 2 (Canal+Campanha); só há uma célula numérica a mais por causa de Pedidos.

- [ ] **Step 5: Recalcular ticket/conversão do Total no front** — onde hoje há `totalTicket`/`totalConversao`, ajustar para as novas semânticas:

```tsx
  const totalConversao = total && total.leads > 0 ? total.clientes / total.leads : 0;
  const totalTicket = total && total.pedidos > 0 ? total.receita / total.pedidos : 0;
```

- [ ] **Step 6: Validar**

Run: `cd frontend; npm run type-check`  → limpo.
Run: `cd frontend; npx eslint "src/components/trafego"` → limpo.
Run: `cd frontend; npm run test` → 263 passed.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/trafego/campaign-report-table.tsx
git commit -m "feat(trafego): colunas Clientes e Pedidos na tabela de campanhas"
```

---

## Task 3 (D): `ensure_reposicao_deal` + `deal_is_won`

**Files:**
- Create: `backend/app/leads/reposicao.py`
- Test: `backend/tests/test_reposicao.py`

- [ ] **Step 1: Escrever os testes (falham)**

```python
# backend/tests/test_reposicao.py
import app.leads.reposicao as rep


def test_ensure_reposicao_deal_creates_in_reposicao_pipeline(monkeypatch):
    calls = {}
    def fake_create_deal(lead_id, title, category=None, *, pipeline_name=None, stage_label=None, dedupe_open=False):
        calls.update(lead_id=lead_id, pipeline_name=pipeline_name, dedupe_open=dedupe_open)
        return {"id": "d1"}
    monkeypatch.setattr(rep, "create_deal", fake_create_deal)
    rep.ensure_reposicao_deal("lead-1")
    assert calls["lead_id"] == "lead-1"
    assert calls["pipeline_name"] == rep.REPOSICAO_PIPELINE_NAME
    assert calls["dedupe_open"] is True


def test_ensure_reposicao_deal_failsoft(monkeypatch):
    def boom(*a, **k): raise RuntimeError("db down")
    monkeypatch.setattr(rep, "create_deal", boom)
    # não deve levantar
    rep.ensure_reposicao_deal("lead-1")


class _FakeQ:
    def __init__(self, rows): self._rows = rows
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self):
        class R: pass
        r = R(); r.data = self._rows; return r


class _FakeSB:
    def __init__(self, deals, stages): self._d = deals; self._s = stages
    def table(self, name): return _FakeQ(self._d if name == "deals" else self._s)


def test_deal_is_won_true_when_stage_key_fechado_ganho(monkeypatch):
    sb = _FakeSB(deals=[{"stage_id": "s1"}], stages=[{"key": "fechado_ganho"}])
    monkeypatch.setattr(rep, "get_supabase", lambda: sb)
    assert rep.deal_is_won("d1") is True


def test_deal_is_won_false_other_stage(monkeypatch):
    sb = _FakeSB(deals=[{"stage_id": "s1"}], stages=[{"key": "qualificado"}])
    monkeypatch.setattr(rep, "get_supabase", lambda: sb)
    assert rep.deal_is_won("d1") is False
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_reposicao.py -q`
Expected: FAIL (ModuleNotFoundError app.leads.reposicao).

- [ ] **Step 3: Implementar**

```python
# backend/app/leads/reposicao.py
"""Ciclo de reposição: todo deal que fecha em 'fechado_ganho' garante uma nova
oportunidade aberta para o lead (recompra). Idempotente e fail-soft."""
import logging
from typing import Any

from app.db.supabase import get_supabase
from app.leads.service import create_deal

logger = logging.getLogger(__name__)

REPOSICAO_PIPELINE_NAME = "Reposição - João"
_WON_KEY = "fechado_ganho"


def ensure_reposicao_deal(lead_id: str) -> None:
    """Garante uma oportunidade aberta para o lead (cria no pipeline de Reposição se não houver).

    `create_deal(dedupe_open=True)` reaproveita qualquer deal aberto do lead → nunca duplica.
    Fail-soft: nunca levanta (não pode derrubar o fluxo de venda/Kanban).
    """
    if not lead_id:
        return
    try:
        create_deal(
            lead_id,
            title="Reposição",
            pipeline_name=REPOSICAO_PIPELINE_NAME,
            dedupe_open=True,
        )
    except Exception as exc:
        logger.error("ensure_reposicao_deal(%s) falhou: %s", lead_id, exc, exc_info=True)


def deal_is_won(deal_id: str) -> bool:
    """True se o stage atual do deal tem key 'fechado_ganho'. Fail-soft → False em erro."""
    if not deal_id:
        return False
    try:
        sb = get_supabase()
        deal = sb.table("deals").select("stage_id").eq("id", deal_id).limit(1).execute().data
        if not deal:
            return False
        stage_id = deal[0].get("stage_id")
        if not stage_id:
            return False
        stage = sb.table("pipeline_stages").select("key").eq("id", stage_id).limit(1).execute().data
        return bool(stage) and stage[0].get("key") == _WON_KEY
    except Exception as exc:
        logger.error("deal_is_won(%s) falhou: %s", deal_id, exc, exc_info=True)
        return False
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend; python -m pytest tests/test_reposicao.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/leads/reposicao.py backend/tests/test_reposicao.py
git commit -m "feat(reposicao): helper ensure_reposicao_deal + deal_is_won"
```

---

## Task 4 (D): hooks em `triggers.py` (deal_stage_enter + sale_created)

**Files:**
- Modify: `backend/app/automation/triggers.py:46-98`
- Test: `backend/tests/test_reposicao.py`

- [ ] **Step 1: Escrever teste (falha)**

```python
# adicionar em backend/tests/test_reposicao.py
import asyncio
import app.automation.triggers as trg


def test_fire_trigger_deal_won_calls_ensure(monkeypatch):
    called = {}
    monkeypatch.setattr(trg, "ensure_reposicao_deal", lambda lid: called.setdefault("lead", lid))
    monkeypatch.setattr(trg, "deal_is_won", lambda did: True)
    monkeypatch.setattr(trg, "_maybe_fire_stage_conversion", lambda lid, data: None)
    monkeypatch.setattr(trg, "get_campaigns_with_trigger_type", lambda t: [])
    asyncio.run(trg.fire_trigger("deal_stage_enter", "lead-9", {"deal_id": "d1"}))
    assert called.get("lead") == "lead-9"


def test_fire_trigger_sale_created_calls_ensure(monkeypatch):
    called = {}
    monkeypatch.setattr(trg, "ensure_reposicao_deal", lambda lid: called.setdefault("lead", lid))
    monkeypatch.setattr(trg, "get_campaigns_with_trigger_type", lambda t: [])
    asyncio.run(trg.fire_trigger("sale_created", "lead-7", {"value": 100}))
    assert called.get("lead") == "lead-7"


def test_fire_trigger_non_won_stage_does_not_call_ensure(monkeypatch):
    called = {}
    monkeypatch.setattr(trg, "ensure_reposicao_deal", lambda lid: called.setdefault("lead", lid))
    monkeypatch.setattr(trg, "deal_is_won", lambda did: False)
    monkeypatch.setattr(trg, "_maybe_fire_stage_conversion", lambda lid, data: None)
    monkeypatch.setattr(trg, "get_campaigns_with_trigger_type", lambda t: [])
    asyncio.run(trg.fire_trigger("deal_stage_enter", "lead-1", {"deal_id": "d1"}))
    assert "lead" not in called
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend; python -m pytest tests/test_reposicao.py -q`
Expected: FAIL (AttributeError: module 'triggers' has no attribute 'ensure_reposicao_deal').

- [ ] **Step 3: Implementar** — no topo de `triggers.py`, adicionar o import:

```python
from app.leads.reposicao import ensure_reposicao_deal, deal_is_won
```

Dentro de `fire_trigger`, no bloco do `deal_stage_enter` (após a chamada de `_maybe_fire_stage_conversion`), e um novo ramo `sale_created`:

```python
        if event_type == "deal_stage_enter":
            _maybe_fire_stage_conversion(lead_id, data)
            # Ciclo de reposição: se o deal entrou em 'fechado_ganho', garante nova oportunidade.
            if deal_is_won(data.get("deal_id")):
                ensure_reposicao_deal(lead_id)

        if event_type == "sale_created":
            # Registrar venda move o deal p/ fechado_ganho sem emitir deal_stage_enter → hook aqui.
            ensure_reposicao_deal(lead_id)
```

(Manter o resto da função intacto; o loop genérico de enrollment de `sale_created` continua rodando depois.)

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend; python -m pytest tests/test_reposicao.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/triggers.py backend/tests/test_reposicao.py
git commit -m "feat(reposicao): dispara ensure_reposicao_deal em deal_stage_enter(ganho) e sale_created"
```

---

## Task 5 (D): hook em `mark_lead_won` (endpoint /won)

**Files:**
- Modify: `backend/app/leads/router.py:108-132`

- [ ] **Step 1: Implementar** — em `mark_lead_won`, após o `mark_deal_won`, disparar reposição quando algum deal foi marcado ganho. Adicionar o import local e a chamada:

```python
    result = mark_deal_won(lead_id, value=body.value, currency=body.currency, deal_id=body.deal_id)

    # Ciclo de reposição: deal ganho → garante nova oportunidade aberta (fail-soft).
    if result.get("deals_updated"):
        from app.leads.reposicao import ensure_reposicao_deal
        ensure_reposicao_deal(lead_id)
```

(Colocar logo antes do bloco `if result.get("deal_id"):` que agenda a conversão.)

- [ ] **Step 2: Smoke — o app importa**

Run: `cd backend; python -c "import app.main"`
Expected: sem erro.

- [ ] **Step 3: Suíte backend completa (sem regressão)**

Run: `cd backend; python -m pytest -q`
Expected: PASS (sem novas falhas).

- [ ] **Step 4: Commit**

```bash
git add backend/app/leads/router.py
git commit -m "feat(reposicao): mark_lead_won garante oportunidade de reposicao"
```

---

## Task 6 (D): script de backfill

**Files:**
- Create: `backend/scripts/backfill_reposicao_deals.py`

- [ ] **Step 1: Implementar** — script idempotente que cria oportunidade de reposição para leads que já têm `fechado_ganho` e nenhum deal aberto.

```python
# backend/scripts/backfill_reposicao_deals.py
"""Backfill do ciclo de reposição: para todo lead com >=1 deal 'fechado_ganho' e SEM deal
aberto, cria uma oportunidade de reposição. Idempotente (ensure_reposicao_deal usa
create_deal(dedupe_open=True)); pode rodar 2x sem duplicar.

Uso: python -m scripts.backfill_reposicao_deals   (a partir de backend/)
"""
import logging

from app.db.supabase import get_supabase
from app.leads.service import get_open_deal
from app.leads.reposicao import ensure_reposicao_deal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_reposicao")


def main() -> None:
    sb = get_supabase()
    won_stage_ids = [s["id"] for s in (
        sb.table("pipeline_stages").select("id").eq("key", "fechado_ganho").execute().data or []
    )]
    if not won_stage_ids:
        logger.info("Nenhum stage 'fechado_ganho' — nada a fazer.")
        return

    won_deals = (
        sb.table("deals").select("lead_id").in_("stage_id", won_stage_ids).execute().data or []
    )
    lead_ids = sorted({d["lead_id"] for d in won_deals if d.get("lead_id")})
    logger.info("Leads com fechado_ganho: %d", len(lead_ids))

    created = 0
    for lead_id in lead_ids:
        try:
            if get_open_deal(lead_id):
                continue  # já tem oportunidade aberta
            ensure_reposicao_deal(lead_id)
            created += 1
        except Exception as exc:
            logger.error("backfill: lead %s falhou: %s", lead_id, exc)
    logger.info("Backfill concluído — oportunidades de reposição criadas: %d", created)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke — compila/importa**

Run: `cd backend; python -c "import ast; ast.parse(open('scripts/backfill_reposicao_deals.py').read()); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/backfill_reposicao_deals.py
git commit -m "feat(reposicao): script de backfill de oportunidades de reposicao"
```

> **Execução do backfill** é manual/autorizada (roda contra produção). NÃO rodar automaticamente — deixar para o usuário após deploy.

---

## Self-Review (autor do plano)

- **Cobertura do spec:** C (clientes+pedidos, ticket=receita/pedidos, conversão=clientes/leads) → Tasks 1-2 ✓. D (helper idempotente → T3; gatilhos deal_stage_enter/sale_created → T4; mark_deal_won → T5; backfill → T6) ✓. Pipeline "Reposição - João" via `REPOSICAO_PIPELINE_NAME` ✓. A/B já feitos (pré-requisito) ✓.
- **Placeholders:** nenhum — todo passo tem código/comando.
- **Consistência de tipos:** chaves `clientes`/`pedidos` idênticas em backend (row/total/subtotals) e nos tipos TS (`CampaignRow`/`ReportTotal`/`ChannelSubtotal`); `ensure_reposicao_deal`/`deal_is_won`/`REPOSICAO_PIPELINE_NAME` referenciados igualmente em T3/T4/T5/T6.

## Validação final pós-implementação
- `cd backend; python -m pytest -q` (0 regressões) e frontend `npm run type-check` + `npm run test`.
- Backfill: rodar manualmente em prod após deploy (autorização do usuário).
