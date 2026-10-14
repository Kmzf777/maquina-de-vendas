# Ativação das conversões Meta/Google — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deixar `feat/conversoes-ads` publicável: Google aceita o evento (eventSource), etapa lead fora da fila, branch em dia com o `master`, e o teste em modo teste feito.

**Architecture:** Duas correções pequenas em `backend/app/conversions/` (cliente Google e varredura), merge do `master` e validação em container descartável na VPS com a imagem `canastra-api` e o código do branch montado — sem tocar nos serviços.

**Tech Stack:** Python 3.12, pytest, httpx, Supabase (PostgREST), Docker na VPS; Next.js/vitest no frontend.

**Spec:** `docs/superpowers/specs/2026-10-13-conversoes-ads-ativacao-design.md`

**Como rodar os testes do backend** (venv local quebrado — sempre na VPS):

```bash
# na máquina local, a partir da raiz do worktree
tar -czf - --exclude=node_modules --exclude=.next --exclude=__pycache__ backend supabase scripts docs \
  | ssh -i "C:\Users\rafae\.ssh\agente_crm" root@173.249.15.11 \
    'rm -rf /root/agente-23ab1cc4 && mkdir -p /root/agente-23ab1cc4 && tar -xzf - -C /root/agente-23ab1cc4'
ssh -i "C:\Users\rafae\.ssh\agente_crm" root@173.249.15.11 \
  'docker run --rm -v /root/agente-23ab1cc4:/repo -w /repo/backend canastra-api:latest sh -c \
   "pip install -q pytest pytest-asyncio pytest-mock respx >/dev/null 2>&1; python -m pytest -q -p no:cacheprovider <ALVO>"'
```

`<ALVO>` = arquivo de teste ou `tests` (suíte inteira, ~7 min).

---

### Task 1: `eventSource` no evento do Google

**Files:**
- Modify: `backend/app/conversions/google.py` (`build_event`)
- Test: `backend/tests/test_conversions_google.py`

- [ ] **Step 1: Teste que falha** — acrescentar em `test_conversions_google.py`, logo após `test_build_event`:

```python
def test_build_event_tem_event_source_other():
    # A Data Manager API recusa o evento sem event_source (400 REQUIRED_FIELD_MISSING, visto em
    # 13/10/2026). A conversão é offline (fechada por WhatsApp/telefone): OTHER.
    ev = google.build_event(ROW, LEAD)
    assert ev["eventSource"] == "OTHER"
```

- [ ] **Step 2: Rodar e ver falhar** — `<ALVO>` = `tests/test_conversions_google.py::test_build_event_tem_event_source_other`. Esperado: FAIL com `KeyError: 'eventSource'`.

- [ ] **Step 3: Implementar** — em `build_event`, no dicionário `ev`, depois de `"currency"`:

```python
    ev: dict[str, Any] = {
        "adIdentifiers": {row["click_id_type"]: row["click_id"]},
        "transactionId": row["event_id"],
        "eventTimestamp": ts,
        "currency": row.get("currency") or "BRL",
        # Obrigatório na Data Manager API (sem ele: 400 REQUIRED_FIELD_MISSING). A venda/repasse
        # acontece fora do site (WhatsApp/telefone).
        "eventSource": "OTHER",
    }
```

- [ ] **Step 4: Rodar `tests/test_conversions_google.py` inteiro** — esperado: tudo PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/conversions/google.py backend/tests/test_conversions_google.py
git commit -m "fix(conversoes): Google exige eventSource no evento (Data Manager API devolvia 400)"
```

### Task 2: etapa `lead` fora da varredura

**Files:**
- Modify: `backend/app/conversions/sweep.py` (`build_candidates`)
- Test: `backend/tests/test_conversions_sweep.py`

- [ ] **Step 1: Trocar o teste** — substituir `test_lead_com_clique_google_gera_evento_lead_com_valor` por:

```python
def test_clique_google_sozinho_nao_gera_evento():
    # Spec 13/10: o clique (lead) já é contado no Google pelas conversões do site e por "Leads de
    # mensagens"; mandar de novo contaria a mesma pessoa duas vezes. Só qualificado/oportunidade/venda.
    rows = build_candidates(lead=_lead(ctwa_clid=None), entradas=GENTRADAS, sales=[], opportunity_at=None,
                            values=VALUES, now=NOW)
    assert rows == []


def test_clique_google_com_repasse_gera_so_qualified():
    lead = _lead(ctwa_clid=None,
                 metadata={"handoff": {"at": (CLICK + timedelta(hours=3)).isoformat(), "motivo": "lead qualificado"}})
    rows = build_candidates(lead=lead, entradas=GENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["google:qualified:G1"]
    r = rows[0]
    assert r["segment"] == "atacado" and r["campaign_name"] == "Search"
    assert r["click_id_type"] == "gclid" and r["click_at"] == CLICK.isoformat()
    assert r["status"] == "pendente" and r["currency"] == "BRL"
```

- [ ] **Step 2: Rodar e ver falhar** — `<ALVO>` = `tests/test_conversions_sweep.py`. Esperado: `test_clique_google_sozinho_nao_gera_evento` FAIL (`google:lead:G1` presente). Anotar quaisquer outros testes que esperem chaves `google:lead:*`.

- [ ] **Step 3: Implementar** — em `build_candidates`, remover o laço que cria o evento `lead` e o desvio `stage == "lead"` que ficou sem uso; atualizar a docstring:

```python
    """Linhas candidatas de UM lead (puro). Regras da §5 da spec de 08/10, com a mudança de 13/10:

    - o clique (`lead`) NÃO vira evento: no Google já é contado pelas conversões do site e por
      "Leads de mensagens", e a Meta conta a conversa sozinha;
    - qualificado/oportunidade/venda vão para o clique atribuído (o mais recente da plataforma
      antes do evento, dentro da janela clique→evento);
    - já era cliente → só venda; venda cancelada não entra;
    - evento fora da janela de envio (ou ainda no futuro) não é enfileirado;
    - uma linha por `dedupe_key`.
    """
```

```python
    # (stage, event_at, value, sale_id)
    eventos: list[tuple[str, datetime, float | None, str | None]] = []
    handoff = (lead.get("metadata") or {}).get("handoff")
    if qualified_handoff_ok(handoff):
        at = _ts(handoff["at"])
        if at:
            eventos.append(("qualified", at, values.get((segment, "qualified")), None))
    opp = _ts(opportunity_at)
    if opp:
        eventos.append(("opportunity", opp, values.get((segment, "opportunity")), None))
    for s in sales:
        ...  # igual, com eventos.append(("purchase", at, float(s["value"]), s["id"]))

    out: dict[str, dict[str, Any]] = {}
    for stage, event_at, value, sale_id in eventos:
        if not stage_allowed(stage, ja_cliente) or event_at > now:
            continue  # futuro (orçamento datado para amanhã): entra numa rodada seguinte
        for platform in PLATFORMS:
            click = attributed_click(clicks, platform, event_at)
            if click is None or not _sendable(platform, click, event_at, now):
                continue
            r = _row(lead=lead, platform=platform, stage=stage, click=click, event_at=event_at,
                     segment=segment, value=value, sale_id=sale_id)
            out.setdefault(r["dedupe_key"], r)
    return list(out.values())
```

- [ ] **Step 4: Rodar `tests/test_conversions_sweep.py`** — corrigir só expectativas que contavam `google:lead:*` (remover essas chaves do esperado; não mudar outras regras). Esperado: tudo PASS. Rodar também `tests/test_conversions_sender.py` e `tests/test_conversions_eligibility.py` (o sender ainda aceita `lead` em linhas antigas — não mexer).

- [ ] **Step 5: Commit**

```bash
git add backend/app/conversions/sweep.py backend/tests/test_conversions_sweep.py
git commit -m "fix(conversoes): clique (lead) não entra mais na fila — Google já conta pelo site"
```

### Task 3: merge do `master` e suíte completa

- [ ] **Step 1:** `git fetch origin master && git merge --no-edit origin/master` (sem conflito previsto).
- [ ] **Step 2:** suíte do backend inteira na VPS (`<ALVO>` = `tests`). Esperado: 0 falhas.
- [ ] **Step 3:** frontend: `cd frontend && npm ci && npm run type-check && npm run test`. Esperado: 0 erros/falhas.
- [ ] **Step 4:** commit do merge já criado pelo `git merge`.

### Task 4: roteiro de setup

**Files:** Modify `docs/setup/conversoes-ads.md`

- [ ] **Step 1:** atualizar o roteiro com: IDs das 3 ações; etapa lead fora (sem `GOOGLE_ADS_CONVERSION_ACTION_LEAD`); dataset `950217978158864` no portfólio Torrefação (1338125734024745); token Meta = token do canal `meta_cloud` (Sistema_API); regra "Meta só com código ATIVO da aba Testar eventos — código inventado é processado como real"; `ad_conversion_values` vazia (intermediárias sem valor); `eventSource: OTHER`.
- [ ] **Step 2:** commit `docs(conversoes): roteiro com a configuração feita em 13/10`.

### Task 5: validação em modo teste (container descartável na VPS)

- [ ] **Step 1: varredura a seco** — rodar a função de I/O da varredura de `sweep.py` contra o banco de produção num container descartável, com a escrita em `ad_conversions` interceptada (monkeypatch do método de upsert do cliente Supabase para só acumular as linhas numa lista). Imprimir `Counter((r["platform"], r["stage"]) for r in linhas)`. Esperado: nenhuma etapa `lead`; qualificado/oportunidade/venda > 0. Conferir no banco depois: `select count(*) from ad_conversions` continua 0.

- [ ] **Step 2: Google validateOnly** — 1 linha de cada etapa (qualified/opportunity/purchase) da varredura a seco, `CONVERSIONS_TEST_MODE=true`, `google.send(row, lead)` com as variáveis de `/root/.secrets/conversoes-ads.env`. Esperado: `ok=True` nas 3.
- [ ] **Step 3: Meta com código ativo** — pedir ao Rafael a aba Testar eventos aberta e o código atual; `meta.send` em 1 linha de cada etapa com `META_CAPI_TEST_EVENT_CODE=<código>`. Esperado: `events_received: 1` **sem** a mensagem "processed normally"; Rafael vê os 3 na tela. Sem código ativo → pular.
- [ ] **Step 4: print** da aba "Conversões enviadas" (`/trafego`) com o frontend do branch rodando local.
