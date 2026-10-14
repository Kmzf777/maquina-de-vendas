# Conversões infladas — janela retroativa, simulação e checagem de duplicatas — Plano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao Rafael (1) um relatório que prova "um evento por lead × etapa × destino", (2) uma janela retroativa configurável (padrão 90 = comportamento atual) e (3) um modo simulação que conta o que sairia sem gravar nem enviar.

**Spec:** `docs/superpowers/specs/2026-10-14-conversoes-ads-inflacao-design.md`

**Architecture:** Funções puras novas (`audit.find_duplicates`, `eligibility.backfill_window`) + parâmetros novos em `sweep`/`sender` (`backfill`, `dry_run`) + duas CLIs em `backend/scripts/conversoes/`. Nada de migration, nada de frontend.

**Tech Stack:** Python 3.12, supabase-py, pytest (rodar de `backend/`: `python -m pytest -q tests/<arquivo>`).

**Decisão técnica (registrar no resumo):** a spec diz "LOOKBACK passa a ser backfill_window()". Isso cortaria leads cujo **clique** é mais velho que a janela mas cujo **evento** é recente (venda 10 dias atrás de um clique de 60 dias, válido no Google). Por isso a seleção de leads continua olhando cliques de 90 dias e a janela retroativa filtra **o evento** dentro de `build_candidates`. Com janela 90 o resultado é idêntico ao de hoje.

## Arquivos

| Arquivo | O quê |
|---|---|
| `backend/app/conversions/audit.py` (novo) | `find_duplicates(rows)` puro |
| `backend/scripts/conversoes/checar_duplicatas.py` (novo) | CLI só leitura |
| `backend/app/conversions/eligibility.py` | `MAX_BACKFILL_DAYS`, `backfill_window(days=None)`, `dry_run_enabled()`, `age_bucket(age)` |
| `backend/app/conversions/sweep.py` | `build_candidates(..., backfill=None)`, `simulate_sweep`, `run_sweep(..., dry_run=False)` |
| `backend/app/conversions/sender.py` | `outside_window(row, now, backfill=None)`, `simulate_sender`, `run_sender(..., dry_run=False)` |
| `backend/app/worker/main.py` | ticks passam `dry_run=dry_run_enabled()` |
| `backend/scripts/conversoes/simular_ativacao.py` (novo) | CLI dry-run |
| `docs/setup/conversoes-ads.md` | secundárias, metas "Lead captado", variáveis e scripts |

Ordem: **Task 1 e Task 2 em paralelo** (arquivos disjuntos) → Task 3 (usa `eligibility` da Task 2) → Task 4.

---

### Task 1: Relatório de duplicatas

**Files:** Create `backend/app/conversions/audit.py`, `backend/scripts/conversoes/checar_duplicatas.py`, `backend/tests/test_conversions_audit.py`

- [ ] **Step 1: Teste que falha** — `backend/tests/test_conversions_audit.py`:

```python
from unittest.mock import MagicMock

from app.conversions.audit import find_duplicates
from scripts.conversoes import checar_duplicatas as cd


def _r(i, lead="L1", platform="google", stage="qualified", event_id=None, sale_id=None, status="enviado"):
    return {"id": i, "lead_id": lead, "platform": platform, "stage": stage,
            "event_id": event_id or f"e{i}", "sale_id": sale_id, "status": status}


def test_sem_duplicata_listas_vazias():
    rows = [_r("1"), _r("2", lead="L2"), _r("3", platform="meta"), _r("4", stage="opportunity")]
    d = find_duplicates(rows)
    assert d == {"lead_stage": [], "sale": [], "event_id": []}


def test_mesmo_lead_etapa_plataforma_e_duplicata():
    d = find_duplicates([_r("1"), _r("2")])
    assert len(d["lead_stage"]) == 1
    g = d["lead_stage"][0]
    assert g["key"] == ("google", "qualified", "L1") and g["n"] == 2
    assert sorted(x["id"] for x in g["rows"]) == ["1", "2"]


def test_mesmo_event_id_e_duplicata():
    d = find_duplicates([_r("1", event_id="X"), _r("2", lead="L2", event_id="X")])
    assert [g["key"] for g in d["event_id"]] == [("google", "X")]
    assert d["lead_stage"] == []


def test_mesma_venda_duas_vezes_e_duplicata_mas_duas_vendas_do_lead_nao():
    d = find_duplicates([_r("1", stage="purchase", sale_id="S1"), _r("2", stage="purchase", sale_id="S1")])
    assert [g["key"] for g in d["sale"]] == [("google", "S1")]
    d2 = find_duplicates([_r("1", stage="purchase", sale_id="S1"), _r("2", stage="purchase", sale_id="S2")])
    assert d2 == {"lead_stage": [], "sale": [], "event_id": []}


def test_linhas_nunca_enviadas_nao_contam():
    for st in ("ignorado", "fora_da_janela"):
        assert find_duplicates([_r("1"), _r("2", status=st)])["lead_stage"] == []


def test_mesmo_lead_em_plataformas_diferentes_nao_e_duplicata():
    assert find_duplicates([_r("1", platform="meta"), _r("2", platform="google")])["lead_stage"] == []


def test_cli_sai_com_1_quando_ha_duplicata(monkeypatch, capsys):
    monkeypatch.setattr(cd, "_ler", lambda: [_r("1"), _r("2")])
    assert cd.main([]) == 1
    assert "duplicad" in capsys.readouterr().out.lower()


def test_cli_sai_com_0_sem_duplicata(monkeypatch, capsys):
    monkeypatch.setattr(cd, "_ler", lambda: [_r("1")])
    assert cd.main([]) == 0
    assert "0 duplicatas" in capsys.readouterr().out
```

- [ ] **Step 2:** `python -m pytest -q tests/test_conversions_audit.py` → FAIL (módulo não existe).

- [ ] **Step 3: Implementar** `backend/app/conversions/audit.py`:

```python
# backend/app/conversions/audit.py
"""Checagem: no máximo um evento por lead × etapa × plataforma (venda: por venda), e nenhum
`event_id` repetido na mesma plataforma. Puro, sem I/O — a CLI é `scripts/conversoes/checar_duplicatas`.

Linhas `ignorado` e `fora_da_janela` nunca saíram para a plataforma: não contam."""
from collections import defaultdict
from typing import Any

_NUNCA_ENVIADAS = ("ignorado", "fora_da_janela")


def _grupos(rows, key_fn) -> list[dict[str, Any]]:
    g: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        k = key_fn(r)
        if k is not None:
            g[k].append(r)
    return [{"key": k, "n": len(v), "rows": [{"id": r.get("id"), "status": r.get("status")} for r in v]}
            for k, v in sorted(g.items(), key=lambda kv: tuple(str(x) for x in kv[0])) if len(v) > 1]


def find_duplicates(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    vivas = [r for r in rows if r.get("status") not in _NUNCA_ENVIADAS]
    return {
        "lead_stage": _grupos(vivas, lambda r: None if r.get("stage") == "purchase"
                              else (r.get("platform"), r.get("stage"), r.get("lead_id"))),
        "sale": _grupos(vivas, lambda r: (r.get("platform"), r.get("sale_id"))
                        if r.get("stage") == "purchase" and r.get("sale_id") else None),
        "event_id": _grupos(vivas, lambda r: (r.get("platform"), r.get("event_id")) if r.get("event_id") else None),
    }
```

`backend/scripts/conversoes/checar_duplicatas.py`:

```python
"""Relatório de duplicatas em `ad_conversions` (só leitura).

Uso (de dentro do container da API/worker, em /app):
    python -m scripts.conversoes.checar_duplicatas
Sai com 1 se houver duplicata."""
import sys
from collections import Counter
from typing import Any

from app.conversions.audit import find_duplicates

_TITULOS = {"lead_stage": "lead × etapa × plataforma", "sale": "venda × plataforma",
            "event_id": "event_id × plataforma"}


def _ler() -> list[dict[str, Any]]:
    from app.db.paginacao import paginar
    from app.db.supabase import get_supabase
    sb = get_supabase()
    return paginar(lambda: sb.table("ad_conversions")
                   .select("id,lead_id,platform,stage,event_id,sale_id,status").order("id"))


def main(argv: list[str] | None = None) -> int:
    rows = _ler()
    print(f"ad_conversions: {len(rows)} linhas")
    for (p, s, st), n in sorted(Counter((r["platform"], r["stage"], r["status"]) for r in rows).items()):
        print(f"  {p:7} {s:12} {st:15} {n}")
    dup = find_duplicates(rows)
    total = sum(len(v) for v in dup.values())
    if not total:
        print("0 duplicatas (lead × etapa × plataforma, venda, event_id)")
        return 0
    print(f"{total} grupos duplicados:")
    for tipo, grupos in dup.items():
        for g in grupos:
            print(f"  [{_TITULOS[tipo]}] {g['key']}: {g['n']} linhas {g['rows']}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4:** `python -m pytest -q tests/test_conversions_audit.py` → PASS.
- [ ] **Step 5:** `git add backend/app/conversions/audit.py backend/scripts/conversoes/checar_duplicatas.py backend/tests/test_conversions_audit.py && git commit -m "feat(conversoes): relatorio de duplicatas por lead, etapa, venda e event_id"`

---

### Task 2: Janela retroativa + simulação na varredura

**Files:** Modify `backend/app/conversions/eligibility.py`, `backend/app/conversions/sweep.py`; Test `backend/tests/test_conversions_eligibility.py`, `backend/tests/test_conversions_sweep.py`

- [ ] **Step 1: Testes que falham.** Em `tests/test_conversions_eligibility.py` (acrescentar):

```python
from datetime import timedelta

from app.conversions.eligibility import age_bucket, backfill_window, dry_run_enabled


def test_backfill_padrao_90(monkeypatch):
    monkeypatch.delenv("CONVERSIONS_BACKFILL_DAYS", raising=False)
    assert backfill_window() == timedelta(days=90)


def test_backfill_lido_do_env_e_limitado(monkeypatch):
    for raw, dias in (("30", 30), ("7", 7), ("200", 90), ("0", 1), ("-5", 1), ("abc", 90), ("", 90)):
        monkeypatch.setenv("CONVERSIONS_BACKFILL_DAYS", raw)
        assert backfill_window() == timedelta(days=dias), raw


def test_backfill_explicito_vence_o_env(monkeypatch):
    monkeypatch.setenv("CONVERSIONS_BACKFILL_DAYS", "30")
    assert backfill_window(10) == timedelta(days=10)
    assert backfill_window(500) == timedelta(days=90)


def test_dry_run_enabled(monkeypatch):
    monkeypatch.delenv("CONVERSIONS_DRY_RUN", raising=False)
    assert dry_run_enabled() is False
    monkeypatch.setenv("CONVERSIONS_DRY_RUN", "true")
    assert dry_run_enabled() is True


def test_age_bucket():
    assert age_bucket(timedelta(days=7)) == "0-7d"
    assert age_bucket(timedelta(days=7, hours=1)) == "8-30d"
    assert age_bucket(timedelta(days=30)) == "8-30d"
    assert age_bucket(timedelta(days=31)) == "31-90d"
```

Em `tests/test_conversions_sweep.py` (acrescentar; usa `_lead`, `NOW`, `_fake_sb`, `_Q` já existentes):

```python
def _lead_com_repasse(dias_atras):
    at = NOW - timedelta(days=dias_atras)
    return _lead(ctwa_clid=None, created_at=(at - timedelta(hours=1)).isoformat(),
                 metadata={"handoff": {"at": at.isoformat(), "motivo": "lead qualificado"}})


def _gentrada(dias_atras):
    return [{"occurred_at": (NOW - timedelta(days=dias_atras, hours=1)).isoformat(), "metadata": {"gclid": "G1"}}]


def test_janela_retroativa_corta_evento_mais_velho():
    rows = build_candidates(lead=_lead_com_repasse(40), entradas=_gentrada(40), sales=[], opportunity_at=None,
                            values={}, now=NOW, backfill=timedelta(days=30))
    assert rows == []
    rows = build_candidates(lead=_lead_com_repasse(20), entradas=_gentrada(20), sales=[], opportunity_at=None,
                            values={}, now=NOW, backfill=timedelta(days=30))
    assert _keys(rows) == ["google:qualified:G1"]


def test_sem_janela_explicita_usa_90(monkeypatch):
    monkeypatch.delenv("CONVERSIONS_BACKFILL_DAYS", raising=False)
    rows = build_candidates(lead=_lead_com_repasse(40), entradas=_gentrada(40), sales=[], opportunity_at=None,
                            values={}, now=NOW)
    assert _keys(rows) == ["google:qualified:G1"]


def test_venda_recente_de_clique_velho_respeita_a_janela_do_evento():
    # clique há 60 dias, venda há 10: com janela 30, a venda entra (a janela é da idade do EVENTO)
    entradas = [{"occurred_at": (NOW - timedelta(days=60)).isoformat(), "metadata": {"gclid": "G1"}}]
    sale = {"id": "S1", "sold_at": (NOW - timedelta(days=10)).isoformat(), "value": 500, "status": "ok"}
    rows = build_candidates(lead=_lead(ctwa_clid=None), entradas=entradas, sales=[sale], opportunity_at=None,
                            values={}, now=NOW, backfill=timedelta(days=30))
    assert _keys(rows) == ["google:purchase:S1"]


def _tables_dry():
    return {
        "ad_conversion_values": [],
        "lead_events": [{"lead_id": "L1", "event_type": "entrada",
                         "occurred_at": (NOW - timedelta(days=40, hours=1)).isoformat(), "metadata": {"gclid": "G1"}},
                        {"lead_id": "L2", "event_type": "entrada",
                         "occurred_at": (NOW - timedelta(days=3, hours=1)).isoformat(), "metadata": {"gclid": "G2"}}],
        "leads": [{**_lead_com_repasse(40), "id": "L1"}, {**_lead_com_repasse(3), "id": "L2"}],
        "sales": [], "quotes": [],
    }


def _fake_sb_dry(tables, upserts, log, existentes=()):
    sb = _fake_sb(tables, upserts, log)
    base = sb.table.side_effect

    def _table(name):
        if name == "ad_conversions":
            q = base(name)
            q.select.return_value = _Q("ad_conversions", [{"dedupe_key": k} for k in existentes], log)
            return q
        return base(name)
    sb.table.side_effect = _table
    return sb


def test_dry_run_nao_faz_upsert_e_conta_por_plataforma_etapa_e_idade(monkeypatch):
    upserts, log = [], []
    monkeypatch.setattr(sweep_mod, "get_supabase", lambda: _fake_sb_dry(_tables_dry(), upserts, log))
    res = sweep_mod.simulate_sweep(now=NOW, backfill_days=90)
    assert upserts == []
    assert res["novos"] == {("google", "qualified", "0-7d"): 1, ("google", "qualified", "31-90d"): 1}
    assert res["ja_na_fila"] == 0


def test_dry_run_desconta_o_que_ja_esta_na_fila(monkeypatch):
    upserts, log = [], []
    monkeypatch.setattr(sweep_mod, "get_supabase",
                        lambda: _fake_sb_dry(_tables_dry(), upserts, log, existentes=["google:qualified:G2"]))
    res = sweep_mod.simulate_sweep(now=NOW, backfill_days=30)
    assert upserts == []
    assert res["novos"] == {}  # L1 fora da janela de 30; L2 já na fila
    assert res["ja_na_fila"] == 1


def test_run_sweep_dry_run_nao_grava(monkeypatch):
    upserts, log = [], []
    monkeypatch.setattr(sweep_mod, "get_supabase", lambda: _fake_sb_dry(_tables_dry(), upserts, log))
    n = sweep_mod.run_sweep(now=NOW, dry_run=True)
    assert upserts == [] and n == 2
```

- [ ] **Step 2:** `python -m pytest -q tests/test_conversions_eligibility.py tests/test_conversions_sweep.py` → FAIL.

- [ ] **Step 3: Implementar.** Em `eligibility.py`, depois de `WINDOW`/`CLICK_TYPES` (acrescentar `import os` no topo):

```python
# Janela retroativa: idade máxima do EVENTO para entrar na fila e ser enviado. Padrão 90 (= a janela
# de clique do Google, decisão do Rafael em 14/10: é o que está configurado nas ações do Google Ads).
# As janelas das plataformas (WINDOW) continuam valendo por cima.
MAX_BACKFILL_DAYS = 90


def backfill_window(days: int | None = None) -> timedelta:
    """`days` explícito (CLI) ou `CONVERSIONS_BACKFILL_DAYS`; ausente/inválido → 90; limitado a 1..90."""
    if days is None:
        try:
            days = int((os.getenv("CONVERSIONS_BACKFILL_DAYS") or "").strip())
        except ValueError:
            days = MAX_BACKFILL_DAYS
    return timedelta(days=max(1, min(days, MAX_BACKFILL_DAYS)))


def dry_run_enabled() -> bool:
    return (os.getenv("CONVERSIONS_DRY_RUN") or "").strip().lower() in ("1", "true", "yes", "on")


def age_bucket(age: timedelta) -> str:
    """Faixa de idade do evento no relatório de simulação."""
    if age <= timedelta(days=7):
        return "0-7d"
    if age <= timedelta(days=30):
        return "8-30d"
    return "31-90d"
```

Em `sweep.py`:
1. Importar `age_bucket, backfill_window` de `eligibility`.
2. `build_candidates(..., now: datetime, backfill: timedelta | None = None)`: no início `backfill = backfill or backfill_window()`; no laço de eventos, junto ao `event_at > now`, pular `now - event_at > backfill` (comentário: janela retroativa da spec de 14/10). Atualizar a docstring com a regra.
3. Extrair o corpo de leitura do `run_sweep` para um gerador `_blocos(sb, now, backfill)` que devolve, por bloco, `(rows, falhas)` — `rows` é a lista de candidatos montada com `build_candidates(..., backfill=backfill)`. A seleção de leads e as consultas continuam com `since = now - LOOKBACK` (90 dias, para não perder clique velho com evento recente).
4. `run_sweep(now=None, dry_run=False)`: se `dry_run`, `res = simulate_sweep(now)`; loga `[CONVERSOES][SIMULACAO] varredura: %d novos (%s), %d já na fila` e retorna `sum(res["novos"].values())`. Senão, comportamento atual (upsert por bloco) usando `_blocos` com `backfill_window()`.
5. Nova função:

```python
def simulate_sweep(now: datetime | None = None, backfill_days: int | None = None) -> dict[str, Any]:
    """Dry-run: o que a varredura enfileiraria agora, sem gravar. Conta só as `dedupe_key` que
    ainda não estão em `ad_conversions`, por (plataforma, etapa, faixa de idade do evento)."""
    now = now or datetime.now(timezone.utc)
    backfill = backfill_window(backfill_days)
    sb = get_supabase()
    novos: Counter = Counter()
    ja = 0
    for rows, _falhas in _blocos(sb, now, backfill):
        if not rows:
            continue
        keys = [r["dedupe_key"] for r in rows]
        existentes: set[str] = set()
        for i in range(0, len(keys), _CHUNK):
            existentes |= {e["dedupe_key"] for e in (sb.table("ad_conversions").select("dedupe_key")
                           .in_("dedupe_key", keys[i:i + _CHUNK]).execute().data or [])}
        for r in rows:
            if r["dedupe_key"] in existentes:
                ja += 1
            else:
                novos[(r["platform"], r["stage"], age_bucket(now - _ts(r["event_at"])))] += 1
    return {"novos": dict(novos), "ja_na_fila": ja, "backfill_days": backfill.days}
```

(`from collections import Counter, defaultdict`.)

- [ ] **Step 4:** `python -m pytest -q tests/test_conversions_eligibility.py tests/test_conversions_sweep.py` → PASS (os testes antigos também).
- [ ] **Step 5:** commit `feat(conversoes): janela retroativa configuravel e simulacao da varredura`.

---

### Task 3: Janela retroativa + simulação no sender

**Files:** Modify `backend/app/conversions/sender.py`; Test `backend/tests/test_conversions_sender.py`. Depende da Task 2 (`backfill_window`, `age_bucket`).

- [ ] **Step 1: Testes que falham** (acrescentar em `tests/test_conversions_sender.py`; usa `_row`, `_qrow`, `_fake_sb`, `_env`, `_updates`, `NOW` existentes):

```python
from datetime import timedelta

from app.conversions.sender import outside_window


def test_outside_window_respeita_a_janela_retroativa():
    r = _row(platform="google", event_at=(NOW - timedelta(days=40)).isoformat(),
             click_at=(NOW - timedelta(days=41)).isoformat())
    assert outside_window(r, NOW) is False                         # padrão 90
    assert outside_window(r, NOW, backfill=timedelta(days=30)) is True


def test_run_sender_evento_fora_da_janela_retroativa_nao_envia(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("CONVERSIONS_BACKFILL_DAYS", "3")
    row = _qrow(platform="meta", event_at=(NOW - timedelta(days=5)).isoformat(),
                click_at=(NOW - timedelta(days=5, hours=1)).isoformat())
    sb, log = _fake_sb([row])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    send = MagicMock()
    monkeypatch.setattr(sender_mod.meta, "send", send)
    counts = sender_mod.run_sender(now=NOW)
    send.assert_not_called()
    assert counts["fora_da_janela"] == 1


def test_run_sender_dry_run_nao_envia_nem_grava(monkeypatch):
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow(platform="meta")])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    send = MagicMock()
    monkeypatch.setattr(sender_mod.meta, "send", send)
    claim = MagicMock(return_value=True)
    monkeypatch.setattr(sender_mod, "_claim", claim)
    res = sender_mod.run_sender(now=NOW, dry_run=True)
    send.assert_not_called()
    claim.assert_not_called()
    assert _updates(log) == []
    assert res["simulacao"] == {("meta", _qrow()["stage"], "0-7d"): 1}


def test_simulate_sender_conta_plataformas_pedidas_sem_estarem_ligadas(monkeypatch):
    monkeypatch.delenv("CONVERSIONS_META_ENABLED", raising=False)
    monkeypatch.delenv("CONVERSIONS_GOOGLE_ENABLED", raising=False)
    velho = _qrow(platform="meta", event_at=(NOW - timedelta(days=8)).isoformat())
    sb, log = _fake_sb([_qrow(platform="meta"), velho])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    res = sender_mod.simulate_sender(now=NOW, platforms=("meta",))
    assert sum(res["enviaria"].values()) == 1 and res["fora_da_janela"] == 1
    assert _updates(log) == []
```

(Ajustar os campos de `_qrow`/`_row` ao que o arquivo já define — ler `_row` na linha 14 antes. Se `_row()` já for de 1 dia atrás, o bucket é `0-7d`.)

- [ ] **Step 2:** `python -m pytest -q tests/test_conversions_sender.py` → FAIL.

- [ ] **Step 3: Implementar** em `sender.py`:
1. Importar `age_bucket, backfill_window` de `eligibility`; `from collections import Counter`.
2. `outside_window(row, now, backfill: timedelta | None = None)`: antes das regras de plataforma, `if now - parse_ts(row["event_at"]) > (backfill or backfill_window()): return True`. Docstring: acrescentar a janela retroativa.
3. Em `run_sender(now=None, limit=100, dry_run=False)`: calcular `backfill = backfill_window()` uma vez e passar `outside_window(row, now, backfill)`. Se `dry_run`: depois de montar `platforms`/`google_stages`, retornar `{**counts, "simulacao": simulate_sender(now, platforms=tuple(platforms), google_stages=google_stages)["enviaria"]}` com log `[CONVERSOES][SIMULACAO] envio: ...` — sem claim, sem envio, sem update (se não houver plataforma pronta, `simulacao` = `{}`).
4. Nova função:

```python
def simulate_sender(now: datetime | None = None, platforms: tuple[str, ...] = ("meta", "google"),
                    google_stages: list[str] | None = None, backfill_days: int | None = None) -> dict[str, Any]:
    """Dry-run: o que sairia da fila agora (pendente e vencido), sem claim, envio nem gravação.
    Pagina sem limite de lote: mostra o tamanho real do salto de uma ativação."""
    now = now or datetime.now(timezone.utc)
    backfill = backfill_window(backfill_days)
    sb = get_supabase()
    enviaria: Counter = Counter()
    fora = 0
    for platform in platforms:
        rows = paginar(lambda: sb.table("ad_conversions").select("id,platform,stage,event_at,click_at")
                       .eq("status", "pendente").eq("platform", platform)
                       .lte("next_attempt_at", now.isoformat()).order("id"))
        for r in rows:
            if platform == "google" and google_stages is not None and r["stage"] not in google_stages:
                continue
            if outside_window(r, now, backfill):
                fora += 1
            else:
                enviaria[(platform, r["stage"], age_bucket(now - parse_ts(r["event_at"])))] += 1
    return {"enviaria": dict(enviaria), "fora_da_janela": fora, "backfill_days": backfill.days}
```

(`from app.db.paginacao import paginar`. O `_Q` falso dos testes ignora `range` — `paginar` chama `.range().execute()`, que o `_Q` aceita via `__getattr__`; se a página falsa vier com < 1000 linhas o laço termina.)

- [ ] **Step 4:** `python -m pytest -q tests/test_conversions_sender.py` → PASS.
- [ ] **Step 5:** commit `feat(conversoes): sender respeita a janela retroativa e tem modo simulacao`.

---

### Task 4: Worker, CLI de simulação e documentação

**Files:** Modify `backend/app/worker/main.py`, `docs/setup/conversoes-ads.md`; Create `backend/scripts/conversoes/simular_ativacao.py`, `backend/tests/test_conversoes_simular_ativacao.py`

- [ ] **Step 1: Teste que falha** `tests/test_conversoes_simular_ativacao.py`:

```python
from scripts.conversoes import simular_ativacao as sa


def test_cli_imprime_tabela_e_repassa_a_janela(monkeypatch, capsys):
    vistos = {}

    def _sweep(now=None, backfill_days=None):
        vistos["sweep"] = backfill_days
        return {"novos": {("google", "qualified", "31-90d"): 5}, "ja_na_fila": 2, "backfill_days": backfill_days or 90}

    def _sender(now=None, platforms=("meta", "google"), google_stages=None, backfill_days=None):
        vistos["sender"] = backfill_days
        return {"enviaria": {("meta", "qualified", "0-7d"): 1}, "fora_da_janela": 0, "backfill_days": backfill_days or 90}

    monkeypatch.setattr(sa, "simulate_sweep", _sweep)
    monkeypatch.setattr(sa, "simulate_sender", _sender)
    assert sa.main(["--dias", "30"]) == 0
    out = capsys.readouterr().out
    assert vistos == {"sweep": 30, "sender": 30}
    assert "google" in out and "qualified" in out and "5" in out and "SIMULA" in out.upper()
```

E em `tests/test_worker_task_specs_conversoes.py` (ler o arquivo antes; acrescentar):

```python
def test_ticks_de_conversoes_respeitam_o_dry_run(monkeypatch):
    import asyncio
    from app.conversions import sender, sweep
    from app.worker import main as wm
    chamadas = {}
    monkeypatch.setattr(sweep, "run_sweep", lambda dry_run=False: chamadas.setdefault("sweep", dry_run))
    monkeypatch.setattr(sender, "run_sender", lambda dry_run=False: chamadas.setdefault("sender", dry_run))
    monkeypatch.setenv("CONVERSIONS_DRY_RUN", "true")
    asyncio.run(wm._conversions_sweep_tick())
    asyncio.run(wm._conversions_send_tick())
    assert chamadas == {"sweep": True, "sender": True}
```

- [ ] **Step 2:** rodar os dois arquivos → FAIL.

- [ ] **Step 3: Implementar.**

`worker/main.py`:

```python
async def _conversions_sweep_tick() -> None:
    from app.conversions.eligibility import dry_run_enabled
    from app.conversions.sweep import run_sweep
    await asyncio.to_thread(run_sweep, dry_run=dry_run_enabled())


async def _conversions_send_tick() -> None:
    from app.conversions.eligibility import dry_run_enabled
    from app.conversions.sender import run_sender
    await asyncio.to_thread(run_sender, dry_run=dry_run_enabled())
```

`scripts/conversoes/simular_ativacao.py`:

```python
"""Simula uma ativação (dry-run): quantos eventos a varredura enfileiraria e quantos o sender
enviaria agora, por plataforma × etapa × idade do evento. Não grava nem envia nada.

Rodar ANTES de qualquer reativação (pausa, etapa ou plataforma nova) — spec de 14/10.

Uso (de dentro do container, em /app):
    python -m scripts.conversoes.simular_ativacao [--dias N]
"""
import argparse
import sys

from app.conversions.sender import simulate_sender
from app.conversions.sweep import simulate_sweep


def _tabela(titulo: str, cont: dict) -> None:
    print(titulo)
    if not cont:
        print("  (nada)")
    for (p, s, faixa), n in sorted(cont.items()):
        print(f"  {p:7} {s:12} {faixa:7} {n}")
    print(f"  total: {sum(cont.values())}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dias", type=int, default=None, help="janela retroativa (padrão: CONVERSIONS_BACKFILL_DAYS ou 90)")
    a = ap.parse_args(argv)
    sw = simulate_sweep(backfill_days=a.dias)
    se = simulate_sender(backfill_days=a.dias)
    print(f"SIMULAÇÃO — janela retroativa {sw['backfill_days']} dias — nada foi gravado nem enviado")
    _tabela("Varredura: novos eventos que entrariam na fila", sw["novos"])
    print(f"  (já na fila, ignorados: {sw['ja_na_fila']})")
    _tabela("Sender: pendentes que sairiam agora", se["enviaria"])
    print(f"  (pendentes fora da janela: {se['fora_da_janela']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`docs/setup/conversoes-ads.md` — na seção "Configuração feita em 13/10" acrescentar um bloco "Ajuste de 14/10 (cartão cf1d26dd)":
- Ações do CRM no Google (Lead_Qualificado, Oportunidade_Criada, Venda_Fechada) são **secundárias** — fora da coluna "Conversões"; aparecem em "Todas as conv.". Se ficarem principais, somam com as conversões do site e a mesma pessoa conta duas vezes (14/10, campanha Terceirização: 29 + 9).
- "Lead captado" = metas personalizadas **Empório e Cafeteria** (Atacado 2 obg 7382055753 + Conversation started 7288479086) e **Terceirização** (Terceirização 2 Obg 7394745545 + Conversation started). Não existe ação Lead_Captado.
- `CONVERSIONS_BACKFILL_DAYS` (padrão 90, 1..90) e `CONVERSIONS_DRY_RUN`.
- Scripts `checar_duplicatas` e `simular_ativacao` com o comando; regra: **simular antes de qualquer reativação**.
Na tabela de variáveis da seção 2, acrescentar as duas variáveis.

- [ ] **Step 4:** rodar os dois arquivos → PASS; depois a suíte de conversões inteira: `python -m pytest -q tests -k "conversions or conversoes"` → PASS.
- [ ] **Step 5:** commit `feat(conversoes): worker em modo simulacao, CLI simular_ativacao e roteiro`.

---

### Task 5 (controlador): verificação

- Suíte de backend inteira: `python -m pytest -q tests` (local) — verde (anotar falhas pré-existentes, se houver, comparando com `origin/master`).
- Container descartável na VPS (imagem `canastra-api`, código do branch montado, `.env` de produção **sem** `CONVERSIONS_*_ENABLED` e com `CONVERSIONS_DRY_RUN=true`): `checar_duplicatas` → 0; `count(*)` de `ad_conversions` antes; `simular_ativacao`; `simular_ativacao --dias 30`; `count(*)` depois — igual.
