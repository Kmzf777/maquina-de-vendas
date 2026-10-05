# P2 — Relatório /trafego (call de Ads de 01/10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Neste pacote a execução é **inline** (sem subagentes), com superpowers:test-driven-development.

**Goal:** O /trafego passa a mostrar um funil coerente (cliente ⊂ closer ⊂ conversa, sem vendas
canceladas), respeitar a campanha atribuída à mão por um admin, mostrar "Já era cliente /
Compras / Primeira origem" por lead, e ganha um script que recupera o `meta_ad_id` dos leads CTWA
anteriores a 21/08/2026.

**Architecture:** O relatório continua puro em `build_campaign_report`/`select_campaign_leads`
(funções sem I/O) e fail-soft nas funções que leem o banco. A atribuição manual mora num módulo
novo `traffic_attribution.py` (regra + I/O) exposto por dois endpoints novos em
`traffic_router.py`, protegidos por JWT de admin (o backend é público); o Next só repassa o token
(`adminProxy`). O script de recuperação é stdlib pura, fala com o banco via `psql` (dry-run em
sessão read-only) e tem a lógica de casamento isolada numa função pura testada.

**Tech Stack:** FastAPI + supabase-py, pytest (container `canastra-api`); Next.js 16 App Router,
React, vitest + @testing-library/react (jsdom); Postgres 17 (descartável `crm-scratch-pg`).

**Spec:** `docs/superpowers/specs/2026-10-06-call-semanal-0110-design.md` (Diagnóstico 1 e 3; P2).
**Plano mestre:** `docs/superpowers/plans/2026-10-06-call-semanal-0110.md` (Regras de execução, P0, P2).

---

## Regras (resumo do plano mestre — valem para todo passo)

- Todo pytest/vitest/eslint/docker dentro de `flock /root/crm-wt/_heavy.lock …`. Sem `next build`,
  sem suíte completa, sem `tsc` do projeto, sem `npm install`.
- Produção: **somente leitura**. O script roda em produção só em dry-run.
- Commits pequenos na `feat/cs-p2`; nunca push; nunca `git stash` sem tag.
- Só arquivos do P2. Precisa de outro? Para e reporta.

Comando de teste backend (referido abaixo como **PYTEST**):

```bash
cd /root/crm-wt/cs-p2 && flock /root/crm-wt/_heavy.lock docker run --rm --user root \
  -v $PWD:/repo -w /repo/backend -e SUPABASE_URL=https://example.supabase.co \
  -e SUPABASE_SERVICE_KEY=ci-dummy canastra-api:latest sh -c \
  "pip install -q -r requirements-dev.txt >/dev/null 2>&1; python -m pytest -q -p no:cacheprovider <arquivos>"
```

Comando de teste frontend (**VITEST**): `cd /root/crm-wt/cs-p2/frontend && flock /root/crm-wt/_heavy.lock npx vitest run <arquivos>`.

---

## Contexto que o executor precisa saber

- `backend/app/campaigns/traffic_report.py` — `build_campaign_report` (linhas ~178-306) conta
  `conversas`/`closer`/`clientes` como **conjuntos independentes**: o webhook do Bling cria lead já
  com venda, sem conversa nem deal → "4 closer e 10 clientes" na call. `_sales_by_lead` (~573)
  conta venda `cancelada`.
- `_fetch_leads` degrada o `select` quando a coluna `meta_ad_id` não existe (flag `_MetaAdCol`).
  As colunas do P0 (`campanha_manual_*`, `ja_era_cliente*`) **não existem em produção** até o
  Rafael aplicar a migração `20261006_call_semanal_base.sql` → precisa da mesma degradação, mas
  só quando o erro cita uma coluna do P0 (um erro de rede não pode desligar o recurso).
- `lead_primeira_origem` (view do P0) começa vazia; o P3 a enche. Leitura fail-soft.
- O backend é alcançável publicamente (`api.canastrainteligencia.com`). As rotas GET do
  /trafego não têm guarda no backend (histórico); as duas rotas novas **gravam/expõem** dado e
  exigem JWT de admin — mesmo padrão de `button_flow/valeria_flow_router.py` +
  `frontend/src/app/api/valeria-flow/_shared.ts` (`adminProxy`, que repassa o Bearer).
- Caso Serginho (produção, lido em 06/10): lead `7c8638ee-0f89-4050-ba5a-de025d93b2da`, phone
  `5566997222209`, `created_at 2026-08-20 16:33:47.213672+00`, `ctwa_clid Afhy6J1…NNw`,
  `meta_ad_id` nulo. Log `e5caacdb-…` em `meta_webhook_logs`: `from 556697222209` (**sem o 9º
  dígito**), mesmo `ctwa_clid`, `source_id 120250785520090163`, `received_at 16:33:47.155459+00`.
- Todo referral em produção tem `source_type='ad'` (1820 de 1820); 1717 trazem `ctwa_clid`.

## Mapa de arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `backend/app/campaigns/traffic_report.py` | Modificar | funil cumulativo, canceladas fora, atribuição manual, colunas novas por lead, degradação P0 |
| `backend/app/campaigns/traffic_attribution.py` | Criar | regra + I/O da atribuição manual; lista de campanhas com gasto (120 d) |
| `backend/app/campaigns/traffic_router.py` | Modificar | `GET /api/traffic/campanhas`, `PATCH /api/traffic/leads/{id}/campanha`, guarda `exigir_admin` |
| `backend/tests/test_cs_p2_trafego.py` | Criar | testes 2.1–2.4 (backend) |
| `backend/tests/test_traffic_report.py` | Modificar (1 asserção) | o teste antigo afirmava o funil independente que a spec mandou trocar |
| `frontend/src/app/api/traffic/campanhas/route.ts` | Criar | proxy admin (GET) |
| `frontend/src/app/api/traffic/leads/[id]/campanha/route.ts` | Criar | proxy admin (PATCH) |
| `frontend/src/components/trafego/campaign-leads-table.tsx` | Modificar | colunas novas, selo "manual", estado local da atribuição |
| `frontend/src/components/trafego/campaign-attribution.tsx` | Criar | select agrupado por canal, atribuir/remover |
| `frontend/src/components/trafego/campaign-lead-panel.tsx` | Modificar | monta `CampaignAttribution` |
| `frontend/src/components/trafego/report-summary.tsx` | Modificar | stat "Entraram já como cliente" |
| `frontend/src/components/trafego/*.test.tsx` | Criar | vitest dos três componentes |
| `scripts/trafego/recuperar_meta_ad_id.py` | Criar | recuperação de `meta_ad_id` (dry-run padrão) |
| `backend/tests/test_cs_p2_recuperar_meta_ad_id.py` | Criar | testes do casamento (Serginho) e do `main` |

---

### Task 1: Funil cumulativo + vendas canceladas fora (spec P2.1)

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py` (`build_campaign_report`, `build_report_summary`, `_fetch_leads`, `_sales_by_lead`, `campaign_detail`)
- Modify: `backend/tests/test_traffic_report.py` (`test_build_metrics_clientes_pedidos_receita`)
- Test: `backend/tests/test_cs_p2_trafego.py`

- [ ] **Step 1: Write the failing tests** — criar `backend/tests/test_cs_p2_trafego.py`:

```python
"""P2 da call de Ads de 01/10 — relatório /trafego.

Spec: docs/superpowers/specs/2026-10-06-call-semanal-0110-design.md (P2). Cobre o funil
cumulativo sem canceladas (2.1), a atribuição manual (2.2), os endpoints de atribuição (2.3)
e as colunas novas da tabela de leads da campanha (2.4).
"""
import pytest

import app.campaigns.traffic_report as tr


# --- Banco falso com filtro de verdade (eq/in_/gte/lte/range/limit/update/insert) ---------

class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, banco, tabela):
        self.banco, self.tabela = banco, tabela
        self.filtros, self.cols, self.op, self.payload = [], "*", "select", None
        self._range = self._limit = None

    def select(self, cols="*", **_):
        self.cols = cols
        return self

    def eq(self, col, val):
        self.filtros.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        vs = set(vals)
        self.filtros.append(lambda r: r.get(col) in vs)
        return self

    def gte(self, col, val):
        self.filtros.append(lambda r: str(r.get(col) or "") >= str(val))
        return self

    def lte(self, col, val):
        self.filtros.append(lambda r: str(r.get(col) or "") <= str(val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def update(self, patch):
        self.op, self.payload = "update", patch
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def execute(self):
        if self.tabela in self.banco.ausentes:
            raise Exception(f'relation "public.{self.tabela}" does not exist')
        linhas = self.banco.tabelas.setdefault(self.tabela, [])
        if self.op == "insert":
            if self.tabela in self.banco.falha_insert:
                raise Exception("insert falhou")
            linhas.append(dict(self.payload))
            return _Resp([self.payload])
        alvo = [r for r in linhas if all(f(r) for f in self.filtros)]
        if self.op == "update":
            for r in alvo:
                r.update(self.payload)
            return _Resp([dict(r) for r in alvo])
        for col in self.banco.colunas_ausentes.get(self.tabela, ()):
            if col in self.cols:
                raise Exception(f"column {self.tabela}.{col} does not exist")
        if self._range is not None:
            alvo = alvo[self._range[0]:self._range[1] + 1]
        if self._limit is not None:
            alvo = alvo[:self._limit]
        return _Resp([dict(r) for r in alvo])


class _Banco:
    def __init__(self, **tabelas):
        self.tabelas = tabelas
        self.ausentes: set[str] = set()
        self.colunas_ausentes: dict[str, list[str]] = {}
        self.falha_insert: set[str] = set()

    def table(self, nome):
        return _Query(self, nome)


@pytest.fixture(autouse=True)
def _flags_de_coluna(monkeypatch):
    """As flags de coluna são de processo: um teste que as desliga não vaza para o próximo."""
    monkeypatch.setattr(tr._MetaAdCol, "enabled", True)


# --- 2.1 Funil cumulativo + canceladas fora ----------------------------------------------

def _g(i, **kw):
    lead = {"id": f"l{i}", "gclid": f"g{i}", "utm_campaign": "black",
            "created_at": "2026-09-01T12:00:00+00:00"}
    lead.update(kw)
    return lead


def test_funil_cumulativo_cenario_da_call():
    # 30 leads, 20 conversaram, 4 chegaram ao closer, 10 compraram — 6 deles sem deal nem
    # conversa (pedido do Bling de quem já era cliente). Era o "4 closer e 10 clientes".
    leads = [_g(i) for i in range(30)]
    conversa = {f"l{i}" for i in range(20)}
    closer = {f"l{i}" for i in range(4)}
    vendas = {f"l{i}": {"count": 1, "value": 60.0} for i in [*range(4), *range(20, 26)]}
    report = tr.build_campaign_report(leads, conversa, closer, vendas, "lead", "30d")
    total = report["total"]
    assert total["leads"] == 30
    assert total["conversas"] == 26  # 20 que conversaram + 6 clientes que entraram comprando
    assert total["closer"] == 10
    assert total["clientes"] == 10
    s = tr.build_report_summary(report, leads, vendas)
    assert s["funnel"]["entraram_ja_clientes"] == 6
    assert s["funnel"]["taxa_cliente"] == 1.0


def test_funil_cumulativo_closer_conta_como_conversa():
    report = tr.build_campaign_report([_g(1)], set(), {"l1"}, {}, "lead", "30d")
    assert (report["total"]["conversas"], report["total"]["closer"]) == (1, 1)
    assert report["entraram_ja_clientes"] == 0


def test_relatorio_vazio_tem_entraram_ja_clientes_zero():
    assert tr._empty_report("lead", "30d")["summary"]["funnel"]["entraram_ja_clientes"] == 0


def test_sales_by_lead_ignora_venda_cancelada(monkeypatch):
    rows = [
        {"lead_id": "a", "value": 60, "sold_at": "2026-09-10T10:00:00+00:00", "status": "registrada"},
        {"lead_id": "a", "value": 60, "sold_at": "2026-09-10T10:00:15+00:00", "status": "cancelada"},
        {"lead_id": "b", "value": 90, "sold_at": "2026-09-11T10:00:00+00:00", "status": "cancelada"},
        {"lead_id": "c", "value": 30, "sold_at": "2026-09-12T10:00:00+00:00", "status": None},
    ]
    monkeypatch.setattr(tr, "_fetch_all", lambda build, page=1000: rows)
    out = tr._sales_by_lead(None, ["a", "b", "c"], None, None, "lead")
    assert out["a"]["count"] == 1 and out["a"]["value"] == 60.0
    assert "b" not in out
    assert out["c"]["count"] == 1


def test_traffic_report_venda_cancelada_nao_vira_cliente(monkeypatch):
    banco = _Banco(
        leads=[_g(1)],
        sales=[{"lead_id": "l1", "value": 60.0, "sold_at": "2026-09-02T12:00:00+00:00",
                "status": "cancelada"}],
    )
    monkeypatch.setattr(tr, "get_supabase", lambda: banco)
    out = tr.traffic_report(period="all", mode="lead")
    assert out["total"]["leads"] == 1
    assert out["total"]["clientes"] == 0 and out["total"]["receita"] == 0.0


def test_modo_venda_nao_traz_lead_so_com_venda_cancelada(monkeypatch):
    banco = _Banco(
        leads=[_g(1), _g(2)],
        sales=[
            {"lead_id": "l1", "value": 60.0, "sold_at": "2026-09-02T12:00:00+00:00", "status": "cancelada"},
            {"lead_id": "l2", "value": 80.0, "sold_at": "2026-09-02T12:00:00+00:00", "status": "registrada"},
        ],
    )
    monkeypatch.setattr(tr, "get_supabase", lambda: banco)
    out = tr.traffic_report(period="all", mode="sale")
    assert out["total"]["leads"] == 1 and out["total"]["receita"] == 80.0
```

- [ ] **Step 2: Run to verify fail** — PYTEST com `tests/test_cs_p2_trafego.py`.
  Expected: FAIL (`conversas == 20 != 26`, `KeyError: 'entraram_ja_clientes'`, cancelada contada).

- [ ] **Step 3: Implement** em `traffic_report.py`.

  3a. Logo após `_s` (linha ~97), adicionar:

```python
def _cancelada(sale: dict[str, Any]) -> bool:
    """Venda cancelada não é venda: não conta cliente, pedido, receita nem compra."""
    return _s(sale.get("status")).lower() == "cancelada"
```

  3b. Em `build_campaign_report`, acrescentar à docstring (antes de "Invariante"):

```
    Funil CUMULATIVO (call de 01/10): quem comprou passou pelo closer, e quem chegou ao closer
    conversou — cliente ⊂ closer ⊂ conversa. Antes eram conjuntos independentes, e o pedido do
    Bling de quem já era cliente (lead criado já com venda, sem conversa nem deal) aparecia como
    "4 closer e 10 clientes". `entraram_ja_clientes` guarda quantos clientes NÃO eram closer pelo
    critério antigo: o que o Arthur percebeu continua visível em vez de sumir na soma.
```

  Antes do `for lead in leads:` inicializar `entraram_ja_clientes = 0`, e trocar o trecho de
  contagem (`row["leads"] += 1` até o fim do `if sale:`) por:

```python
        row["leads"] += 1
        sale = sales_by_lead.get(lead_id)
        cliente = bool(sale)
        closer = cliente or lead_id in closer_ids
        if closer or lead_id in conversed_ids:
            row["conversas"] += 1
        if closer:
            row["closer"] += 1
        if cliente:
            row["clientes"] += 1  # leads distintos que compraram (base da conversão)
            row["pedidos"] += int(sale.get("count", 0) or 0)  # nº de vendas (recompra: pode ser >1)
            row["receita"] += float(sale.get("value", 0.0) or 0.0)
            if lead_id not in closer_ids:
                entraram_ja_clientes += 1
```

  No `return` final, acrescentar `"entraram_ja_clientes": entraram_ja_clientes`.

  3c. Em `build_report_summary`, trocar a linha do `funnel` por:

```python
    funnel = {**counts, **rates, "gargalo": min(candidates)[2] if candidates else None,
              "entraram_ja_clientes": int(report.get("entraram_ja_clientes", 0) or 0)}
```

  3d. `_sales_by_lead`: select `"lead_id, value, sold_at, status"` e, no laço, logo após
  `lid = r.get("lead_id")`: `if not lid or _cancelada(r): continue` (substitui o `if not lid`).

  3e. `_fetch_leads` modo venda: `sb.table("sales").select("lead_id, status")` e
  `sale_ids = sorted({r["lead_id"] for r in _fetch_all(_sales_q) if r.get("lead_id") and not _cancelada(r)})`.

  3f. `campaign_detail`, série diária: `select("value, sold_at, status")` e
  `sales_rows.extend(r for r in _fetch_all(_sq) if not _cancelada(r))`.

  3g. `backend/tests/test_traffic_report.py::test_build_metrics_clientes_pedidos_receita`:
  `assert row["conversas"] == 1` → `assert row["conversas"] == 2  # funil cumulativo: closer conversou (call 01/10)`.

- [ ] **Step 4: Run** — PYTEST com `tests/test_cs_p2_trafego.py tests/test_traffic_report.py tests/test_traffic_report_summary.py tests/test_traffic_report_fuso_e_meta_ad_id.py`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/traffic_report.py backend/tests/test_cs_p2_trafego.py backend/tests/test_traffic_report.py
git commit -m "fix(trafego): funil cumulativo e venda cancelada fora do relatório"
```

---

### Task 2: Atribuição manual vence meta_ad_id/UTMs (spec P2.2)

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py`
- Test: `backend/tests/test_cs_p2_trafego.py`

- [ ] **Step 1: Write the failing tests** — no fixture `_flags_de_coluna` acrescentar
  `monkeypatch.setattr(tr._P0Col, "enabled", True)` e, no fim do arquivo:

```python
# --- 2.2 Atribuição manual ---------------------------------------------------------------

_META = [{"campaign_id": "cm_atac", "campaign_name": "Atacado WA", "cost": 500.0},
         {"campaign_id": "cm_terc", "campaign_name": "Terceirização WA", "cost": 300.0}]
_GOOGLE = [{"campaign_id": "cg_pmax", "campaign_name": "PMAX | Atacado", "cost": 200.0}]


def _manual(canal, cid, nome):
    return {"campanha_manual_canal": canal, "campanha_manual_id": cid, "campanha_manual_nome": nome}


def test_atribuicao_manual_vence_meta_ad_id():
    lead = {"id": "a", "ctwa_clid": "x", "meta_ad_id": "ad1", **_manual("meta", "cm_terc", "Terceirização WA")}
    rep = tr.build_campaign_report([lead], set(), set(), {}, "lead", "30d",
                                   spend_by_channel={"Meta Ads": _META},
                                   campaign_id_by_lead={"a": "cm_atac"})
    rows = {r["campaign"]: r for r in rep["rows"]}
    assert rows["Terceirização WA"]["leads"] == 1
    assert rows["Atacado WA"]["leads"] == 0


def test_atribuicao_manual_troca_o_canal():
    lead = {"id": "a", "utm_source": "instagram", **_manual("google", "cg_pmax", "PMAX | Atacado")}
    rep = tr.build_campaign_report([lead], set(), set(), {}, "lead", "30d",
                                   spend_by_channel={"Google Ads": _GOOGLE})
    row = next(r for r in rep["rows"] if r["leads"])
    assert (row["channel"], row["campaign"], row["investimento"]) == ("Google Ads", "PMAX | Atacado", 200.0)
    assert "Orgânico" not in rep["channel_subtotals"]


def test_atribuicao_manual_campanha_sem_gasto_na_janela_usa_nome_gravado():
    lead = {"id": "a", **_manual("meta", "cm_velha", "Campanha de julho")}
    rep = tr.build_campaign_report([lead], set(), set(), {}, "lead", "30d",
                                   spend_by_channel={"Meta Ads": _META})
    row = next(r for r in rep["rows"] if r["leads"])
    assert (row["channel"], row["campaign"], row["investimento"]) == ("Meta Ads", "Campanha de julho", 0.0)


def test_atribuicao_manual_com_canal_invalido_e_ignorada():
    lead = {"id": "a", "gclid": "g", "utm_campaign": "black", **_manual("tiktok", "x", "X")}
    assert tr.manual_attribution(lead) is None
    assert tr.lead_channel(lead) == "Google Ads"


def test_drilldown_respeita_atribuicao_manual():
    campaigns = tr._index_campaigns(_META)
    manual = {"id": "m", "utm_source": "instagram", **_manual("meta", "cm_terc", "Terceirização WA")}
    auto = {"id": "x", "ctwa_clid": "c", "meta_ad_id": "ad"}
    sel = tr.select_campaign_leads([manual, auto], "Meta Ads", "Terceirização WA", campaigns, {"x": "cm_terc"})
    assert [l["id"] for l in sel] == ["m", "x"]
    # o anúncio do lead manual aponta para outra campanha: a resposta do admin vence
    assert tr.select_campaign_leads([manual], "Meta Ads", "Atacado WA", campaigns, {"m": "cm_atac"}) == []


def test_drilldown_manual_em_campanha_sem_gasto():
    manual = {"id": "m", **_manual("meta", "cm_velha", "Campanha de julho")}
    assert [l["id"] for l in tr.select_campaign_leads(
        [manual], "Meta Ads", "Campanha de julho", tr._index_campaigns(_META), {})] == ["m"]
    assert [l["id"] for l in tr.select_campaign_leads(
        [manual], "Meta Ads", "Campanha de julho", {}, {})] == ["m"]


def test_fetch_leads_degrada_sem_colunas_do_p0():
    banco = _Banco(leads=[_g(1)])
    banco.colunas_ausentes = {"leads": ["campanha_manual_canal"]}
    out = tr._fetch_leads(banco, "lead", None, None)
    assert [l["id"] for l in out] == ["l1"]
    assert tr._P0Col.enabled is False
    assert tr._MetaAdCol.enabled is True  # o erro era só das colunas do P0


def test_fetch_leads_erro_generico_nao_desliga_p0():
    banco = _Banco(leads=[_g(1)])
    banco.ausentes = {"leads"}
    with pytest.raises(Exception):
        tr._fetch_leads(banco, "lead", None, None)
    assert tr._P0Col.enabled is True
```

- [ ] **Step 2: Run to verify fail** — PYTEST `tests/test_cs_p2_trafego.py`. Expected: FAIL
  (`AttributeError: _P0Col`, `manual_attribution`, `lead_channel`).

- [ ] **Step 3: Implement** em `traffic_report.py`.

  3a. Logo depois de `derive_channel`:

```python
# Atribuição manual (P0: leads.campanha_manual_*). Um admin diz no /trafego de qual campanha o
# lead veio quando o rastreio não diz — e essa resposta vence meta_ad_id, UTMs e tokens.
_MANUAL_CHANNEL = {"meta": "Meta Ads", "google": "Google Ads"}


def manual_attribution(lead: dict[str, Any]) -> tuple[str, str, str] | None:
    """(canal do relatório, campaign_id, nome) da atribuição manual, ou None."""
    channel = _MANUAL_CHANNEL.get(_s(lead.get("campanha_manual_canal")).lower())
    cid = _s(lead.get("campanha_manual_id"))
    if not channel or not cid:
        return None
    return channel, cid, _s(lead.get("campanha_manual_nome")) or cid


def lead_channel(lead: dict[str, Any]) -> str:
    """Canal do lead no relatório: a atribuição manual vence o rastreio (derive_channel)."""
    manual = manual_attribution(lead)
    return manual[0] if manual else derive_channel(lead)
```

  3b. No laço de `build_campaign_report`, trocar do `channel = derive_channel(lead)` até a
  montagem de `key`/`label` por:

```python
        manual = manual_attribution(lead)
        channel = manual[0] if manual else derive_channel(lead)
        raw_campaign = _s(lead.get("utm_campaign"))
        campaigns = campaigns_by_channel.get(channel)
        cid = None
        label = None
        if manual:
            # A resposta do admin vence anúncio e UTM. Campanha sem gasto na janela vira linha
            # própria com o nome gravado (investimento 0), sem se misturar com o "não atribuído".
            cid = manual[1]
            label = campaigns[cid]["name"] if campaigns and cid in campaigns else manual[2]
        elif campaigns:
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
            if label is None:
                label = campaigns[cid]["name"]
        elif campaigns:
```
  (o resto — ramo `elif campaigns:` do não atribuído e o `else` — fica igual.)

  3c. Colunas e degradação — trocar `_lead_cols` e `_fetch_leads` por:

```python
# Colunas do P0 (20261006_call_semanal_base.sql — migração manual). Até o Rafael aplicá-la, o
# PostgREST rejeita o select inteiro; o relatório degrada (perde só atribuição manual e "já
# era cliente") em vez de zerar.
_P0_LEAD_COLS = ("campanha_manual_canal, campanha_manual_id, campanha_manual_nome, "
                 "ja_era_cliente, ja_era_cliente_fonte")
_P0_COL_MARKERS = ("campanha_manual", "ja_era_cliente")


class _P0Col:
    """Flag de processo: colunas do P0 existem? Desligada só quando o erro CITA uma delas —
    um erro de rede não pode desligar a atribuição manual até o próximo deploy."""
    enabled = True


def _lead_cols() -> str:
    cols = _LEAD_COLS + ", meta_ad_id" if _MetaAdCol.enabled else _LEAD_COLS
    return cols + ", " + _P0_LEAD_COLS if _P0Col.enabled else cols


def _select_leads(fetch) -> list[dict[str, Any]]:
    """Roda `fetch(cols)` degradando as colunas de migration ainda não aplicada."""
    try:
        return fetch(_lead_cols())
    except Exception as exc:
        if _P0Col.enabled and any(m in str(exc) for m in _P0_COL_MARKERS):
            logger.warning("traffic_report: colunas do P0 ausentes (%s) - migration 20261006 pendente?", exc)
            _P0Col.enabled = False
            return _select_leads(fetch)
        if _MetaAdCol.enabled:
            logger.warning("traffic_report: select com meta_ad_id falhou (%s) - migration pendente?", exc)
            _MetaAdCol.enabled = False
            return _select_leads(fetch)
        raise


def _fetch_leads(sb, mode: str, lo: str | None, hi: str | None) -> list[dict[str, Any]]:
    if mode == "sale":
        def _sales_q():
            q = sb.table("sales").select("lead_id, status")
            if lo:
                q = q.gte("sold_at", lo)
            if hi:
                q = q.lte("sold_at", hi)
            return q
        sale_ids = sorted({r["lead_id"] for r in _fetch_all(_sales_q)
                           if r.get("lead_id") and not _cancelada(r)})

        def _por_venda(cols):
            leads: list[dict[str, Any]] = []
            for chunk in _chunks(sale_ids):
                leads.extend(_fetch_all(lambda c=chunk: sb.table("leads").select(cols).in_("id", c)))
            return leads
        return _select_leads(_por_venda)

    def _por_janela(cols):
        def _q():
            q = sb.table("leads").select(cols)
            if lo:
                q = q.gte("created_at", lo)
            if hi:
                q = q.lte("created_at", hi)
            return q
        return _fetch_all(_q)
    return _select_leads(_por_janela)
```

  3d. `select_campaign_leads` — substituir o corpo inteiro (mantendo a docstring e
  acrescentando "A atribuição manual vence, como em build_campaign_report."):

```python
    campaigns = campaigns or {}
    campaign_id_by_lead = campaign_id_by_lead or {}
    in_channel = [l for l in leads if lead_channel(l) == channel]

    def _manual_label(l):
        _, cid, nome = manual_attribution(l)
        return campaigns[cid]["name"] if cid in campaigns else nome

    auto = [l for l in in_channel if manual_attribution(l) is None]
    auto_ids = {id(l) for l in _select_auto(auto, campaign, campaigns, campaign_id_by_lead)}
    return [l for l in in_channel
            if (_manual_label(l) == campaign if manual_attribution(l) else id(l) in auto_ids)]


def _select_auto(in_channel, campaign, campaigns, campaign_id_by_lead):
    """Leads SEM atribuição manual de uma linha — o casamento por anúncio/UTM de sempre."""
    if not campaigns:  # canal nao pago: a linha e o proprio utm_campaign
        return [l for l in in_channel if (_s(l.get("utm_campaign")) or _NO_CAMPAIGN) == campaign]

    def _resolve(l):
        cid = campaign_id_by_lead.get(l.get("id"))
        if cid and cid in campaigns:
            return cid
        return resolve_campaign_id(_s(l.get("utm_campaign")), _s(l.get("utm_medium")), campaigns)

    if campaign.startswith(_UNATTRIBUTED):
        # "(nao atribuido) - slug" ou "(nao atribuido)" puro: sobras daquele slug.
        sufixo = campaign[len(_UNATTRIBUTED):].lstrip(" ·").strip().lower()
        return [l for l in in_channel
                if _resolve(l) is None and _s(l.get("utm_campaign")).lower() == sufixo]

    target = next((cid for cid, c in campaigns.items() if c["name"] == campaign), None)
    if target is None:
        # Linha antiga/rotulo desconhecido: cai no comportamento legado por utm_campaign.
        return [l for l in in_channel if (_s(l.get("utm_campaign")) or _NO_CAMPAIGN) == campaign]
    return [l for l in in_channel if _resolve(l) == target]
```

- [ ] **Step 4: Run** — PYTEST com os 4 arquivos `test_traffic_report*.py` + `tests/test_cs_p2_trafego.py`. Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(trafego): atribuição manual de campanha vence anúncio e UTM"`.

---

### Task 3: Endpoints de atribuição + proxies Next (spec P2.3)

**Files:**
- Create: `backend/app/campaigns/traffic_attribution.py`
- Modify: `backend/app/campaigns/traffic_router.py`
- Create: `frontend/src/app/api/traffic/campanhas/route.ts`
- Create: `frontend/src/app/api/traffic/leads/[id]/campanha/route.ts`
- Test: `backend/tests/test_cs_p2_trafego.py`

- [ ] **Step 1: Write the failing tests** (fim do arquivo):

```python
# --- 2.3 Endpoints de atribuição ---------------------------------------------------------

from datetime import date, datetime, timedelta, timezone  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.campaigns.traffic_attribution as ta  # noqa: E402
import app.campaigns.traffic_router as rotas  # noqa: E402

LEAD = "6f1c2b9e-1111-4222-8333-944455556666"
ADMIN = "rafael@cafecanastra.com"


@pytest.fixture
def banco_attr(monkeypatch):
    b = _Banco(
        leads=[{"id": LEAD, "campanha_manual_canal": None, "campanha_manual_id": None,
                "campanha_manual_nome": None}],
        lead_events=[], ad_spend=[],
    )
    monkeypatch.setattr(ta, "get_supabase", lambda: b)
    monkeypatch.setattr(ta, "_agora", lambda: datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc))
    return b


def _app(admin=True):
    app = FastAPI()
    app.include_router(rotas.router)
    if admin:
        app.dependency_overrides[rotas.exigir_admin] = lambda: ADMIN
    return TestClient(app)


def test_patch_atribui_campanha_e_grava_evento(banco_attr):
    r = _app().patch(f"/api/traffic/leads/{LEAD}/campanha",
                     json={"canal": "meta", "campanha_id": "cm_terc", "campanha_nome": "Terceirização WA"})
    assert r.status_code == 200
    assert r.json()["atribuicao_manual"] is True
    lead = banco_attr.tabelas["leads"][0]
    assert (lead["campanha_manual_canal"], lead["campanha_manual_id"], lead["campanha_manual_nome"]) == \
        ("meta", "cm_terc", "Terceirização WA")
    assert lead["campanha_manual_por"] == ADMIN
    assert lead["campanha_manual_em"] == "2026-10-06T15:00:00+00:00"
    [ev] = banco_attr.tabelas["lead_events"]
    assert (ev["lead_id"], ev["event_type"], ev["source"]) == (LEAD, "atribuicao_manual", "crm")
    assert (ev["old_value"], ev["new_value"]) == (None, "meta:cm_terc")
    assert ev["occurred_at"] == "2026-10-06T15:00:00+00:00"
    assert ev["metadata"]["campanha_nome"] == "Terceirização WA" and ev["metadata"]["por"] == ADMIN


def test_patch_remover_limpa_e_registra(banco_attr):
    banco_attr.tabelas["leads"][0].update(campanha_manual_canal="google", campanha_manual_id="cg_pmax",
                                          campanha_manual_nome="PMAX | Atacado")
    r = _app().patch(f"/api/traffic/leads/{LEAD}/campanha", json={"remover": True})
    assert r.status_code == 200 and r.json()["atribuicao_manual"] is False
    lead = banco_attr.tabelas["leads"][0]
    assert lead["campanha_manual_canal"] is None and lead["campanha_manual_id"] is None
    assert lead["campanha_manual_por"] == ADMIN
    [ev] = banco_attr.tabelas["lead_events"]
    assert (ev["old_value"], ev["new_value"]) == ("google:cg_pmax", None)
    assert ev["metadata"]["remover"] is True


@pytest.mark.parametrize("corpo", [{"canal": "tiktok", "campanha_id": "x"}, {"canal": "meta"}])
def test_patch_invalido_e_422_sem_gravar(banco_attr, corpo):
    r = _app().patch(f"/api/traffic/leads/{LEAD}/campanha", json=corpo)
    assert r.status_code == 422
    assert banco_attr.tabelas["leads"][0]["campanha_manual_canal"] is None
    assert banco_attr.tabelas["lead_events"] == []


def test_patch_lead_inexistente_404(banco_attr):
    r = _app().patch("/api/traffic/leads/00000000-0000-4000-8000-000000000000/campanha",
                     json={"canal": "meta", "campanha_id": "cm_terc"})
    assert r.status_code == 404


def test_patch_lead_id_que_nao_e_uuid_422(banco_attr):
    r = _app().patch("/api/traffic/leads/nao-e-uuid/campanha", json={"remover": True})
    assert r.status_code == 422


def test_patch_falha_no_evento_nao_desfaz_atribuicao(banco_attr):
    banco_attr.falha_insert = {"lead_events"}
    r = _app().patch(f"/api/traffic/leads/{LEAD}/campanha", json={"canal": "meta", "campanha_id": "cm_terc"})
    assert r.status_code == 200
    assert banco_attr.tabelas["leads"][0]["campanha_manual_id"] == "cm_terc"
    assert banco_attr.tabelas["leads"][0]["campanha_manual_nome"] == "cm_terc"  # sem nome: o id


def test_rotas_novas_exigem_admin(banco_attr):
    cliente = _app(admin=False)
    assert cliente.patch(f"/api/traffic/leads/{LEAD}/campanha", json={"remover": True}).status_code == 401
    assert cliente.get("/api/traffic/campanhas").status_code == 401


def test_campanhas_com_gasto_nos_ultimos_120_dias(banco_attr):
    hoje = datetime.now(tr._TZ).date()
    d = lambda n: (hoje - timedelta(days=n)).isoformat()  # noqa: E731
    banco_attr.tabelas["ad_spend"] = [
        {"platform": "google", "campaign_id": "cg_pmax", "campaign_name": "PMAX | Atacado", "cost": 100.0, "date": d(5)},
        {"platform": "meta", "campaign_id": "cm_atac", "campaign_name": "Atacado WA (antigo)", "cost": 50.0, "date": d(30)},
        {"platform": "meta", "campaign_id": "cm_atac", "campaign_name": "Atacado WA", "cost": 250.0, "date": d(3)},
        {"platform": "meta", "campaign_id": "cm_terc", "campaign_name": "Terceirização WA", "cost": 400.0, "date": d(10)},
        {"platform": "meta", "campaign_id": "cm_velha", "campaign_name": "Julho", "cost": 900.0, "date": d(200)},
        {"platform": "meta", "campaign_id": "cm_zero", "campaign_name": "Pausada", "cost": 0, "date": d(2)},
    ]
    r = _app().get("/api/traffic/campanhas")
    assert r.status_code == 200
    camps = r.json()["campanhas"]
    assert [(c["canal"], c["campanha_id"]) for c in camps] == \
        [("meta", "cm_terc"), ("meta", "cm_atac"), ("google", "cg_pmax")]
    atac = camps[1]
    assert atac["campanha_nome"] == "Atacado WA" and atac["investimento"] == 300.0
```

- [ ] **Step 2: Run to verify fail** — Expected: `ModuleNotFoundError: app.campaigns.traffic_attribution`.

- [ ] **Step 3: Implement.** Criar `backend/app/campaigns/traffic_attribution.py`:

```python
"""Atribuição manual de campanha no /trafego (spec 2026-10-06, P2.2–P2.4).

O webhook do CTWA só passou a gravar o anúncio (meta_ad_id) em 21/08/2026, e há lead que chega
por caminho que o rastreio não vê. Um admin diz à mão de qual campanha o lead veio; o relatório
(traffic_report.manual_attribution) dá prioridade a essa resposta sobre anúncio e UTMs.

Contrato (migração 20261006_call_semanal_base.sql, P0): leads.campanha_manual_canal
('meta'|'google'), campanha_manual_id, campanha_manual_nome, campanha_manual_por (e-mail),
campanha_manual_em; lead_events tipo 'atribuicao_manual', source 'crm'.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.campaigns.traffic_report import _TZ, _fetch_all, _s
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

CANAIS = ("meta", "google")
JANELA_CAMPANHAS_DIAS = 120


class AtribuicaoInvalida(ValueError):
    """O corpo não descreve uma atribuição válida (vira 422)."""


class LeadNaoEncontrado(LookupError):
    """lead_id inexistente (vira 404)."""


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def campanhas_com_gasto(hoje: date | None = None) -> list[dict[str, Any]]:
    """Campanhas com gasto (ad_spend) nos últimos 120 dias, para o select do painel.

    Uma linha por (canal, campaign_id), nome mais recente (campanha renomeada), ordenadas por
    canal (Meta antes de Google) e investimento decrescente. Gasto zero fica de fora."""
    sb = get_supabase()
    hoje = hoje or datetime.now(_TZ).date()
    desde = (hoje - timedelta(days=JANELA_CAMPANHAS_DIAS)).isoformat()
    linhas = _fetch_all(lambda: sb.table("ad_spend")
                        .select("platform, campaign_id, campaign_name, cost, date")
                        .gte("date", desde))
    agregado: dict[tuple[str, str], dict[str, Any]] = {}
    for r in linhas:
        canal = _s(r.get("platform")).lower()
        cid = str(r.get("campaign_id") or "").strip()
        nome = _s(r.get("campaign_name"))
        if canal not in CANAIS or not cid or not nome:
            continue
        slot = agregado.setdefault((canal, cid), {"canal": canal, "campanha_id": cid,
                                                  "campanha_nome": nome, "investimento": 0.0,
                                                  "_dia": ""})
        try:
            slot["investimento"] += float(r.get("cost") or 0.0)
        except (TypeError, ValueError):
            pass
        dia = str(r.get("date") or "")
        if dia >= slot["_dia"]:
            slot["_dia"], slot["campanha_nome"] = dia, nome
    out: list[dict[str, Any]] = []
    for c in agregado.values():
        c.pop("_dia")
        c["investimento"] = round(c["investimento"], 2)
        if c["investimento"] > 0:
            out.append(c)
    out.sort(key=lambda c: (CANAIS.index(c["canal"]), -c["investimento"], c["campanha_nome"].lower()))
    return out


def _rotulo(canal: Any, cid: Any) -> str | None:
    canal, cid = _s(canal), _s(cid)
    return f"{canal}:{cid}" if canal and cid else None


def atribuir_campanha(lead_id: str, *, canal: str | None = None, campanha_id: str | None = None,
                      campanha_nome: str | None = None, remover: bool = False,
                      por: str | None = None) -> dict[str, Any]:
    """Grava (ou remove) a atribuição manual do lead e registra o evento na linha do tempo."""
    if not remover:
        canal = _s(canal).lower()
        campanha_id = _s(campanha_id)
        if canal not in CANAIS:
            raise AtribuicaoInvalida("canal deve ser 'meta' ou 'google'")
        if not campanha_id:
            raise AtribuicaoInvalida("campanha_id é obrigatório")
        campanha_nome = _s(campanha_nome) or campanha_id
    sb = get_supabase()
    achados = (sb.table("leads")
               .select("id, campanha_manual_canal, campanha_manual_id, campanha_manual_nome")
               .eq("id", lead_id).limit(1).execute().data or [])
    if not achados:
        raise LeadNaoEncontrado(lead_id)
    antes = achados[0]
    em = _agora().isoformat()
    por = _s(por) or None
    if remover:
        patch: dict[str, Any] = {"campanha_manual_canal": None, "campanha_manual_id": None,
                                 "campanha_manual_nome": None}
    else:
        patch = {"campanha_manual_canal": canal, "campanha_manual_id": campanha_id,
                 "campanha_manual_nome": campanha_nome}
    # por/em também na remoção: fica o rastro de quem desfez.
    patch.update({"campanha_manual_por": por, "campanha_manual_em": em})
    sb.table("leads").update(patch).eq("id", lead_id).execute()
    _registrar_evento(sb, lead_id, antes, patch, remover, por, em)
    return {"lead_id": lead_id, "atribuicao_manual": not remover, **patch}


def _registrar_evento(sb, lead_id: str, antes: dict[str, Any], patch: dict[str, Any],
                      remover: bool, por: str | None, em: str) -> None:
    """lead_events `atribuicao_manual` (a linha do tempo do P3 lê daqui).

    Fail-soft: a atribuição já foi gravada e é ela que o relatório usa; perder o evento só
    empobrece a linha do tempo, então loga e segue em vez de devolver erro ao admin."""
    evento = {
        "lead_id": lead_id,
        "event_type": "atribuicao_manual",
        "old_value": _rotulo(antes.get("campanha_manual_canal"), antes.get("campanha_manual_id")),
        "new_value": _rotulo(patch["campanha_manual_canal"], patch["campanha_manual_id"]),
        "metadata": {
            "canal": patch["campanha_manual_canal"],
            "campanha_id": patch["campanha_manual_id"],
            "campanha_nome": patch["campanha_manual_nome"],
            "remover": remover,
            "por": por,
            "anterior": {"canal": antes.get("campanha_manual_canal"),
                         "campanha_id": antes.get("campanha_manual_id"),
                         "campanha_nome": antes.get("campanha_manual_nome")},
        },
        "source": "crm",
        "occurred_at": em,
    }
    try:
        sb.table("lead_events").insert(evento).execute()
    except Exception as exc:
        logger.error("atribuicao_manual: evento do lead %s não gravado: %s", lead_id, exc)
```

  Em `traffic_router.py`: atualizar a docstring do módulo (as rotas de atribuição exigem JWT de
  admin) e acrescentar:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.auth.jwt import validate_token
from app.campaigns.traffic_attribution import (
    AtribuicaoInvalida, LeadNaoEncontrado, atribuir_campanha, campanhas_com_gasto,
)

_bearer = HTTPBearer(auto_error=False)


def exigir_admin(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """E-mail do admin logado, do JWT do Supabase que a proxy do Next repassa.

    As rotas de leitura antigas deste router seguem sem guarda (a proteção é a proxy). As de
    atribuição gravam em `leads`, e o backend é alcançável em api.canastrainteligencia.com —
    sem esta guarda qualquer requisição externa reescreveria a origem de um lead. Função de
    módulo (não `require_role(...)` inline) para o teste poder sobrepor a dependência."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Não autenticado")
    payload = validate_token(f"Bearer {credentials.credentials}")
    if (payload.get("app_metadata") or {}).get("role") != "admin":
        raise HTTPException(status_code=403, detail="Permissão insuficiente")
    return str(payload.get("email") or payload.get("sub") or "admin")


class CampanhaManualBody(BaseModel):
    canal: str | None = None
    campanha_id: str | None = None
    campanha_nome: str | None = None
    remover: bool = False


@router.get("/campanhas")
def traffic_campanhas_endpoint(_admin: str = Depends(exigir_admin)):
    """Campanhas com gasto nos últimos 120 dias (select da atribuição manual)."""
    return {"campanhas": campanhas_com_gasto()}


@router.patch("/leads/{lead_id}/campanha")
def traffic_lead_campanha_endpoint(lead_id: str, body: CampanhaManualBody,
                                   por: str = Depends(exigir_admin)):
    """Atribui (ou remove, com `remover: true`) a campanha de origem de um lead."""
    try:
        uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="lead_id inválido")
    try:
        return atribuir_campanha(lead_id, canal=body.canal, campanha_id=body.campanha_id,
                                 campanha_nome=body.campanha_nome, remover=body.remover, por=por)
    except AtribuicaoInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except LeadNaoEncontrado:
        raise HTTPException(status_code=404, detail="lead não encontrado")
```

  Proxies Next (repassam o Bearer via `adminProxy`, como o valeria-flow):

`frontend/src/app/api/traffic/campanhas/route.ts`:

```ts
// Proxy admin-only: campanhas com gasto nos últimos 120 dias (select da atribuição manual).
// Usa o adminProxy do valeria-flow porque o endpoint do backend exige o JWT de admin
// (traffic_router.exigir_admin) — ele grava/expõe dado e o backend é público.
import { adminProxy } from "@/app/api/valeria-flow/_shared";

export async function GET() {
  return adminProxy("/api/traffic/campanhas");
}
```

`frontend/src/app/api/traffic/leads/[id]/campanha/route.ts`:

```ts
// Proxy admin-only: atribui (ou remove) a campanha de origem de um lead no /trafego.
// O e-mail de quem atribuiu sai do JWT no backend, não do corpo — o cliente não escolhe o "por".
import type { NextRequest } from "next/server";
import { adminProxy } from "@/app/api/valeria-flow/_shared";

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.text();
  return adminProxy(`/api/traffic/leads/${encodeURIComponent(id)}/campanha`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
```

- [ ] **Step 4: Run** — PYTEST `tests/test_cs_p2_trafego.py tests/test_traffic_report.py`; eslint nos dois `route.ts`. Expected: PASS / sem erros.

- [ ] **Step 5: Commit** — `git commit -m "feat(trafego): endpoint de atribuição manual de campanha (admin)"`.

---

### Task 4: Colunas "Já era cliente / Compras / Primeira origem" (spec P2.3; mestre Task 2.4)

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py` (`campaign_leads`, novo `_primeira_origem`)
- Modify: `frontend/src/components/trafego/campaign-leads-table.tsx`
- Test: `backend/tests/test_cs_p2_trafego.py`, `frontend/src/components/trafego/campaign-leads-table.test.tsx`

- [ ] **Step 1: Write the failing tests.** Backend (fim do arquivo):

```python
# --- 2.4 Colunas novas na tabela de leads da campanha -------------------------------------

def _banco_colunas():
    return _Banco(
        leads=[
            _g(1, name="Iago", ja_era_cliente=True, ja_era_cliente_fonte="auto"),
            _g(2, name="Velho Hank", ja_era_cliente=None, ja_era_cliente_fonte=None),
        ],
        sales=[
            {"lead_id": "l1", "value": 60.0, "sold_at": "2026-01-10T12:00:00+00:00", "status": "registrada"},
            {"lead_id": "l1", "value": 60.0, "sold_at": "2026-09-02T12:00:00+00:00", "status": "cancelada"},
            {"lead_id": "l1", "value": 90.0, "sold_at": "2026-09-20T12:00:00+00:00", "status": None},
        ],
        lead_primeira_origem=[{"lead_id": "l1", "canal": "Meta Ads", "campanha_id": "cm_atac",
                               "campanha_nome": "Atacado WA", "occurred_at": "2026-07-01T12:00:00+00:00"}],
    )


def test_campaign_leads_traz_colunas_novas(monkeypatch):
    banco = _banco_colunas()
    monkeypatch.setattr(tr, "get_supabase", lambda: banco)
    out = {l["lead_id"]: l for l in tr.campaign_leads("Google Ads", "black", period="all")}
    a, b = out["l1"], out["l2"]
    assert (a["ja_era_cliente"], a["ja_era_cliente_fonte"]) == (True, "auto")
    assert a["compras"] == 2  # a cancelada não conta
    assert a["primeira_origem"]["campanha_nome"] == "Atacado WA"
    assert (a["canal"], a["atribuicao_manual"]) == ("Google Ads", False)
    assert b["ja_era_cliente"] is None and b["compras"] == 0 and b["primeira_origem"] is None


def test_compras_conta_todas_as_datas_no_modo_venda(monkeypatch):
    banco = _banco_colunas()
    monkeypatch.setattr(tr, "get_supabase", lambda: banco)
    [a] = tr.campaign_leads("Google Ads", "black", period="all", mode="sale",
                            date_from="2026-09-01", date_to="2026-09-30")
    assert a["valor"] == 90.0  # receita: só a venda da janela
    assert a["compras"] == 2   # compras: a vida inteira do lead


def test_campaign_leads_sem_view_primeira_origem_e_fail_soft(monkeypatch):
    banco = _banco_colunas()
    banco.ausentes = {"lead_primeira_origem"}
    monkeypatch.setattr(tr, "get_supabase", lambda: banco)
    out = tr.campaign_leads("Google Ads", "black", period="all")
    assert len(out) == 2 and all(l["primeira_origem"] is None for l in out)


def test_campaign_leads_marca_atribuicao_manual(monkeypatch):
    banco = _Banco(leads=[_g(1, name="Serginho", **_manual("meta", "cm_x", "Campanha X"))])
    monkeypatch.setattr(tr, "get_supabase", lambda: banco)
    [l] = tr.campaign_leads("Meta Ads", "Campanha X", period="all")
    assert l["atribuicao_manual"] is True and l["canal"] == "Meta Ads"
    assert (l["campanha_manual_canal"], l["campanha_manual_id"], l["campanha_manual_nome"]) == \
        ("meta", "cm_x", "Campanha X")
```

  Frontend — criar `frontend/src/components/trafego/campaign-leads-table.test.tsx`:

```tsx
/**
 * @vitest-environment jsdom
 *
 * Colunas da call de 01/10 (P2): "Já era cliente" (com selo auto), "Compras" e "Primeira
 * origem" (vazia → canal atual marcado "(atual)"), mais o selo "manual" no nome.
 * Sem jest-dom (não é dependência do projeto): asserções com a API crua do DOM.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import {
  CampaignLeadsTable, jaEraClienteTexto, primeiraOrigemTexto, type CampaignLead,
} from "./campaign-leads-table";

const base: CampaignLead = {
  lead_id: "x", name: "X", phone: null, created_at: "2026-09-01T12:00:00Z",
  utm_source: null, utm_medium: null, utm_campaign: null, traffic_type: null,
  conversou: false, stage: null, comprou: false, valor: 0, sold_at: null,
};

const LEADS: CampaignLead[] = [
  {
    ...base, lead_id: "a", name: "Iago", canal: "Google Ads", ja_era_cliente: true,
    ja_era_cliente_fonte: "auto", compras: 2,
    primeira_origem: { canal: "Meta Ads", campanha_id: "cm", campanha_nome: "Atacado WA", occurred_at: null },
  },
  { ...base, lead_id: "b", name: "Velho Hank", canal: "Google Ads", ja_era_cliente: null, compras: 0, primeira_origem: null },
  {
    ...base, lead_id: "c", name: "Serginho", canal: "Meta Ads", ja_era_cliente: false,
    ja_era_cliente_fonte: "vendedor", compras: 1, atribuicao_manual: true,
  },
];

const linha = (nome: string) => screen.getByText(nome).closest("tr") as HTMLElement;

afterEach(cleanup);

describe("helpers", () => {
  it("jaEraClienteTexto: Sim / Não / —", () => {
    expect([true, false, null, undefined].map(jaEraClienteTexto)).toEqual(["Sim", "Não", "—", "—"]);
  });
  it("primeiraOrigemTexto: origem registrada, senão canal atual", () => {
    expect(primeiraOrigemTexto(LEADS[0])).toEqual({ texto: "Meta Ads · Atacado WA", atual: false });
    expect(primeiraOrigemTexto(LEADS[1])).toEqual({ texto: "Google Ads", atual: true });
    expect(primeiraOrigemTexto({ canal: null, primeira_origem: null })).toEqual({ texto: "—", atual: false });
  });
});

describe("CampaignLeadsTable", () => {
  it("tem as colunas novas no cabeçalho", () => {
    render(<CampaignLeadsTable leads={LEADS} />);
    const cabecalho = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(cabecalho).toEqual(expect.arrayContaining(["Já era cliente", "Compras", "Primeira origem"]));
  });

  it("mostra Sim com selo auto, compras e primeira origem", () => {
    render(<CampaignLeadsTable leads={LEADS} />);
    const row = linha("Iago");
    expect(within(row).getByText("Sim")).toBeTruthy();
    expect(within(row).getByText("auto")).toBeTruthy();
    expect(within(row).getByText("2")).toBeTruthy();
    expect(within(row).getByText("Meta Ads · Atacado WA")).toBeTruthy();
  });

  it("sem primeira origem cai no canal atual com (atual), e desconhecido é —", () => {
    render(<CampaignLeadsTable leads={LEADS} />);
    const row = linha("Velho Hank");
    expect(within(row).getByText("Google Ads (atual)")).toBeTruthy();
    expect(within(row).queryByText("auto")).toBeNull();
  });

  it("resposta do vendedor não ganha selo auto; atribuição manual ganha selo manual", () => {
    render(<CampaignLeadsTable leads={LEADS} />);
    const row = linha("Serginho");
    expect(within(row).getByText("Não")).toBeTruthy();
    expect(within(row).queryByText("auto")).toBeNull();
    expect(within(row).getByText("manual")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run to verify fail** — PYTEST `tests/test_cs_p2_trafego.py` (KeyError `ja_era_cliente`) e VITEST `src/components/trafego/campaign-leads-table.test.tsx` (helpers não exportados).

- [ ] **Step 3: Implement.** Backend — antes de `_stage_info_map`:

```python
def _primeira_origem(sb, lead_ids: list[str]) -> dict[str, dict[str, Any]]:
    """lead_id -> primeira entrada registrada (view lead_primeira_origem do P0, enchida pelo P3).

    Fail-soft: sem a migração a view não existe e a coluna cai no canal atual na tela."""
    try:
        out: dict[str, dict[str, Any]] = {}
        for chunk in _chunks(lead_ids):
            rows = _fetch_all(lambda c=chunk: sb.table("lead_primeira_origem")
                              .select("lead_id, canal, campanha_id, campanha_nome, occurred_at")
                              .in_("lead_id", c))
            for r in rows:
                if r.get("lead_id"):
                    out[r["lead_id"]] = {k: r.get(k) for k in
                                         ("canal", "campanha_id", "campanha_nome", "occurred_at")}
        return out
    except Exception as exc:
        logger.warning("lead_primeira_origem indisponível (migration 20261006 pendente?): %s", exc)
        return {}
```

  Em `campaign_leads`, logo após `sales = _sales_by_lead(...)`:

```python
        # "Compras" é a vida inteira do lead; no modo venda `sales` vem recortado pela janela.
        compras = sales if mode != "sale" else _sales_by_lead(sb, lead_ids, None, None, "lead")
        origem = _primeira_origem(sb, lead_ids)
```

  e no `out.append({...})`, após `"sold_at": …`:

```python
                "canal": lead_channel(l),
                "atribuicao_manual": manual is not None,
                "campanha_manual_canal": _s(l.get("campanha_manual_canal")).lower() if manual else None,
                "campanha_manual_id": manual[1] if manual else None,
                "campanha_manual_nome": manual[2] if manual else None,
                "ja_era_cliente": l.get("ja_era_cliente"),
                "ja_era_cliente_fonte": l.get("ja_era_cliente_fonte"),
                "compras": int((compras.get(lid) or {}).get("count", 0) or 0),
                "primeira_origem": origem.get(lid),
```
  com `manual = manual_attribution(l)` declarado no início do laço.

  Frontend — `campaign-leads-table.tsx` (arquivo inteiro):

```tsx
"use client";
import { useState, type ReactNode } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { CampaignLeadPanel } from "@/components/trafego/campaign-lead-panel";
import { stageLabel } from "@/lib/lead-overview";

export type PrimeiraOrigem = {
  canal: string | null; campanha_id: string | null; campanha_nome: string | null; occurred_at: string | null;
};

export type CampaignLead = {
  lead_id: string; name: string | null; phone: string | null; created_at: string | null;
  utm_source: string | null; utm_medium: string | null; utm_campaign: string | null;
  traffic_type: string | null; conversou: boolean; stage: string | null;
  comprou: boolean; valor: number; sold_at: string | null;
  // Call de 01/10 (P2). Opcionais: backend anterior ao P2 não os manda.
  canal?: string | null;
  atribuicao_manual?: boolean;
  campanha_manual_canal?: "meta" | "google" | null;
  campanha_manual_id?: string | null;
  campanha_manual_nome?: string | null;
  ja_era_cliente?: boolean | null;
  ja_era_cliente_fonte?: "auto" | "vendedor" | null;
  compras?: number;
  primeira_origem?: PrimeiraOrigem | null;
};

const HEADERS = [
  "Lead", "Origem", "Fonte", "Meio", "Etapa", "Conversou",
  "Já era cliente", "Compras", "Primeira origem", "Entrada", "Venda",
];

const fmtBRL = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
const fmtDate = (v: string | null) => {
  if (!v) return "—";
  try { return new Date(v).toLocaleDateString("pt-BR"); } catch { return "—"; }
};

/** Sim / Não / —. O sistema nunca marca "não" sozinho (P0): "—" é "ninguém sabe ainda". */
export function jaEraClienteTexto(v: boolean | null | undefined): string {
  return v === true ? "Sim" : v === false ? "Não" : "—";
}

/** Primeira entrada da linha do tempo; sem ela, o canal atual marcado como "(atual)". */
export function primeiraOrigemTexto(
  l: Pick<CampaignLead, "primeira_origem" | "canal">,
): { texto: string; atual: boolean } {
  const o = l.primeira_origem;
  if (o && (o.canal || o.campanha_nome)) {
    return { texto: [o.canal, o.campanha_nome].filter(Boolean).join(" · "), atual: false };
  }
  return l.canal ? { texto: l.canal, atual: true } : { texto: "—", atual: false };
}

function Selo({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex items-center text-[10px] font-medium uppercase tracking-[0.4px] px-1.5 py-px rounded-[3px] border bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6] whitespace-nowrap"
    >
      {children}
    </span>
  );
}

function OriginBadge({ trafficType }: { trafficType: string | null }) {
  /* (sem mudança) */
}

export function CampaignLeadsTable({ leads }: { leads: CampaignLead[] }) {
  const [q, setQ] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const norm = (s: string) => s.toLowerCase();
  const filtered = q
    ? leads.filter(l => norm(`${l.name ?? ""} ${l.phone ?? ""}`).includes(norm(q)))
    : leads;
  const selected = leads.find(l => l.lead_id === selectedId) ?? null;
  // … cabeçalho/busca sem mudança; cabeçalho da tabela mapeia HEADERS; colSpan={HEADERS.length};
  // cada linha: onClick={() => setSelectedId(l.lead_id)},
  //   data-state={selectedId === l.lead_id ? "selected" : undefined}
  // célula do nome:
  //   <div className="flex items-center gap-1.5 min-w-0">
  //     <button … className="block min-w-0 truncate text-left …">{l.name || l.phone || l.lead_id}</button>
  //     {l.atribuicao_manual && <Selo title="Campanha atribuída à mão no /trafego">manual</Selo>}
  //   </div>
  // novas células, entre "Conversou" e "Entrada":
  //   <TableCell className="text-[13px] text-[#7b7b78] whitespace-nowrap">
  //     <span className="inline-flex items-center gap-1.5">
  //       <span>{jaEraClienteTexto(l.ja_era_cliente)}</span>
  //       {l.ja_era_cliente != null && l.ja_era_cliente_fonte === "auto" && (
  //         <Selo title="Marcado pelo sistema: há venda anterior à entrada do lead">auto</Selo>)}
  //     </span>
  //   </TableCell>
  //   <TableCell className="text-[13px] tabular-nums text-[#7b7b78]">{l.compras ?? "—"}</TableCell>
  //   <TableCell className={`text-[13px] whitespace-nowrap ${origem.atual ? "text-[#b5b1aa]" : "text-[#7b7b78]"}`}
  //     title={origem.atual ? "Sem entrada registrada na linha do tempo: canal atual" : undefined}>
  //     {origem.texto}{origem.atual ? " (atual)" : ""}
  //   </TableCell>
  // painel: <CampaignLeadPanel target={selected} onClose={() => setSelectedId(null)} />
}
```
  (O executor escreve o JSX completo seguindo o arquivo atual; as únicas mudanças são as
  listadas nos comentários. `origem = primeiraOrigemTexto(l)` no início do `map`.)

- [ ] **Step 4: Run** — PYTEST `tests/test_cs_p2_trafego.py` e VITEST `src/components/trafego/campaign-leads-table.test.tsx`; eslint no `.tsx`. Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(trafego): colunas já era cliente, compras e primeira origem"`.

---

### Task 5: UI de atribuição no painel do lead (spec P2.4 / Task 2.5)

**Files:**
- Create: `frontend/src/components/trafego/campaign-attribution.tsx`
- Modify: `frontend/src/components/trafego/campaign-lead-panel.tsx`, `campaign-leads-table.tsx`
- Test: `frontend/src/components/trafego/campaign-attribution.test.tsx`

- [ ] **Step 1: Write the failing test** `campaign-attribution.test.tsx`:

```tsx
/**
 * @vitest-environment jsdom
 *
 * Atribuição manual de campanha (call de 01/10, P2): select agrupado por canal, "Atribuir"
 * manda PATCH com canal/id/nome, "Remover atribuição" manda {remover: true}, erro do
 * backend aparece em texto. `<select>` nativo: o Radix Select não roda no jsdom.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CampaignAttribution, type AtribuicaoManual } from "./campaign-attribution";

const CAMPANHAS = [
  { canal: "meta", campanha_id: "m1", campanha_nome: "Atacado WA", investimento: 500 },
  { canal: "google", campanha_id: "g1", campanha_nome: "PMAX | Atacado", investimento: 300 },
];
const SEM: AtribuicaoManual = {
  atribuicao_manual: false, campanha_manual_canal: null, campanha_manual_id: null, campanha_manual_nome: null,
};
const COM: AtribuicaoManual = {
  atribuicao_manual: true, campanha_manual_canal: "google", campanha_manual_id: "g1", campanha_manual_nome: "PMAX | Atacado",
};

type Chamada = { url: string; init?: RequestInit };

function mockFetch(patch: { ok: boolean; body: unknown }) {
  const chamadas: Chamada[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    chamadas.push({ url, init });
    const data = url === "/api/traffic/campanhas" ? { campanhas: CAMPANHAS } : patch.body;
    const ok = url === "/api/traffic/campanhas" ? true : patch.ok;
    return { ok, status: ok ? 200 : 422, json: async () => data };
  }));
  return chamadas;
}

const patches = (c: Chamada[]) => c.filter((x) => x.init?.method === "PATCH");

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("CampaignAttribution", () => {
  it("agrupa as campanhas por canal", async () => {
    mockFetch({ ok: true, body: {} });
    const { container } = render(<CampaignAttribution leadId="L1" atual={SEM} />);
    await waitFor(() => expect(container.querySelectorAll("optgroup").length).toBe(2));
    const grupos = Array.from(container.querySelectorAll("optgroup")).map((g) => g.getAttribute("label"));
    expect(grupos).toEqual(["Meta Ads", "Google Ads"]);
  });

  it("atribui com PATCH e avisa o pai", async () => {
    const chamadas = mockFetch({ ok: true, body: {
      atribuicao_manual: true, campanha_manual_canal: "meta", campanha_manual_id: "m1", campanha_manual_nome: "Atacado WA",
    } });
    const onChange = vi.fn();
    const { container } = render(<CampaignAttribution leadId="L1" atual={SEM} onChange={onChange} />);
    await waitFor(() => expect(container.querySelectorAll("optgroup").length).toBe(2));
    fireEvent.change(screen.getByLabelText("Campanha"), { target: { value: "meta:m1" } });
    fireEvent.click(screen.getByRole("button", { name: "Atribuir" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const [p] = patches(chamadas);
    expect(p.url).toBe("/api/traffic/leads/L1/campanha");
    expect(JSON.parse(String(p.init?.body))).toEqual({ canal: "meta", campanha_id: "m1", campanha_nome: "Atacado WA" });
    expect(onChange.mock.calls[0][0]).toMatchObject({ atribuicao_manual: true, campanha_manual_id: "m1" });
  });

  it("mostra o selo manual e remove a atribuição", async () => {
    const chamadas = mockFetch({ ok: true, body: {
      atribuicao_manual: false, campanha_manual_canal: null, campanha_manual_id: null, campanha_manual_nome: null,
    } });
    const onChange = vi.fn();
    render(<CampaignAttribution leadId="L1" atual={COM} onChange={onChange} />);
    expect(screen.getByText("manual")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remover atribuição" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(JSON.parse(String(patches(chamadas)[0].init?.body))).toEqual({ remover: true });
    expect(onChange.mock.calls[0][0]).toMatchObject({ atribuicao_manual: false });
  });

  it("mostra o erro do backend", async () => {
    mockFetch({ ok: false, body: { detail: "canal deve ser 'meta' ou 'google'" } });
    const { container } = render(<CampaignAttribution leadId="L1" atual={SEM} />);
    await waitFor(() => expect(container.querySelectorAll("optgroup").length).toBe(2));
    fireEvent.change(screen.getByLabelText("Campanha"), { target: { value: "google:g1" } });
    fireEvent.click(screen.getByRole("button", { name: "Atribuir" }));
    expect(await screen.findByText("canal deve ser 'meta' ou 'google'")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run to verify fail** — VITEST: módulo `./campaign-attribution` não existe.

- [ ] **Step 3: Implement** `campaign-attribution.tsx`:

```tsx
"use client";

// Atribuição manual de campanha (call de 01/10, P2). Um admin diz de qual campanha o lead veio
// quando o rastreio não diz (lead CTWA de antes de 21/08, indicação, Google sem gclid) — e o
// /trafego passa a contá-lo lá, acima do anúncio e das UTMs. <select> nativo com <optgroup> por
// canal: o Radix Select não roda no jsdom e ~30 campanhas não pedem busca.

import { useEffect, useState } from "react";

export type CanalCampanha = "meta" | "google";

export type CampanhaComGasto = {
  canal: CanalCampanha;
  campanha_id: string;
  campanha_nome: string;
  investimento: number;
};

export type AtribuicaoManual = {
  atribuicao_manual: boolean;
  campanha_manual_canal: CanalCampanha | null;
  campanha_manual_id: string | null;
  campanha_manual_nome: string | null;
};

export const CANAL_LABEL: Record<CanalCampanha, string> = { meta: "Meta Ads", google: "Google Ads" };
const CANAIS: CanalCampanha[] = ["meta", "google"];

const valorDe = (canal: string | null, id: string | null) => (canal && id ? `${canal}:${id}` : "");

type Resposta = Partial<AtribuicaoManual> & { detail?: unknown };

export function CampaignAttribution({
  leadId,
  atual,
  onChange,
}: {
  leadId: string;
  atual: AtribuicaoManual;
  onChange?: (a: AtribuicaoManual) => void;
}) {
  const [campanhas, setCampanhas] = useState<CampanhaComGasto[] | null>(null);
  const [erroLista, setErroLista] = useState<string | null>(null);
  const [escolha, setEscolha] = useState(valorDe(atual.campanha_manual_canal, atual.campanha_manual_id));
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch("/api/traffic/campanhas", { signal: ctrl.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error("failed");
        return (await r.json()) as { campanhas?: CampanhaComGasto[] };
      })
      .then((d) => setCampanhas(d.campanhas ?? []))
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setErroLista("Não foi possível carregar as campanhas.");
      });
    return () => ctrl.abort();
  }, []);

  const salvar = async (body: Record<string, unknown>) => {
    setSalvando(true);
    setErro(null);
    try {
      const r = await fetch(`/api/traffic/leads/${leadId}/campanha`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = (await r.json().catch(() => ({}))) as Resposta;
      if (!r.ok) {
        throw new Error(typeof d.detail === "string" ? d.detail : "Não foi possível salvar a atribuição.");
      }
      const nova: AtribuicaoManual = {
        atribuicao_manual: Boolean(d.atribuicao_manual),
        campanha_manual_canal: d.campanha_manual_canal ?? null,
        campanha_manual_id: d.campanha_manual_id ?? null,
        campanha_manual_nome: d.campanha_manual_nome ?? null,
      };
      setEscolha(valorDe(nova.campanha_manual_canal, nova.campanha_manual_id));
      onChange?.(nova);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível salvar a atribuição.");
    } finally {
      setSalvando(false);
    }
  };

  const atribuir = () => {
    const c = campanhas?.find((x) => valorDe(x.canal, x.campanha_id) === escolha);
    if (c) void salvar({ canal: c.canal, campanha_id: c.campanha_id, campanha_nome: c.campanha_nome });
  };

  const valorAtual = valorDe(atual.campanha_manual_canal, atual.campanha_manual_id);
  const lista = campanhas ?? [];
  const grupos = CANAIS.map((canal) => ({ canal, itens: lista.filter((c) => c.canal === canal) }))
    .filter((g) => g.itens.length > 0);
  // Campanha atribuída que saiu da janela de 120 dias continua aparecendo no select.
  const atualForaDaLista =
    atual.atribuicao_manual && valorAtual !== "" && !lista.some((c) => valorDe(c.canal, c.campanha_id) === valorAtual);

  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <div className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Campanha de origem</div>
        {atual.atribuicao_manual && (
          <span className="inline-flex items-center text-[10px] font-medium uppercase tracking-[0.4px] px-1.5 py-px rounded-[3px] border bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]">
            manual
          </span>
        )}
      </div>

      {atual.atribuicao_manual && atual.campanha_manual_canal && (
        <div className="text-[13px] text-[#111111] mb-2.5">
          {CANAL_LABEL[atual.campanha_manual_canal]} · {atual.campanha_manual_nome ?? atual.campanha_manual_id}
        </div>
      )}

      {erroLista ? (
        <div className="text-[12px] text-[#c41c1c]">{erroLista}</div>
      ) : (
        <div className="flex items-center gap-2">
          <select
            aria-label="Campanha"
            value={escolha}
            onChange={(e) => setEscolha(e.target.value)}
            disabled={campanhas === null || salvando}
            className="flex-1 min-w-0 text-[13px] text-[#111111] bg-white border border-[#dedbd6] rounded-[4px] px-2 py-1.5 focus:outline-none focus-visible:ring-1 focus-visible:ring-[#111111]"
          >
            <option value="">{campanhas === null ? "Carregando campanhas…" : "Escolher campanha…"}</option>
            {atualForaDaLista && (
              <option value={valorAtual}>{atual.campanha_manual_nome ?? atual.campanha_manual_id}</option>
            )}
            {grupos.map((g) => (
              <optgroup key={g.canal} label={CANAL_LABEL[g.canal]}>
                {g.itens.map((c) => (
                  <option key={valorDe(c.canal, c.campanha_id)} value={valorDe(c.canal, c.campanha_id)}>
                    {c.campanha_nome}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <button
            type="button"
            onClick={atribuir}
            disabled={!escolha || escolha === valorAtual || salvando}
            className="text-[13px] text-white bg-[#111111] hover:bg-[#000000] disabled:opacity-40 px-3 py-1.5 rounded-[4px] transition-colors whitespace-nowrap"
          >
            Atribuir
          </button>
        </div>
      )}

      {atual.atribuicao_manual && (
        <button
          type="button"
          onClick={() => void salvar({ remover: true })}
          disabled={salvando}
          className="mt-2 text-[12px] text-[#7b7b78] hover:text-[#c41c1c] disabled:opacity-40 transition-colors"
        >
          Remover atribuição
        </button>
      )}

      {erro && <div className="mt-2 text-[12px] text-[#c41c1c]">{erro}</div>}

      <p className="mt-2 text-[11px] text-[#7b7b78] leading-snug">
        Vale acima do anúncio e das UTMs. O relatório recalcula ao recarregar a página.
      </p>
    </div>
  );
}
```

  `campaign-lead-panel.tsx`:
  - importar `import { CampaignAttribution, type AtribuicaoManual } from "@/components/trafego/campaign-attribution";`
  - `CampaignLeadPanelTarget` ganha os campos opcionais
    `atribuicao_manual?: boolean; campanha_manual_canal?: "meta" | "google" | null; campanha_manual_id?: string | null; campanha_manual_nome?: string | null;`
  - props ganham `onAttributionChange?: (leadId: string, a: AtribuicaoManual) => void`
  - primeira coisa dentro de `{/* ── Corpo ── */}`:

```tsx
          {leadId && (
            // key: trocar de lead recomeça o select do zero, sem herdar a escolha do anterior.
            <CampaignAttribution
              key={leadId}
              leadId={leadId}
              atual={{
                atribuicao_manual: Boolean(target?.atribuicao_manual),
                campanha_manual_canal: target?.campanha_manual_canal ?? null,
                campanha_manual_id: target?.campanha_manual_id ?? null,
                campanha_manual_nome: target?.campanha_manual_nome ?? null,
              }}
              onChange={(a) => onAttributionChange?.(leadId, a)}
            />
          )}
```

  `campaign-leads-table.tsx`: importar `type AtribuicaoManual`; estado
  `const [overrides, setOverrides] = useState<Record<string, Partial<CampaignLead>>>({});`,
  `const rows = leads.map(l => (overrides[l.lead_id] ? { ...l, ...overrides[l.lead_id] } : l));`
  (filtro e `selected` passam a usar `rows`), e o painel recebe
  `onAttributionChange={(id, a) => setOverrides(prev => ({ ...prev, [id]: { ...prev[id], ...a } }))}`.

- [ ] **Step 4: Run** — VITEST `campaign-attribution.test.tsx campaign-leads-table.test.tsx`; eslint nos 3 `.tsx`. Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(trafego): atribuir campanha pelo painel do lead"`.

---

### Task 6: Stat "Entraram já como cliente" no resumo (spec P2.1, parte de UI)

**Files:**
- Modify: `frontend/src/components/trafego/report-summary.tsx` (`FunnelBand`)
- Test: `frontend/src/components/trafego/report-summary.test.tsx`

- [ ] **Step 1: Write the failing test**:

```tsx
/**
 * @vitest-environment jsdom
 *
 * Funil cumulativo (call de 01/10): o resumo mostra "Entraram já como cliente" — os clientes que
 * não passaram pelo closer — em vez de esconder o que o Arthur percebeu.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ReportSummaryPanel, type FunnelComEntrada } from "./report-summary";
import type { ReportSummary } from "@/lib/traffic-summary";

const FUNNEL: FunnelComEntrada = {
  leads: 30, conversas: 26, closer: 10, clientes: 10,
  taxa_conversa: 0.8667, taxa_closer: 0.3846, taxa_cliente: 1, taxa_total: 0.3333,
  gargalo: "closer", entraram_ja_clientes: 6,
};
const summary = (funnel: FunnelComEntrada): ReportSummary => ({
  funnel,
  cost: { leads: 30, conversas: 26, closer: 10, clientes: 10, investimento: 0, receita: 0, roas: null,
          cpl: null, custo_conversa: null, custo_closer: null, cac: null },
  channels: [],
  timing_quality: { dias_ate_compra_mediana: null, amostra_dias: 0, pedidos_por_cliente: null,
                    recompra_pct: null, sem_rastreio_pct: null, nao_atribuido_pct: null },
});

afterEach(cleanup);

describe("ReportSummaryPanel — funil", () => {
  it("mostra quantos entraram já como cliente", () => {
    render(<ReportSummaryPanel summary={summary(FUNNEL)} mode="lead" />);
    expect(screen.getByText(/Entraram já como cliente/).textContent).toContain("6");
  });

  it("backend antigo (sem o campo) não mostra a linha", () => {
    const { entraram_ja_clientes: _, ...antigo } = FUNNEL;
    render(<ReportSummaryPanel summary={summary(antigo)} mode="lead" />);
    expect(screen.queryByText(/Entraram já como cliente/)).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify fail** — VITEST: `FunnelComEntrada` não exportado / texto ausente.

- [ ] **Step 3: Implement** em `report-summary.tsx`: importar `type SummaryFunnel` de
  `@/lib/traffic-summary` e exportar

```tsx
/** Campo do funil cumulativo (call de 01/10). Opcional: backend anterior não o manda. O tipo
 *  base mora em lib/traffic-summary.ts, fora do pacote P2 — por isso a extensão local. */
export type FunnelComEntrada = SummaryFunnel & { entraram_ja_clientes?: number };
```

  Em `FunnelBand`, `const entraram = (f as FunnelComEntrada).entraram_ja_clientes;` e trocar o
  `<p>` "Lead → cliente" do ramo `showRates` por:

```tsx
        <div className="flex flex-col gap-1 border-t border-[#dedbd6] pt-2">
          <p className="text-[12px] text-[#7b7b78]">
            Lead → cliente: <span className="text-[#111111] tabular-nums">{fmtPctOrDash(f.taxa_total)}</span>
          </p>
          {entraram != null && (
            <p
              className="text-[12px] text-[#7b7b78]"
              title="Clientes que compraram sem ter chegado ao closer — em geral pedido do Bling de quem já era cliente. O funil os conta em conversa e closer também."
            >
              Entraram já como cliente: <span className="text-[#111111] tabular-nums">{fmtInt(entraram)}</span>
            </p>
          )}
        </div>
```

- [ ] **Step 4: Run** — VITEST `report-summary.test.tsx` + `src/lib/traffic-summary.test.ts`; eslint. Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(trafego): resumo mostra quem entrou já como cliente"`.

---

### Task 7: Script `recuperar_meta_ad_id.py` (spec P2.5 / Task 2.6)

**Files:**
- Create: `scripts/trafego/recuperar_meta_ad_id.py`
- Test: `backend/tests/test_cs_p2_recuperar_meta_ad_id.py`

- [ ] **Step 1: Write the failing tests**:

```python
"""scripts/trafego/recuperar_meta_ad_id.py — casamento lead ↔ referral CTWA (P2.5).

Caso real: Serginho Sinop entrou em 20/08/2026, um dia antes de o webhook gravar o anúncio.
O referral dele continua em meta_webhook_logs, com o número SEM o 9º dígito."""
import csv
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "trafego" / "recuperar_meta_ad_id.py"
_spec = importlib.util.spec_from_file_location("recuperar_meta_ad_id", _SCRIPT)
rec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rec)

CLID = ("Afhy6J1tOh0F3ozUBbh5oQqoxKBS-G0WeKHOoN0cVAHXVy6M_TvbvyschdfLlIraaREmSnuz_Mb5c1Pk"
        "r-wKL2XK6lA6CrpHLSGO0zL21K3u-dtmIMYunVFstnX9rdds0rQdDdNRNw")
AD = "120250785520090163"
SERGINHO = {"id": "7c8638ee-0f89-4050-ba5a-de025d93b2da", "name": "Serginho Sinop",
            "phone": "5566997222209", "created_at": "2026-08-20 16:33:47.213672+00", "ctwa_clid": CLID}
REF = {"received_at": "2026-08-20 16:33:47.155459+00", "from_number": "556697222209",
       "ctwa_clid": CLID, "source_id": AD, "source_type": "ad"}


def _ref(**kw):
    return {**REF, **kw}


def test_serginho_casa_pelo_ctwa_clid():
    [r] = rec.casar([SERGINHO], [REF])
    assert (r["status"], r["metodo"], r["meta_ad_id"]) == ("recuperado", "ctwa_clid", AD)


def test_serginho_casa_pelo_telefone_sem_o_nono_digito():
    [r] = rec.casar([SERGINHO], [_ref(ctwa_clid=None)])
    assert (r["status"], r["metodo"], r["meta_ad_id"]) == ("recuperado", "telefone", AD)


def test_fallback_pega_o_referral_mais_proximo_antes_da_entrada():
    refs = [_ref(ctwa_clid=None, received_at="2026-08-20 14:33:00+00", source_id="111"),
            _ref(ctwa_clid=None, received_at="2026-08-20 16:03:00+00", source_id="222"),
            _ref(ctwa_clid=None, received_at="2026-08-20 16:43:00+00", source_id="333")]  # depois
    [r] = rec.casar([SERGINHO], refs)
    assert r["meta_ad_id"] == "222"


def test_fallback_nao_passa_de_24_horas():
    [r] = rec.casar([SERGINHO], [_ref(ctwa_clid=None, received_at="2026-08-19 16:00:00+00")])
    assert r["status"] == "sem_referral" and r["meta_ad_id"] == ""


def test_mesmo_clid_com_dois_anuncios_e_ambiguo():
    [r] = rec.casar([SERGINHO], [REF, _ref(source_id="999")])
    assert r["status"] == "ambiguo"


def test_referral_que_nao_e_anuncio_e_ignorado():
    [r] = rec.casar([SERGINHO], [_ref(source_type="post")])
    assert r["status"] == "sem_referral"


def test_chaves_telefone_com_e_sem_o_nove():
    assert rec.chaves_telefone("5566997222209") == {"5566997222209", "556697222209"}
    assert rec.chaves_telefone("556697222209") == {"556697222209", "5566997222209"}
    assert rec.chaves_telefone("+55 (66) 9 9722-2209") == {"5566997222209", "556697222209"}
    assert rec.chaves_telefone(None) == frozenset()


def test_sql_de_aplicacao_so_preenche_nulos_e_rejeita_lixo():
    ok = {"status": "recuperado", "lead_id": SERGINHO["id"], "meta_ad_id": AD}
    lixo = {"status": "recuperado", "lead_id": SERGINHO["id"], "meta_ad_id": "1'; drop table leads; --"}
    sql, n = rec.sql_de_aplicacao([ok, lixo, {"status": "ambiguo", "lead_id": "x", "meta_ad_id": "1|2"}])
    assert n == 1
    assert sql == (f"update public.leads set meta_ad_id = '{AD}' "
                   f"where id = '{SERGINHO['id']}' and meta_ad_id is null;\n")


def _executar_falso(sql):
    if "to_regclass" in sql:
        return [{"tem": "f"}]
    if "from public.leads" in sql:
        return [SERGINHO]
    if "meta_webhook_logs" in sql:
        return [REF]
    if "meta_ad_campaigns" in sql:
        return [{"ad_id": AD, "campaign_name": "Cafeterias | Vídeo"}]
    raise AssertionError(sql)


def test_main_dry_run_escreve_csv_e_nao_grava(tmp_path, capsys):
    def _nao_pode(sql):
        pytest.fail("dry-run não pode gravar")
    assert rec.main(["--saida", str(tmp_path)], executar=_executar_falso, aplicar=_nao_pode) == 0
    [arq] = list(tmp_path.glob("recuperar_meta_ad_id_*.csv"))
    [linha] = list(csv.DictReader(arq.open(encoding="utf-8")))
    assert (linha["status"], linha["meta_ad_id"], linha["campanha"]) == ("recuperado", AD, "Cafeterias | Vídeo")
    saida = capsys.readouterr().out
    assert "fonte: log" in saida and "recuperado: 1" in saida


def test_main_aplicar_manda_os_updates(tmp_path):
    recebido = []
    def _aplicar(sql):
        recebido.append(sql)
        return "UPDATE 1\n"
    assert rec.main(["--saida", str(tmp_path), "--aplicar"], executar=_executar_falso, aplicar=_aplicar) == 0
    assert "and meta_ad_id is null" in recebido[0]
```

- [ ] **Step 2: Run to verify fail** — PYTEST `tests/test_cs_p2_recuperar_meta_ad_id.py`: `FileNotFoundError` no import do script.

- [ ] **Step 3: Implement** `scripts/trafego/recuperar_meta_ad_id.py`:

```python
#!/usr/bin/env python3
"""Recupera leads.meta_ad_id a partir dos referrals CTWA arquivados (spec 2026-10-06, P2.5).

O webhook só passou a gravar o anúncio do Click-to-WhatsApp (referral.source_id → meta_ad_id) em
21/08/2026. Lead pago anterior tem ctwa_clid e meta_ad_id nulo, e no /trafego cai em "Meta,
campanha não identificada" (caso Antônio Sérgio/Serginho da call de 01/10). O referral da
mensagem que o trouxe continua guardado — em meta_referrals_arquivo (P0) ou, antes do P0 ser
aplicado, dentro do payload de meta_webhook_logs.

Casamento, do mais forte ao mais fraco:
  1. mesmo ctwa_clid → source_id do referral. Um clid apontando para dois anúncios = ambíguo,
     não grava;
  2. fallback: mesmo telefone (com e sem o 9º dígito — o WhatsApp ainda entrega número antigo
     sem o 9) e o referral mais próximo ANTES de leads.created_at, até 24 h.
Só referral de anúncio (source_type 'ad'). Só preenche nulos: o UPDATE leva
`and meta_ad_id is null`, então rodar de novo ou rodar depois de o lead mudar não sobrescreve.

Uso — dry-run é o padrão (sessão read-only, escreve CSV, não altera nada):
  python3 scripts/trafego/recuperar_meta_ad_id.py \\
      --psql "docker exec -i $(docker ps -q -f name=supabase_db | head -1) psql -U postgres -d postgres"
  --fonte auto|arquivo|log   (auto: meta_referrals_arquivo se existir, senão o log)
  --saida DIR                (pasta do CSV; padrão: diretório atual)
  --aplicar                  grava, um UPDATE (= uma transação) por lead. Só com OK do Rafael.
Sem dependência além da stdlib: fala com o banco pelo `psql`.
"""
import argparse
import csv
import io
import re
import shlex
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

JANELA_FALLBACK = timedelta(hours=24)

SQL_LEADS = """
select id, coalesce(name, '') as name, phone, created_at, ctwa_clid
  from public.leads
 where ctwa_clid is not null and btrim(ctwa_clid) <> '' and meta_ad_id is null
 order by created_at
""".strip()

SQL_TEM_ARQUIVO = "select to_regclass('public.meta_referrals_arquivo') is not null as tem"

SQL_REFERRALS_ARQUIVO = """
select received_at, from_number, ctwa_clid, source_id, source_type
  from public.meta_referrals_arquivo
 where source_id is not null
""".strip()

# Mesma extração de fn_arquiva_meta_referrals (P0) — produção antes da migração.
SQL_REFERRALS_LOG = """
select l.received_at,
       coalesce(m->>'from', l.from_number) as from_number,
       m->'referral'->>'ctwa_clid'   as ctwa_clid,
       m->'referral'->>'source_id'   as source_id,
       m->'referral'->>'source_type' as source_type
  from public.meta_webhook_logs l
  cross join lateral jsonb_path_query(l.payload, '$.entry[*].changes[*].value.messages[*]') as m
 where l.direction = 'inbound'
   and l.payload::text like '%"referral"%'
   and m ? 'referral'
""".strip()

SQL_CAMPANHAS = "select ad_id, campaign_name from public.meta_ad_campaigns"

CAMPOS_CSV = ("lead_id", "nome", "phone", "created_at", "status", "metodo", "meta_ad_id",
              "campanha", "referral_em")

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_AD_ID = re.compile(r"^\d{5,30}$")


def digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def chaves_telefone(v) -> frozenset:
    """O mesmo celular com e sem o 9º dígito (55 + DDD + número)."""
    d = digitos(v)
    if not d:
        return frozenset()
    chaves = {d}
    if d.startswith("55") and len(d) == 13 and d[4] == "9":
        chaves.add(d[:4] + d[5:])
    elif d.startswith("55") and len(d) == 12:
        chaves.add(d[:4] + "9" + d[4:])
    return frozenset(chaves)


def parse_ts(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def casar(leads, referrals, janela=JANELA_FALLBACK) -> list:
    """Uma linha por lead: status recuperado | ambiguo | sem_referral. Pura."""
    por_clid = defaultdict(dict)   # ctwa_clid -> {source_id: primeiro received_at}
    por_tel = defaultdict(list)    # chave de telefone -> [(received_at, source_id)]
    for r in referrals:
        sid = str(r.get("source_id") or "").strip()
        tipo = str(r.get("source_type") or "ad").strip().lower()
        if not sid or tipo != "ad":
            continue
        ts = parse_ts(r.get("received_at"))
        clid = str(r.get("ctwa_clid") or "").strip()
        if clid:
            anuncios = por_clid[clid]
            if sid not in anuncios or (ts and (anuncios[sid] is None or ts < anuncios[sid])):
                anuncios[sid] = ts
        if ts:
            for k in chaves_telefone(r.get("from_number")):
                por_tel[k].append((ts, sid))

    out = []
    for lead in leads:
        linha = {"lead_id": lead.get("id"), "nome": lead.get("name") or "",
                 "phone": lead.get("phone") or "", "created_at": lead.get("created_at") or "",
                 "status": "sem_referral", "metodo": "", "meta_ad_id": "", "referral_em": ""}
        clid = str(lead.get("ctwa_clid") or "").strip()
        anuncios = por_clid.get(clid, {}) if clid else {}
        if len(anuncios) > 1:
            linha.update(status="ambiguo", metodo="ctwa_clid", meta_ad_id="|".join(sorted(anuncios)))
        elif len(anuncios) == 1:
            sid, ts = next(iter(anuncios.items()))
            linha.update(status="recuperado", metodo="ctwa_clid", meta_ad_id=sid,
                         referral_em=ts.isoformat() if ts else "")
        else:
            criado = parse_ts(lead.get("created_at"))
            if criado:
                candidatos = {(ts, sid) for k in chaves_telefone(lead.get("phone"))
                              for ts, sid in por_tel.get(k, ()) if criado - janela <= ts <= criado}
                if candidatos:
                    ts, sid = max(candidatos)
                    linha.update(status="recuperado", metodo="telefone", meta_ad_id=sid,
                                 referral_em=ts.isoformat())
        out.append(linha)
    return out


def sql_de_aplicacao(resultados) -> tuple:
    """Um UPDATE por lead recuperado; id e anúncio validados antes de entrar no SQL."""
    linhas = []
    for r in resultados:
        if r.get("status") != "recuperado":
            continue
        lid, sid = str(r.get("lead_id") or "").lower(), str(r.get("meta_ad_id") or "")
        if not _UUID.match(lid) or not _AD_ID.match(sid):
            continue
        linhas.append(f"update public.leads set meta_ad_id = '{sid}' "
                      f"where id = '{lid}' and meta_ad_id is null;")
    return ("\n".join(linhas) + "\n" if linhas else ""), len(linhas)


def _executor_psql(psql_cmd: str):
    base = shlex.split(psql_cmd) + ["-X", "-q", "-v", "ON_ERROR_STOP=1"]

    def executar(sql: str) -> list:
        # Sessão read-only: o dry-run não grava nem por engano.
        cmd = base + ["-c", "set default_transaction_read_only = on",
                      "-c", f"copy ({sql}) to stdout with csv header"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return list(csv.DictReader(io.StringIO(res.stdout)))
    return executar


def _aplicador_psql(psql_cmd: str):
    base = shlex.split(psql_cmd) + ["-X"]

    def aplicar(sql: str) -> str:
        # Autocommit do psql: cada UPDATE é a sua transação — um lead com erro não leva os outros.
        res = subprocess.run(base + ["-f", "-"], input=sql, capture_output=True, text=True, check=True)
        if res.stderr.strip():
            print(res.stderr, file=sys.stderr)
        return res.stdout
    return aplicar


def main(argv=None, executar=None, aplicar=None) -> int:
    p = argparse.ArgumentParser(description="Recupera leads.meta_ad_id dos referrals CTWA (dry-run padrão).")
    p.add_argument("--psql", help='comando psql do banco-alvo, ex.: "docker exec -i <container> psql -U postgres -d postgres"')
    p.add_argument("--fonte", choices=("auto", "arquivo", "log"), default="auto")
    p.add_argument("--saida", default=".", help="pasta do CSV")
    p.add_argument("--aplicar", action="store_true", help="grava (só com OK do Rafael)")
    a = p.parse_args(argv)
    if executar is None or (a.aplicar and aplicar is None):
        if not a.psql:
            p.error("--psql é obrigatório")
    executar = executar or _executor_psql(a.psql)

    fonte = a.fonte
    if fonte == "auto":
        tem = executar(SQL_TEM_ARQUIVO)
        fonte = "arquivo" if tem and str(tem[0].get("tem")).lower() in ("t", "true") else "log"
    leads = executar(SQL_LEADS)
    referrals = executar(SQL_REFERRALS_ARQUIVO if fonte == "arquivo" else SQL_REFERRALS_LOG)
    resultados = casar(leads, referrals)
    campanha = {r.get("ad_id"): r.get("campaign_name") or "" for r in executar(SQL_CAMPANHAS)}
    for r in resultados:
        r["campanha"] = campanha.get(r["meta_ad_id"], "")

    Path(a.saida).mkdir(parents=True, exist_ok=True)
    caminho = Path(a.saida) / f"recuperar_meta_ad_id_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with caminho.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS_CSV, extrasaction="ignore")
        w.writeheader()
        w.writerows(resultados)

    status = Counter(r["status"] for r in resultados)
    metodo = Counter(r["metodo"] for r in resultados if r["status"] == "recuperado")
    com_campanha = sum(1 for r in resultados if r["status"] == "recuperado" and r["campanha"])
    print(f"fonte: {fonte}")
    print(f"leads com ctwa_clid e sem meta_ad_id: {len(resultados)}")
    print(f"recuperado: {status['recuperado']} (ctwa_clid: {metodo['ctwa_clid']}, "
          f"telefone: {metodo['telefone']}; com campanha conhecida: {com_campanha})")
    print(f"ambiguo: {status['ambiguo']}  sem_referral: {status['sem_referral']}")
    print(f"csv: {caminho}")

    if not a.aplicar:
        print("dry-run: nada foi gravado. --aplicar grava (só com OK do Rafael).")
        return 0
    sql, n = sql_de_aplicacao(resultados)
    if not n:
        print("nada para aplicar")
        return 0
    saida = (aplicar or _aplicador_psql(a.psql))(sql)
    gravados = sum(1 for linha in saida.splitlines() if linha.strip() == "UPDATE 1")
    print(f"aplicado: {gravados} de {n} leads (o resto já tinha meta_ad_id)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run** — PYTEST `tests/test_cs_p2_recuperar_meta_ad_id.py`. Expected: PASS.

- [ ] **Step 5: Verificação real no Postgres descartável** (com flock):

```bash
docker exec crm-scratch-pg psql -U postgres -c "drop database if exists p2;" -c "create database p2 template crm_schema;"
docker exec -i crm-scratch-pg psql -U postgres -d p2 -v ON_ERROR_STOP=1 -q -f /seed/20261006_call_semanal_base.sql
# lead do Serginho + o log com o referral (o trigger do P0 arquiva o referral)
docker exec -i crm-scratch-pg psql -U postgres -d p2 -v ON_ERROR_STOP=1 <<'SQL'
insert into leads (id, phone, name, created_at, ctwa_clid)
values ('7c8638ee-0f89-4050-ba5a-de025d93b2da', '5566997222209', 'Serginho Sinop',
        '2026-08-20 16:33:47.213672+00', '<CLID>');
insert into meta_webhook_logs (id, received_at, from_number, direction, payload)
values (gen_random_uuid(), '2026-08-20 16:33:47.155459+00', '556697222209', 'inbound',
        '{"entry":[{"changes":[{"value":{"messages":[{"from":"556697222209","referral":{"ctwa_clid":"<CLID>","source_id":"120250785520090163","source_type":"ad"}}]}}]}]}');
SQL
python3 scripts/trafego/recuperar_meta_ad_id.py --psql "docker exec -i crm-scratch-pg psql -U postgres -d p2" --saida <scratch>      # fonte: arquivo, recuperado: 1
python3 scripts/trafego/recuperar_meta_ad_id.py --psql "…" --fonte log --saida <scratch>                                         # recuperado: 1
python3 scripts/trafego/recuperar_meta_ad_id.py --psql "…" --aplicar --saida <scratch>                                           # aplicado: 1 de 1
docker exec crm-scratch-pg psql -U postgres -d p2 -c "select meta_ad_id from leads where id='7c8638ee-0f89-4050-ba5a-de025d93b2da'"  # 120250785520090163
python3 scripts/trafego/recuperar_meta_ad_id.py --psql "…" --saida <scratch>                                                     # leads …: 0
```

- [ ] **Step 6: Dry-run contra produção (somente leitura)**:

```bash
flock /root/crm-wt/_heavy.lock python3 scripts/trafego/recuperar_meta_ad_id.py \
  --psql "docker exec -i $(docker ps -q -f name=supabase_db | head -1) psql -U postgres -d postgres" \
  --saida /tmp/claude-0/…/scratchpad
grep 7c8638ee <csv>   # Serginho: recuperado, 120250785520090163
```
  Anotar as contagens no relatório.

- [ ] **Step 7: Commit** — `git commit -m "feat(trafego): script que recupera meta_ad_id dos referrals CTWA"`.

---

### Task 8: Verificação final

- [ ] PYTEST: `tests/test_cs_p2_trafego.py tests/test_cs_p2_recuperar_meta_ad_id.py tests/test_traffic_report.py tests/test_traffic_report_summary.py tests/test_traffic_report_fuso_e_meta_ad_id.py tests/test_traffic_type.py tests/test_lp_traffic_tracking.py`
- [ ] VITEST: `src/components/trafego src/lib/traffic-summary.test.ts`
- [ ] eslint em todos os `.ts/.tsx` alterados/criados.
- [ ] `git status` limpo; `git log --oneline feat/call-semanal-0110..` lista os commits do P2.

## Fora do pacote (reportar, não editar)

- `frontend/src/lib/traffic-summary.ts`: `SummaryFunnel` não tem `entraram_ja_clientes` (resolvido
  com o tipo local `FunnelComEntrada`); `collapsedLine` não o mostra.
- `frontend/src/app/api/valeria-flow/_shared.ts`: o comentário diz ser o "ÚNICO proxy" que
  repassa o Bearer — deixa de ser verdade (as proxies do /trafego novas o importam).
- P3: o trigger de `entrada` em `leads` dispara em update de `meta_ad_id` — o `--aplicar` do
  script geraria um evento `entrada` com `occurred_at = now()` por lead recuperado.
