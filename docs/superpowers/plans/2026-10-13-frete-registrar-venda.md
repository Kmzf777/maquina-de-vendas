# Frete no Registrar venda — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O modal "Registrar venda" (modo Bling) ganha Frete (R$) + Modalidade; o frete vai para o pedido do Bling (`transporte`), soma no total/parcelas, fica gravado em `sales.freight`/`sales.freight_mode` e sobrevive à edição.

**Architecture:** Backend já tem `build_order_payload(freight, freight_mode)` e `order_net_total`. Falta: colunas em `sales`, `OrderIn` aceitar os campos, `update_order` repassar, `create_order` gravar. No front, `buildOrderPayload` (lib pura) soma frete e o põe no payload; `BlingOrderForm` mostra os campos só quando `showFreight`; o modal passa o frete inicial na edição e grava no PATCH.

**Tech Stack:** FastAPI + pytest (backend), Next.js App Router + vitest (frontend), Supabase Postgres.

Spec: `docs/superpowers/specs/2026-10-13-frete-registrar-venda-design.md`.

Tarefas 1 e 2 são independentes (arquivos diferentes). Tarefa 3 depende da 2.

---

### Task 1: Backend — frete no POST/PUT de pedido e coluna em `sales`

**Files:**
- Create: `supabase/migrations/20261013_sales_freight.sql`
- Modify: `backend/app/bling/router.py` (`OrderIn` ~l.77; kwargs do POST ~l.381; kwargs do PUT ~l.467)
- Modify: `backend/app/bling/orders.py` (`update_order` ~l.234; `linha` de `create_order` ~l.475)
- Test: `backend/tests/test_bling_orders.py`, `backend/tests/test_bling_router.py`

- [ ] **Step 1: Migração**

```sql
-- Frete do pedido de venda, guardado à parte para a edição reabrir com ele.
-- Sem isso o PUT no Bling (que manda o pedido inteiro) apagaria o frete.
-- `value` continua sendo o total com frete (order_net_total).
ALTER TABLE sales
  ADD COLUMN IF NOT EXISTS freight numeric(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS freight_mode smallint;
```

- [ ] **Step 2: Testes que falham (orders.py)**

Em `test_bling_orders.py`, seguindo o padrão dos testes existentes de `create_order` (cliente fake + monkeypatch de `_insert_sale`):
- `update_order(..., freight=40.0, freight_mode=0)` → payload enviado no PUT tem `transporte == {"frete": 40.0, "fretePorConta": 0}` e parcelas somando 40.
- `update_order` sem frete → payload sem chave `transporte` (regressão).
- `create_order(..., freight=40.0, freight_mode=1)` → a linha passada a `_insert_sale` tem `freight == 40.0`, `freight_mode == 1` e `value` = itens + 40.
- `create_order` sem frete → `freight == 0.0`, `freight_mode is None`.

- [ ] **Step 3: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_bling_orders.py -q -m "not integration"`
Expected: FAIL (update_order não aceita `freight`; linha sem `freight`).

- [ ] **Step 4: Implementar em orders.py**

`update_order` ganha `freight=0, freight_mode: int | None = None` e repassa a `build_order_payload(..., freight=freight, freight_mode=freight_mode)`. Em `create_order`, na `linha`: `"freight": float(_money(_dec(freight)))`, `"freight_mode": freight_mode`.

- [ ] **Step 5: Testes que falham (router.py)**

Em `test_bling_router.py`, seguindo o padrão dos testes de POST/PUT `/orders` existentes (monkeypatch de `create_order`/`update_order` capturando kwargs):
- POST `/orders` com `freight: 35.5, freight_mode: 1` → `create_order` recebe `freight=35.5`, `freight_mode=1`.
- POST com `freight: -10` → recebe `freight=0` (normalizado).
- POST com `freight_mode: 7` → 422 sem chamar `create_order`.
- PUT `/orders/{id}` com frete → `update_order` recebe os dois.
- Caminho da fila (Bling transitório) → kwargs enfileirados contêm `freight`/`freight_mode`.

- [ ] **Step 6: Implementar em router.py**

```python
class OrderIn(BaseModel):
    ...
    # Frete do pedido (mesma regra do orçamento): negativo vira 0 e a
    # modalidade é o enum `fretePorConta` do Bling.
    freight: float = 0
    freight_mode: int | None = None
```

Helper no router:

```python
from app.quotes.proposals import MODALIDADES_FRETE, normalize_freight

def _frete_do_pedido(body: OrderIn) -> tuple[float, int | None] | JSONResponse:
    if body.freight_mode is not None and body.freight_mode not in MODALIDADES_FRETE:
        return JSONResponse({"error": "freight_mode_invalido",
                             "message": f"modalidade de frete invalida: {body.freight_mode}"},
                            status_code=422)
    return float(normalize_freight(body.freight)), body.freight_mode
```

Chamar no início do POST e do PUT (depois de `_conta_valida`), retornar a resposta se for `JSONResponse`, e incluir `"freight"` e `"freight_mode"` nos dois `kwargs`. (Conferir que importar de `app.quotes.proposals` não cria import circular; se criar, copiar a tupla com comentário apontando a origem.)

- [ ] **Step 7: Rodar e ver passar + suíte backend**

Run: `cd backend && python -m pytest -q -m "not integration"`
Expected: tudo verde.

- [ ] **Step 8: Commit**

```bash
git add supabase/migrations/20261013_sales_freight.sql backend/app/bling backend/tests
git commit -m "feat(vendas): frete no pedido de venda do CRM e em sales.freight"
```

---

### Task 2: Frontend lib — `buildOrderPayload` com frete

**Files:**
- Modify: `frontend/src/lib/bling-order-state.ts`
- Modify: `frontend/src/lib/types.ts` (interface `Sale`)
- Test: `frontend/src/lib/bling-order-state.test.ts`

- [ ] **Step 1: Testes que falham**

```ts
it("soma o frete ao total e às parcelas e o manda no payload", () => {
  const r = buildOrderPayload([linhaCompleta(100)], { ...meta, terms: [30, 60], freight: 50, freightMode: 1 });
  expect(r.total).toBe(150);
  expect(r.installments.map((p) => p.valor)).toEqual([75, 75]);
  expect(r.payload.freight).toBe(50);
  expect(r.payload.freight_mode).toBe(1);
});
it("sem frete: total só dos itens, freight 0 e modalidade null", () => {
  const r = buildOrderPayload([linhaCompleta(100)], meta);
  expect(r.total).toBe(100);
  expect(r.payload.freight).toBe(0);
  expect(r.payload.freight_mode).toBeNull();
});
it("frete negativo vira 0", () => {
  expect(buildOrderPayload([linhaCompleta(100)], { ...meta, freight: -5 }).total).toBe(100);
});
it("frete sem itens não torna o pedido válido", () => {
  expect(buildOrderPayload([], { ...meta, freight: 30 }).valid).toBe(false);
});
```

(Use os helpers/fixtures que o arquivo de teste já tem; `linhaCompleta(v)` = uma linha com produto, qtd 1, valor v. Ajuste o nome do campo da parcela ao de `BlingInstallment`.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd frontend && npx vitest run src/lib/bling-order-state.test.ts`

- [ ] **Step 3: Implementar**

- `OrderMeta` ganha `freight?: number; freightMode?: number | null;`.
- `OrderPayloadResult.payload` ganha `freight: number; freight_mode: number | null;`.
- Em `buildOrderPayload`: `const frete = meta.freight && meta.freight > 0 ? Math.round(meta.freight * 100) / 100 : 0;` e `total = round2(orderTotal(...) + frete)` (frete entra depois dos itens, como `order_net_total` no backend); payload com `freight: frete, freight_mode: meta.freightMode ?? null`.
- `Sale` em `types.ts` ganha `freight?: number | null; freight_mode?: number | null;` com comentário apontando `20261013_sales_freight.sql`.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd frontend && npx vitest run src/lib/bling-order-state.test.ts`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/bling-order-state.ts frontend/src/lib/bling-order-state.test.ts frontend/src/lib/types.ts
git commit -m "feat(vendas): payload do pedido soma e envia o frete"
```

---

### Task 3: Frontend UI — campos no formulário, edição e PATCH

**Files:**
- Modify: `frontend/src/components/sales/bling-order-form.tsx`
- Modify: `frontend/src/components/sales/sale-create-modal.tsx`
- Modify: `frontend/src/app/api/sales/[id]/route.ts` (ALLOWED)
- Test: `frontend/src/components/sales/bling-order-form.test.tsx`

- [ ] **Step 1: Teste que falha (jsdom)**

Em `bling-order-form.test.tsx`, no mesmo padrão dos testes existentes (render com mocks de fetch já usados ali):
- com `showFreight` → existe input com `aria-label="Valor do frete"` e o rótulo "Modalidade do frete";
- sem `showFreight` → o input não existe (orçamento continua igual);
- com `showFreight` e `initialFreight={45}` → input nasce com "45" e o `onChange` recebe `payload.freight === 45`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd frontend && npx vitest run src/components/sales/bling-order-form.test.tsx`

- [ ] **Step 3: Implementar no BlingOrderForm**

Props novas:
```ts
/** Mostra Frete (R$) + Modalidade. Só o Registrar venda liga; o orçamento
 *  tem o próprio campo de frete e passa os itens sem ele. */
showFreight?: boolean;
/** Frete com que o formulário nasce (edição de venda que já tem frete). */
initialFreight?: number | null;
initialFreightMode?: number | null;
```
Estado `freteTexto` (string, inicial `initialFreight ? String(initialFreight) : ""`) e `freteModalidade` (`initialFreightMode ?? null`). No `useMemo` do `result`: `freight: showFreight ? parseDecimalInput(freteTexto) : 0, freightMode: showFreight ? freteModalidade : null` (+ deps). Importar `FREIGHT_MODES` e `parseDecimalInput` de `@/lib/quote-modal-state`.
UI: depois do bloco de itens/total e antes de "Pagamento", quando `showFreight`, um `grid grid-cols-2 gap-3` com "Frete (R$)" (input texto, `inputMode="decimal"`, placeholder "0,00", `aria-label="Valor do frete"`, classe `control`) e "Modalidade do frete" (Select com "Não informar" + `FREIGHT_MODES`), copiando o markup do `quote-create-modal.tsx` (~l.565-598) e as classes deste arquivo (`label`, select trigger igual ao de forma de pagamento). Se o total exibido ao lado dos itens usa `result.total`, mostrar uma linha "Frete R$ x" quando > 0 para o vendedor entender o total.

- [ ] **Step 4: Modal**

Em `sale-create-modal.tsx`, no `<BlingOrderForm>`: `showFreight`, `initialFreight={isEditing ? editingSale?.freight ?? 0 : undefined}`, `initialFreightMode={isEditing ? editingSale?.freight_mode ?? null : undefined}`. Em `saveLocalAfterBlingPut`, incluir no body do PATCH `freight: payload.freight, freight_mode: payload.freight_mode`.

- [ ] **Step 5: Rota PATCH**

Em `app/api/sales/[id]/route.ts`, adicionar `"freight"` e `"freight_mode"` ao `ALLOWED`.

- [ ] **Step 6: Rodar testes + suíte + lint + build**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`
Expected: tudo verde (falhas pré-existentes na master devem ser comparadas com a master antes de concluir).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/sales frontend/src/app/api/sales
git commit -m "feat(vendas): campo de frete no Registrar venda, mantido na edicao"
```

---

### Task 4: Publicação e verificação (controlador, não subagente)

- [ ] Push do branch `agente/1a586e44` para o GitHub.
- [ ] Aplicar a migração na VPS (`supabase_db`, psql) — só `ADD COLUMN IF NOT EXISTS`; conferir colunas por SELECT em `information_schema.columns`.
- [ ] Deploy = push para `master` (CLAUDE.md): só com autorização do Rafael.
- [ ] Depois do deploy: `docker service ls`/logs, print do modal, venda de teste com frete conferida no Bling e por SELECT.
