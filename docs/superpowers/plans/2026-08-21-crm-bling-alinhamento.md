# Alinhamento CRM ↔ Bling — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o CRM refletir o Bling nas cinco superfícies onde hoje ele não reflete — modal de venda, leads, situação do pedido, catálogo e edição de venda.

**Architecture:** Lógica de decisão vive em funções puras sob `frontend/src/lib/*.ts`, testadas por `vitest`; componentes React só as consomem. O backend segue o padrão existente do módulo `app/bling/`: toda chamada ao Bling passa pelo `BlingClient`, leitura de catálogo sai do espelho no Postgres, nunca da API.

**Tech Stack:** FastAPI + Supabase (Postgres) no backend, Next.js 15 (App Router) + React no frontend, `vitest` no frontend e `pytest` no backend.

---

## Contexto que o executor precisa saber

**O vitest do frontend roda em `environment: "node"` e só inclui `src/**/*.test.ts`.**
Não existe `@testing-library/react` nem jsdom no projeto, e nenhum arquivo
`.test.tsx`. **Não adicione essa infraestrutura.** O padrão do projeto é extrair a
decisão para uma função pura em `lib/` e testá-la lá — é exatamente o que
`lib/sale-display.ts`, `lib/bling-order-state.ts` e `lib/bling-contact-form.ts`
fazem. Componentes ficam finos e sem teste próprio.

**Backend:** `cd backend && python -m pytest -q`. Os testes usam dublês do Supabase.
**Frontend:** `cd frontend && npx vitest run <arquivo>` para um arquivo, `npm test`
para tudo.

**Nunca** rode migration só com o dublê: aplique contra o Postgres real e verifique.
A lição do `42P10` (commit `09497172`) é que dublê de Supabase não modela inferência
de `ON CONFLICT`.

---

## FASE A — Ligar o modo Bling no modal

### Task 1: Função pura que decide o modo

**Files:**
- Create: `frontend/src/lib/bling-gate.ts`
- Test: `frontend/src/lib/bling-gate.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
// frontend/src/lib/bling-gate.test.ts
import { describe, it, expect } from "vitest";
import { blingGate } from "@/lib/bling-gate";

describe("blingGate", () => {
  it("enquanto carrega, nao decide nada e bloqueia o envio", () => {
    const g = blingGate({ loading: true, error: null, enabled: null, isEditing: false });
    expect(g.mode).toBe("loading");
    expect(g.canSubmit).toBe(false);
  });

  it("Bling ligado entra em modo bling", () => {
    const g = blingGate({ loading: false, error: null, enabled: true, isEditing: false });
    expect(g.mode).toBe("bling");
    expect(g.canSubmit).toBe(true);
  });

  it("Bling desligado cai no modo legado", () => {
    const g = blingGate({ loading: false, error: null, enabled: false, isEditing: false });
    expect(g.mode).toBe("legacy");
    expect(g.canSubmit).toBe(true);
  });

  it("editar venda continua legado mesmo com Bling ligado (Fase E muda isso)", () => {
    const g = blingGate({ loading: false, error: null, enabled: true, isEditing: true });
    expect(g.mode).toBe("legacy");
  });

  // O teste que da nome a fase: falhar NAO pode virar venda avulsa silenciosa.
  it("falha ao consultar o status BLOQUEIA, nunca cai no legado", () => {
    const g = blingGate({ loading: false, error: "timeout", enabled: null, isEditing: false });
    expect(g.mode).toBe("error");
    expect(g.canSubmit).toBe(false);
    expect(g.message).toContain("Bling");
  });

  it("falha durante edicao nao bloqueia: edicao nao toca no ERP nesta fase", () => {
    const g = blingGate({ loading: false, error: "timeout", enabled: null, isEditing: true });
    expect(g.mode).toBe("legacy");
    expect(g.canSubmit).toBe(true);
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/bling-gate.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/bling-gate"`

- [ ] **Step 3: Implementar**

```ts
// frontend/src/lib/bling-gate.ts
/**
 * Decide em que modo o modal de venda opera.
 *
 * Existe como funcao pura porque a regra tem uma consequencia que precisa de
 * teste: quando a consulta a `/api/bling/status` FALHA, o modal bloqueia em vez
 * de cair no modo legado. Cair no legado reintroduziria o defeito que esta fase
 * conserta (venda avulsa entrando no CRM sem ninguem perceber), so que
 * intermitente. Falha de rede e transitoria; venda gravada fora do ERP e
 * permanente.
 */
export type BlingMode = "loading" | "bling" | "legacy" | "error";

export interface BlingGateInput {
  loading: boolean;
  error: string | null;
  enabled: boolean | null;
  isEditing: boolean;
}

export interface BlingGate {
  mode: BlingMode;
  canSubmit: boolean;
  message?: string;
}

export function blingGate({ loading, error, enabled, isEditing }: BlingGateInput): BlingGate {
  // Editar venda e PATCH local: nao toca no ERP nesta fase, entao nem o
  // carregamento nem a falha do status importam.
  if (isEditing) return { mode: "legacy", canSubmit: true };

  if (loading) return { mode: "loading", canSubmit: false };

  if (error) {
    return {
      mode: "error",
      canSubmit: false,
      message:
        "Nao foi possivel confirmar a conexao com o Bling. " +
        "Registrar agora criaria uma venda fora do ERP, entao o envio esta bloqueado.",
    };
  }

  return enabled ? { mode: "bling", canSubmit: true } : { mode: "legacy", canSubmit: true };
}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd frontend && npx vitest run src/lib/bling-gate.test.ts`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/bling-gate.ts frontend/src/lib/bling-gate.test.ts
git commit -m "feat(bling): funcao pura que decide o modo do modal de venda"
```

---

### Task 2: Hook que busca o status

**Files:**
- Create: `frontend/src/hooks/use-bling-status.ts`

Sem teste próprio: é I/O fino sobre `fetch`, e a regra que importa já está testada
na Task 1. Segue o formato de `hooks/use-current-role.ts`.

- [ ] **Step 1: Implementar**

```ts
// frontend/src/hooks/use-bling-status.ts
"use client";

import { useState, useEffect } from "react";

/**
 * Estado da integracao Bling, lido de `/api/bling/status`.
 *
 * Cache em memoria compartilhado entre chamadores: os quatro pontos que abrem o
 * modal de venda montam em telas diferentes, e sem isso cada abertura repetiria
 * a chamada. `enabled` fica `null` enquanto nao se sabe — quem decide o que
 * fazer com isso e `blingGate`, nao este hook.
 */
export interface BlingStatusState {
  enabled: boolean | null;
  loading: boolean;
  error: string | null;
}

let cache: { enabled: boolean } | null = null;
let inflight: Promise<{ enabled: boolean }> | null = null;

async function fetchStatus(): Promise<{ enabled: boolean }> {
  if (cache) return cache;
  if (!inflight) {
    inflight = fetch("/api/bling/status", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`status ${r.status}`);
        const body = (await r.json()) as { enabled?: boolean; connected?: boolean };
        // `enabled` e o toggle BLING_ENABLED; `connected` diz se ha refresh_token.
        // Modo Bling exige os dois: ligado mas sem OAuth so produziria 401 na cara
        // do vendedor no meio do registro.
        const ok = !!body.enabled && !!body.connected;
        cache = { enabled: ok };
        return cache;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function useBlingStatus(): BlingStatusState {
  const [state, setState] = useState<BlingStatusState>(
    cache ? { enabled: cache.enabled, loading: false, error: null }
          : { enabled: null, loading: true, error: null }
  );

  useEffect(() => {
    if (cache) return;
    let vivo = true;
    fetchStatus()
      .then((s) => vivo && setState({ enabled: s.enabled, loading: false, error: null }))
      .catch((e) => vivo && setState({ enabled: null, loading: false, error: String(e) }));
    return () => {
      vivo = false;
    };
  }, []);

  return state;
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npm run type-check`
Expected: sem erros

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/use-bling-status.ts
git commit -m "feat(bling): hook de status compartilhado entre os chamadores do modal"
```

---

### Task 3: Ligar o modal (os quatro chamadores nao mudam)

**Files:**
- Modify: `frontend/src/components/sales/sale-create-modal.tsx:93`
- Modify: `frontend/src/app/(authenticated)/painel-vendas/page.tsx:113`
- Modify: `frontend/src/components/deals/deal-detail-sidebar.tsx:257`
- Modify: `frontend/src/components/conversas/contact-detail.tsx:278`
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx:640`

- [ ] **Step 1: Trocar a decisão dentro do modal**

Em `sale-create-modal.tsx`, importe o hook e a função e substitua a linha 93.

```ts
import { useBlingStatus } from "@/hooks/use-bling-status";
import { blingGate } from "@/lib/bling-gate";
```

```ts
// ANTES (linha 93):
//   const blingMode = !!blingEnabled && !isEditing;
// DEPOIS:
const blingStatus = useBlingStatus();
const gate = blingGate({
  loading: blingStatus.loading,
  error: blingStatus.error,
  // A prop continua existindo e VENCE quando informada: os testes e quem quiser
  // forcar o modo nao passam a depender de rede.
  enabled: blingEnabled ?? blingStatus.enabled,
  isEditing,
});
const blingMode = gate.mode === "bling";
```

- [ ] **Step 2: Refletir `gate` no botão de envio**

Na linha ~718, o `disabled` do botão passa a considerar o gate:

```tsx
disabled={saving || !gate.canSubmit || (blingMode && !orderResult?.valid)}
```

E logo acima da barra de botões, renderize a mensagem quando houver:

```tsx
{gate.message && (
  <p className="text-[13px] text-[#b42318] mb-3">{gate.message}</p>
)}
```

- [ ] **Step 3: Passar nada nos quatro chamadores**

Nenhuma mudança é necessária nos quatro chamadores: com `blingEnabled ?? blingStatus.enabled`,
omitir a prop faz o hook decidir. Confirme que os quatro continuam **sem** passar
`blingEnabled` e que isso agora significa "pergunte ao backend", não "modo legado".

Run: `grep -rn "blingEnabled" frontend/src/app frontend/src/components`
Expected: só as ocorrências dentro de `sale-create-modal.tsx`

- [ ] **Step 4: Type-check, lint e suíte**

Run: `cd frontend && npm run type-check && npm run lint && npm test`
Expected: tudo verde

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sales/sale-create-modal.tsx
git commit -m "fix(bling): modal de venda entra em modo Bling de verdade"
```

---

## FASE C — Nome da situação do pedido

### Task 4: Provar a resposta real de `/situacoes/modulos`

**Files:** nenhum. Task de verificação — **não escreva parser antes dela.**

Pré-requisito humano: o escopo de Situações precisa estar marcado no aplicativo do
Bling e o OAuth refeito. Sem isso o endpoint devolve 403.

- [ ] **Step 1: Chamar o endpoint com o token de produção**

```bash
DBCID=$(docker ps -q --filter "name=supabase_db")
TOKEN=$(docker exec -i $DBCID psql -U postgres -tAc \
  "SELECT access_token FROM bling_credentials WHERE id='default';")
curl -sS https://api.bling.com.br/Api/v3/situacoes/modulos \
  -H "Authorization: Bearer $TOKEN" -H "enable-jwt: 1" -H "Accept: application/json" \
  | python3 -m json.tool | head -40
```

Expected: HTTP 200 com uma lista de módulos. **Se vier 403, pare** — o escopo não
foi aplicado, e nada abaixo desta task funciona.

- [ ] **Step 2: Listar as situações do módulo de pedidos de venda**

Com o `id` do módulo de vendas obtido acima:

```bash
curl -sS "https://api.bling.com.br/Api/v3/situacoes/modulos/<ID_DO_MODULO>" \
  -H "Authorization: Bearer $TOKEN" -H "enable-jwt: 1" -H "Accept: application/json" \
  | python3 -m json.tool | head -40
```

Expected: lista contendo os ids `6` e `9`, que são os observados nos pedidos reais.

- [ ] **Step 3: Registrar o formato observado**

Anote em `docs/setup/bling-observacoes-producao.md`, na seção da pendência de
`bling_situacao_nome`, o nome exato dos campos (`id`, `nome`/`descricao`, e como o
módulo é identificado). As tasks seguintes usam esses nomes.

- [ ] **Step 4: Commit**

```bash
git add docs/setup/bling-observacoes-producao.md
git commit -m "docs(bling): formato real de /situacoes/modulos"
```

---

### Task 5: Espelho `bling_situacoes`

**Files:**
- Create: `supabase/migrations/20260821_bling_situacoes.sql`
- Modify: `backend/app/bling/sync.py`
- Test: `backend/tests/test_bling_sync.py`

- [ ] **Step 1: Escrever a migration**

```sql
-- supabase/migrations/20260821_bling_situacoes.sql
--
-- Espelho das situacoes de pedido. Existe porque o nome da situacao NAO vem no
-- pedido nem no webhook — os dois trazem so `{id, valor}`. Sem este espelho,
-- `sales.bling_situacao_nome` fica nulo e /painel-vendas mostra "Registrada"
-- para todo pedido, qualquer que seja a situacao real no ERP.
CREATE TABLE IF NOT EXISTS bling_situacoes (
  id        bigint PRIMARY KEY,
  nome      text NOT NULL,
  modulo_id bigint,
  synced_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE bling_situacoes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bling_situacoes_select ON bling_situacoes;
CREATE POLICY bling_situacoes_select ON bling_situacoes
  FOR SELECT TO authenticated, service_role USING (true);
```

- [ ] **Step 2: Escrever o teste que falha**

Acrescente a `backend/tests/test_bling_sync.py` (siga o formato dos dublês já
usados no arquivo para `sync_sellers`):

```python
async def test_sync_situacoes_grava_id_nome_e_modulo():
    client = FakeClient(pages={
        "/situacoes/modulos": [{"id": 10, "descricao": "Pedidos de Venda"}],
        "/situacoes/modulos/10": [
            {"id": 6, "nome": "Em aberto"},
            {"id": 9, "nome": "Atendido"},
        ],
    })
    total = await sync.sync_situacoes(client)
    assert total == 2
    gravados = {r["id"]: r["nome"] for r in fake_supabase.upserts["bling_situacoes"]}
    assert gravados == {6: "Em aberto", 9: "Atendido"}
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_sync.py -k situacoes -q`
Expected: FAIL — `AttributeError: module 'app.bling.sync' has no attribute 'sync_situacoes'`

- [ ] **Step 4: Implementar `sync_situacoes`**

Em `backend/app/bling/sync.py`, ao lado de `sync_sellers`. **Use os nomes de campo
observados na Task 4** — o exemplo abaixo assume `descricao` no módulo e `nome` na
situação; corrija se a Task 4 mostrou outra coisa.

```python
async def sync_situacoes(client) -> int:
    """Espelha as situacoes dos modulos de venda.

    Duas chamadas: a lista de modulos e, para cada modulo de pedido de venda, as
    situacoes dele. O nome do modulo e casado de forma tolerante porque a
    descricao e texto do painel, nao enum estavel.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    async for modulo in client.paginate("/situacoes/modulos", {}):
        descricao = (modulo.get("descricao") or "").lower()
        if "venda" not in descricao:
            continue
        modulo_id = int(modulo["id"])
        async for sit in client.paginate(f"/situacoes/modulos/{modulo_id}", {}):
            rows.append({
                "id": int(sit["id"]),
                "nome": sit.get("nome") or sit.get("descricao") or "",
                "modulo_id": modulo_id,
                "synced_at": started_at,
            })
    await _upsert("bling_situacoes", rows)
    await asyncio.to_thread(_save_sync_state, "situacoes", last_sync_at=started_at)
    logger.info("[BLING] situacoes sincronizadas: %d", len(rows))
    return len(rows)
```

E acrescente ao `sync_all`, depois de `sync_sellers`:

```python
        situacoes = await sync_situacoes(client)
    return {"produtos": produtos, "contatos": contatos,
            "formas_pagamento": formas, "vendedores": vendedores,
            "situacoes": situacoes}
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_sync.py -q`
Expected: PASS

- [ ] **Step 6: Aplicar a migration no Postgres real e verificar**

```bash
docker cp supabase/migrations/20260821_bling_situacoes.sql \
  $(docker ps -q -f name=supabase_db):/tmp/sit.sql
docker exec $(docker ps -q -f name=supabase_db) \
  psql -U postgres -v ON_ERROR_STOP=1 --single-transaction -f /tmp/sit.sql
docker exec $(docker ps -q -f name=supabase_db) psql -U postgres -c "\d bling_situacoes"
```

Expected: tabela criada, com a policy de SELECT.

- [ ] **Step 7: Commit**

```bash
git add supabase/migrations/20260821_bling_situacoes.sql backend/app/bling/sync.py backend/tests/test_bling_sync.py
git commit -m "feat(bling): espelho de situacoes de pedido"
```

---

### Task 6: Preencher `bling_situacao_nome`

**Files:**
- Modify: `backend/app/bling/orders.py:475` (e o bloco de `create_order` por volta de :387)
- Test: `backend/tests/test_bling_orders.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_upsert_from_bling_preenche_nome_da_situacao():
    fake_supabase.tables["bling_situacoes"] = [{"id": 6, "nome": "Em aberto"}]
    await orders.upsert_from_bling(
        {"id": 1, "numero": 10, "total": 100, "situacao": {"id": 6}, "data": "2026-08-20"},
        lead_id="lead-1", event_date=None,
    )
    linha = fake_supabase.upserts["sales"][-1]
    assert linha["bling_situacao_id"] == 6
    assert linha["bling_situacao_nome"] == "Em aberto"


async def test_situacao_ausente_do_espelho_nao_quebra_a_projecao():
    fake_supabase.tables["bling_situacoes"] = []
    await orders.upsert_from_bling(
        {"id": 2, "numero": 11, "total": 50, "situacao": {"id": 99}, "data": "2026-08-20"},
        lead_id="lead-1", event_date=None,
    )
    linha = fake_supabase.upserts["sales"][-1]
    assert linha["bling_situacao_id"] == 99
    assert linha["bling_situacao_nome"] is None
```

O segundo teste é o que importa: situação nova criada no painel do Bling e ainda
não sincronizada **não pode** derrubar o processamento do webhook.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_orders.py -k situacao -q`
Expected: FAIL — `bling_situacao_nome` ausente ou `KeyError`

- [ ] **Step 3: Implementar**

Em `orders.py`, acrescente o lookup:

```python
def _situacao_nome(situacao_id: int | None) -> str | None:
    """Nome da situacao a partir do espelho. Ausencia devolve None, nunca levanta:
    situacao criada no painel e ainda nao sincronizada nao pode derrubar o
    processamento do webhook."""
    if not situacao_id:
        return None
    res = (get_supabase().table("bling_situacoes").select("nome")
           .eq("id", situacao_id).limit(1).maybe_single().execute())
    return (getattr(res, "data", None) or {}).get("nome")
```

Em `upsert_from_bling`, ao lado de `bling_situacao_id` (linha ~475):

```python
        "bling_situacao_id": (pedido.get("situacao") or {}).get("id"),
        "bling_situacao_nome": await asyncio.to_thread(
            _situacao_nome, (pedido.get("situacao") or {}).get("id")
        ),
```

Faça o mesmo no bloco de `create_order` (linha ~387), onde `bling_situacao_id` já é
gravado a partir do `detalhe`.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_orders.py -q`
Expected: PASS

- [ ] **Step 5: Sincronizar e conferir em produção**

```bash
curl -sS -X POST "https://api.canastrainteligencia.com/api/bling/sync"
docker exec -i $(docker ps -q -f name=supabase_db) psql -U postgres -c \
  "SELECT bling_order_number, bling_situacao_id, bling_situacao_nome
     FROM sales WHERE bling_order_id IS NOT NULL ORDER BY bling_order_number LIMIT 5;"
```

Expected: `bling_situacao_nome` preenchido nas vendas novas. Vendas já gravadas só
mudam quando um novo evento do pedido chegar — isso é esperado.

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/orders.py backend/tests/test_bling_orders.py
git commit -m "fix(bling): situacao do pedido aparece com nome em /painel-vendas"
```

---

## FASE B — Superfície Bling nos leads

### Task 7: Busca de contatos e desvincular no backend

**Files:**
- Modify: `backend/app/bling/router.py`
- Modify: `backend/app/bling/contacts.py`
- Test: `backend/tests/test_bling_router.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
def test_busca_de_contato_sanitiza_o_termo():
    # Virgula e parentese COMPOEM a sintaxe do filtro `or` do PostgREST: sem
    # neutralizar, o resto do texto vira filtro.
    assert router._termo_seguro("Ltda, (ME)") == "Ltda   ME"


async def test_unlink_limpa_o_vinculo_do_lead():
    fake_supabase.tables["leads"] = [{"id": "lead-1", "bling_contact_id": 42}]
    await contacts.unlink("lead-1")
    assert fake_supabase.updates["leads"][-1]["bling_contact_id"] is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_router.py -k "termo_seguro or unlink" -q`
Expected: FAIL — `contacts.unlink` não existe

- [ ] **Step 3: Implementar `unlink` em `contacts.py`**

```python
def _unlink(lead_id: str) -> None:
    (get_supabase().table("leads")
     .update({"bling_contact_id": None}).eq("id", lead_id).execute())


async def unlink(lead_id: str) -> None:
    """Desfaz o vinculo. Verbo proprio, e nao `link` com nulo, porque desvincular
    tem consequencia diferente: a proxima venda do lead volta a cair na resolucao
    por documento, e um nulo acidental no payload de `link` nao pode ser capaz de
    apagar vinculo em silencio."""
    await asyncio.to_thread(_unlink, lead_id)
```

- [ ] **Step 4: Implementar os endpoints em `router.py`**

```python
def _query_contacts(q: str | None, limit: int):
    query = (get_supabase().table("bling_contacts")
             .select("id, nome, fantasia, doc_digits, telefone_e164, celular_e164, "
                     "email, situacao, endereco"))
    if q:
        alvo = f"%{_termo_seguro(q)}%"
        query = query.or_(f"nome.ilike.{alvo},fantasia.ilike.{alvo},doc_digits.ilike.{alvo}")
    return getattr(query.order("nome").limit(limit).execute(), "data", None) or []


@router.get("/contacts/search")
async def search_contacts(q: str | None = Query(None), limit: int = Query(20, le=100)):
    """Busca no ESPELHO, nunca no Bling — o campo dispara a cada tecla."""
    return {"data": await asyncio.to_thread(_query_contacts, q, limit)}


@router.post("/contacts/unlink")
async def unlink_contact_endpoint(lead_id: str):
    await contacts.unlink(lead_id)
    return {"unlinked": True}
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_router.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/bling/router.py backend/app/bling/contacts.py backend/tests/test_bling_router.py
git commit -m "feat(bling): busca de contato no espelho e desvincular"
```

---

### Task 8: Proxies do Next

**Files:**
- Create: `frontend/src/app/api/bling/contacts/search/route.ts`
- Create: `frontend/src/app/api/bling/contacts/unlink/route.ts`

- [ ] **Step 1: Criar os proxies**

Siga exatamente o formato de `frontend/src/app/api/bling/sellers/route.ts` (que já
existe): repassa para `${backend()}/api/bling/...` com `cache: "no-store"` e
devolve o corpo e o status originais.

```ts
// frontend/src/app/api/bling/contacts/search/route.ts
import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/backend";

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams.get("q") ?? "";
  const resp = await fetch(
    `${backend()}/api/bling/contacts/search?q=${encodeURIComponent(q)}`,
    { cache: "no-store" }
  );
  return NextResponse.json(await resp.json(), { status: resp.status });
}
```

```ts
// frontend/src/app/api/bling/contacts/unlink/route.ts
import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/backend";

export async function POST(req: NextRequest) {
  const { lead_id } = (await req.json()) as { lead_id: string };
  const resp = await fetch(
    `${backend()}/api/bling/contacts/unlink?lead_id=${encodeURIComponent(lead_id)}`,
    { method: "POST", cache: "no-store" }
  );
  return NextResponse.json(await resp.json(), { status: resp.status });
}
```

Confirme o nome real do helper de URL do backend antes de escrever:
`grep -n "backend()" frontend/src/app/api/bling/sellers/route.ts`

- [ ] **Step 2: Type-check e commit**

Run: `cd frontend && npm run type-check`

```bash
git add frontend/src/app/api/bling/contacts
git commit -m "feat(bling): proxies de busca e desvinculo de contato"
```

---

### Task 9: Seção Bling no detalhe do lead e selo de origem

**Files:**
- Create: `frontend/src/components/leads/lead-bling-section.tsx`
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx`
- Modify: a tabela/lista de leads, para o selo de origem

Componente separado, e não mais um bloco dentro de `lead-detail-modal.tsx`: esse
arquivo já tem mais de 640 linhas, e a seção tem estado próprio (busca, seleção).

- [ ] **Step 1: Criar `lead-bling-section.tsx`**

Props: `{ leadId: string; blingContactId: number | null; onChanged: () => void }`.

Comportamento:
- Com `blingContactId`: busca `/api/bling/contacts/search?q=` não é usada; mostra os
  dados do contato (obtidos de `/api/bling/contacts/search` filtrando pelo doc, ou
  de um GET direto se preferir criar um) — razão social, CNPJ, telefone, e-mail,
  endereço — mais link `https://www.bling.com.br/contatos.php#edit/{id}` e botão
  "Desvincular" que chama `/api/bling/contacts/unlink`.
- Sem `blingContactId`: campo de busca com debounce (use `@/lib/debounce`, que já
  existe) contra `/api/bling/contacts/search`, lista de resultados, e botão
  "Vincular" que chama `/api/bling/contacts/link`.
- Depois de vincular ou desvincular, chama `onChanged()`.

- [ ] **Step 2: Montar no modal do lead**

Em `lead-detail-modal.tsx`, renderize `<LeadBlingSection ... />` numa seção nova,
passando `lead.bling_contact_id` e um `onChanged` que refaz o fetch do lead.

- [ ] **Step 3: Selo de origem na lista de leads**

Onde a lista de leads renderiza cada linha, acrescente um selo quando
`lead.channel === "bling"`. `ensure_lead` já grava esse valor — não há migration.

- [ ] **Step 4: Type-check, lint, suíte**

Run: `cd frontend && npm run type-check && npm run lint && npm test`
Expected: tudo verde

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/leads
git commit -m "feat(bling): vinculo com o Bling no detalhe do lead"
```

---

## FASE D — Tela de produtos

### Task 10: Endpoint paginado de produtos

**Files:**
- Modify: `backend/app/bling/router.py`
- Test: `backend/tests/test_bling_router.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
async def test_catalogo_pagina_de_verdade_e_devolve_total():
    fake_supabase.tables["bling_products"] = [
        {"id": i, "nome": f"Produto {i}", "situacao": "A"} for i in range(1, 51)
    ]
    pagina2 = await router.list_catalog(q=None, situacao=None, page=2, limit=20)
    assert len(pagina2["data"]) == 20
    assert pagina2["page"] == 2
    assert pagina2["total"] == 50
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_router.py -k catalogo -q`
Expected: FAIL — `router.list_catalog` não existe

- [ ] **Step 3: Implementar**

```python
def _query_catalog(q: str | None, situacao: str | None, page: int, limit: int):
    """Catalogo completo, paginado. Diferente de `_query_products`, que fixa
    situacao='A' e teto de 200 porque nasceu para um combobox.

    A paginacao e explicita de proposito: o PostgREST corta em 1000 linhas por
    padrao, e um catalogo maior que isso viraria truncamento silencioso."""
    inicio = (page - 1) * limit
    query = (get_supabase().table("bling_products")
             .select("id, codigo, nome, preco, unidade, situacao, saldo_virtual, "
                     "imagem_url", count="exact"))
    if situacao:
        query = query.eq("situacao", situacao)
    if q:
        alvo = f"%{_termo_seguro(q)}%"
        query = query.or_(f"nome.ilike.{alvo},codigo.ilike.{alvo}")
    res = query.order("nome").range(inicio, inicio + limit - 1).execute()
    return getattr(res, "data", None) or [], getattr(res, "count", None) or 0


@router.get("/catalog")
async def list_catalog(q: str | None = Query(None), situacao: str | None = Query(None),
                       page: int = Query(1, ge=1), limit: int = Query(50, le=200)):
    data, total = await asyncio.to_thread(_query_catalog, q, situacao, page, limit)
    return {"data": data, "page": page, "limit": limit, "total": total}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_router.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/router.py backend/tests/test_bling_router.py
git commit -m "feat(bling): endpoint paginado do catalogo"
```

---

### Task 11: Página `/produtos`

**Files:**
- Create: `frontend/src/app/(authenticated)/produtos/page.tsx`
- Create: `frontend/src/app/api/bling/catalog/route.ts`

- [ ] **Step 1: Criar o proxy**

Mesmo formato da Task 8, repassando `q`, `situacao`, `page` e `limit`.

- [ ] **Step 2: Criar a página**

Tabela somente leitura: código, nome, preço, unidade, saldo, situação. Campo de
busca com debounce, filtro de situação (Ativo/Inativo/Todos) e paginação usando
`total` devolvido pelo endpoint. Siga o visual de `components/sales/sales-table.tsx`
(mesmas classes de cabeçalho e célula) para não introduzir um segundo estilo de
tabela.

- [ ] **Step 3: Entrada no menu**

Acrescente `/produtos` à navegação, junto de onde `/painel-vendas` aparece.

- [ ] **Step 4: Type-check, lint, suíte, commit**

Run: `cd frontend && npm run type-check && npm run lint && npm test`

```bash
git add frontend/src/app
git commit -m "feat(bling): tela de catalogo de produtos"
```

---

## FASE E — Editar venda reflete no Bling

### Task 12: Colunas de divergência

**Files:**
- Create: `supabase/migrations/20260821_sales_divergencia_bling.sql`

- [ ] **Step 1: Escrever a migration**

```sql
-- supabase/migrations/20260821_sales_divergencia_bling.sql
--
-- Edicao recusada pelo Bling (tipicamente pedido ja faturado) pode valer no CRM,
-- mas nunca em silencio: divergencia silenciosa entre CRM e ERP e exatamente o
-- que a integracao existe para evitar. Estas colunas tornam a escolha auditavel.
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_divergent  boolean NOT NULL DEFAULT false;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS bling_divergence jsonb;

CREATE INDEX IF NOT EXISTS sales_bling_divergent_idx
  ON sales (bling_divergent) WHERE bling_divergent;
```

- [ ] **Step 2: Aplicar no Postgres real e verificar**

```bash
docker cp supabase/migrations/20260821_sales_divergencia_bling.sql \
  $(docker ps -q -f name=supabase_db):/tmp/div.sql
docker exec $(docker ps -q -f name=supabase_db) \
  psql -U postgres -v ON_ERROR_STOP=1 --single-transaction -f /tmp/div.sql
docker exec $(docker ps -q -f name=supabase_db) psql -U postgres -c \
  "SELECT count(*) FROM sales WHERE bling_divergent;"
```

Expected: `0` — nenhuma venda nasce divergente.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260821_sales_divergencia_bling.sql
git commit -m "feat(bling): colunas de divergencia em sales"
```

---

### Task 13: `update_order` no backend

**Files:**
- Modify: `backend/app/bling/orders.py`
- Modify: `backend/app/bling/router.py`
- Test: `backend/tests/test_bling_orders.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_update_order_manda_put_para_o_pedido():
    client = FakeClient()
    await orders.update_order(client, order_id=123, contact_id=1,
                              sold_at="2026-08-20", itens=[ITEM], payment=PAGAMENTO,
                              seller_id=None, notes="")
    assert client.puts[-1][0] == "/pedidos/vendas/123"


async def test_recusa_de_validacao_sobe_como_BlingValidationError():
    client = FakeClient(put_raises=BlingValidationError(
        "Pedido faturado", type_="VALIDATION_ERROR", description="", status=400, payload={}))
    with pytest.raises(BlingValidationError):
        await orders.update_order(client, order_id=123, contact_id=1,
                                  sold_at="2026-08-20", itens=[ITEM], payment=PAGAMENTO,
                                  seller_id=None, notes="")
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_bling_orders.py -k update_order -q`
Expected: FAIL — `orders.update_order` não existe

- [ ] **Step 3: Implementar**

```python
async def update_order(client, *, order_id: int, contact_id: int, sold_at: str,
                       itens: list[dict], payment: dict, seller_id: int | None,
                       notes: str) -> dict:
    """Altera o pedido no Bling. Reaproveita o mesmo payload do POST.

    Nao trata a recusa: quem chama e que decide o que fazer com ela. A distincao
    importa — recusa de validacao (pedido faturado) e decisao de negocio, erro
    transitorio e retentativa.
    """
    payload = build_order_payload(
        contact_id=contact_id, sold_at=sold_at, itens=itens,
        payment=payment, seller_id=seller_id, notes=notes,
    )
    return await client.put(f"/pedidos/vendas/{order_id}", payload)
```

E no `router.py`:

```python
@router.put("/orders/{order_id}")
async def update_order_endpoint(order_id: int, body: OrderIn):
    """422 quando o Bling recusa (pedido faturado) — a UI pergunta se salva local.
    202 quando o erro e transitorio: ai NAO e divergencia, e retentativa."""
    from app.bling.client import BlingClient

    # Mesma completude de item do POST: descricao e obrigatoria no Bling mesmo
    # com produto.id, entao o que faltar vem do espelho.
    itens = [{
        "bling_product_id": i.bling_product_id,
        "codigo": i.codigo,
        "descricao": i.descricao or "",
        "unidade": i.unidade,
        "quantidade": i.quantidade,
        "valor_unitario": i.valor_unitario,
        "desconto_percentual": i.desconto_percentual,
    } for i in body.items]
    faltando = [i for i in itens if not i["descricao"]]
    if faltando:
        por_id = await asyncio.to_thread(
            _products_by_id, [i["bling_product_id"] for i in faltando]
        )
        for item in faltando:
            p = por_id.get(item["bling_product_id"]) or {}
            item["descricao"] = p.get("nome") or "Item"
            item["codigo"] = item["codigo"] or p.get("codigo")
            item["unidade"] = item["unidade"] or p.get("unidade")

    kwargs = {
        "contact_id": (await contacts.resolve(
            await asyncio.to_thread(_load_lead, body.lead_id))).contact_id,
        "sold_at": body.sold_at,
        "itens": itens,
        "payment": {"method_id": body.payment.method_id, "terms": body.payment.terms},
        "seller_id": await asyncio.to_thread(_seller_id_for, body.sold_by),
        "notes": body.notes,
    }

    try:
        async with BlingClient() as client:
            out = await update_order(client, order_id=order_id, **kwargs)
    except BlingValidationError as exc:
        return JSONResponse({"error": "validation", "message": str(exc),
                             "detail": exc.description, "type": exc.type},
                            status_code=422)
    except TRANSIENT as exc:
        return JSONResponse({"status": "queued", "reason": str(exc)}, status_code=202)
    return JSONResponse({**out, "status": "updated"}, status_code=200)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_bling_orders.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/bling/orders.py backend/app/bling/router.py backend/tests/test_bling_orders.py
git commit -m "feat(bling): PUT de pedido no Bling"
```

---

### Task 14: Regra de divergência (função pura)

**Files:**
- Create: `frontend/src/lib/bling-divergence.ts`
- Test: `frontend/src/lib/bling-divergence.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
import { describe, it, expect } from "vitest";
import { divergenceFrom, shouldMarkDivergent } from "@/lib/bling-divergence";

describe("shouldMarkDivergent", () => {
  it("recusa de validacao marca divergencia", () => {
    expect(shouldMarkDivergent(422)).toBe(true);
  });

  // O teste que separa negocio de infraestrutura: erro transitorio e
  // retentativa, nao decisao de divergir.
  it("erro transitorio NAO marca divergencia", () => {
    expect(shouldMarkDivergent(202)).toBe(false);
    expect(shouldMarkDivergent(503)).toBe(false);
  });

  it("sucesso nao marca", () => {
    expect(shouldMarkDivergent(200)).toBe(false);
  });
});

describe("divergenceFrom", () => {
  it("registra so os campos que mudaram", () => {
    const d = divergenceFrom(
      { value: 400, notes: "a" },
      { value: 500, notes: "a" },
      "2026-08-21T10:00:00Z"
    );
    expect(d.fields).toEqual(["value"]);
    expect(d.bling).toEqual({ value: 400 });
    expect(d.crm).toEqual({ value: 500 });
    expect(d.at).toBe("2026-08-21T10:00:00Z");
  });

  it("sem mudanca, sem divergencia", () => {
    expect(divergenceFrom({ value: 1 }, { value: 1 }, "x").fields).toEqual([]);
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/bling-divergence.test.ts`
Expected: FAIL — módulo não encontrado

- [ ] **Step 3: Implementar**

```ts
// frontend/src/lib/bling-divergence.ts
/** Registro de divergencia entre o que o CRM guarda e o que o Bling aceitou. */
export interface Divergence {
  fields: string[];
  bling: Record<string, unknown>;
  crm: Record<string, unknown>;
  at: string;
}

/**
 * So recusa de VALIDACAO (422) vira divergencia. 202 e 5xx sao transitorios: o
 * pedido nao foi recusado, so nao foi entregue ainda — marcar divergencia neles
 * transformaria instabilidade de rede em ruido permanente no relatorio.
 */
export function shouldMarkDivergent(status: number): boolean {
  return status === 422;
}

export function divergenceFrom(
  bling: Record<string, unknown>,
  crm: Record<string, unknown>,
  at: string
): Divergence {
  const fields = Object.keys(crm).filter((k) => crm[k] !== bling[k]);
  return {
    fields,
    bling: Object.fromEntries(fields.map((k) => [k, bling[k]])),
    crm: Object.fromEntries(fields.map((k) => [k, crm[k]])),
    at,
  };
}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd frontend && npx vitest run src/lib/bling-divergence.test.ts`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/bling-divergence.ts frontend/src/lib/bling-divergence.test.ts
git commit -m "feat(bling): regra de divergencia entre CRM e Bling"
```

---

### Task 15: Edição no modal e selo na tabela

**Files:**
- Modify: `frontend/src/components/sales/sale-create-modal.tsx`
- Modify: `frontend/src/lib/bling-gate.ts` (e o teste)
- Modify: `frontend/src/components/sales/sales-table.tsx`
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Liberar o modo Bling na edição**

Em `bling-gate.test.ts`, troque o teste "editar venda continua legado" por:

```ts
it("editar venda com Bling ligado entra em modo bling (Fase E)", () => {
  const g = blingGate({ loading: false, error: null, enabled: true, isEditing: true });
  expect(g.mode).toBe("bling");
});
```

E em `bling-gate.ts`, remova o atalho `if (isEditing) return { mode: "legacy", ... }`,
mantendo o resto. `isEditing` deixa de influenciar o modo.

Run: `cd frontend && npx vitest run src/lib/bling-gate.test.ts`
Expected: PASS

- [ ] **Step 2: Estender o tipo `Sale`**

Em `frontend/src/lib/types.ts`, na interface `Sale`:

```ts
  bling_divergent?: boolean | null;
  bling_divergence?: {
    fields: string[];
    bling: Record<string, unknown>;
    crm: Record<string, unknown>;
    at: string;
  } | null;
```

- [ ] **Step 3: Fluxo de edição no modal**

Quando `isEditing && blingMode`, o submit chama
`PUT /api/bling/orders/{sale.bling_order_id}`:

- **200** → PATCH em `/api/sales` normal, com `bling_divergent: false` e
  `bling_divergence: null`.
- **422** → mostra a mensagem do Bling e um botão "Salvar só no CRM". Confirmando,
  PATCH com `bling_divergent: true` e `bling_divergence` montado por
  `divergenceFrom`.
- **202** → mensagem de "o Bling está indisponível, tente de novo" e **não** salva
  nem marca divergência.

- [ ] **Step 4: Selo na tabela**

Em `sales-table.tsx`, na célula de Situação, acrescente um selo quando
`sale.bling_divergent`, com `title` listando `sale.bling_divergence?.fields`.

- [ ] **Step 5: Type-check, lint, suíte**

Run: `cd frontend && npm run type-check && npm run lint && npm test`
Expected: tudo verde

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(bling): editar venda reflete no Bling, com selo de divergencia"
```

---

## Fechamento

- [ ] **Suíte completa**

```bash
cd backend && python -m pytest -q
cd ../frontend && npm test && npm run type-check && npm run lint
```

- [ ] **Verificação em produção, por fase**

| Fase | Como confirmar |
|---|---|
| A | Abrir o modal em `/painel-vendas` e ver o formulário de itens do Bling, não o campo de texto livre |
| C | `SELECT bling_situacao_nome FROM sales WHERE bling_order_id IS NOT NULL` preenchido |
| B | Detalhe de um lead vinculado mostra CNPJ e endereço do contato do Bling |
| D | `/produtos` lista os 535 produtos, com paginação além da primeira página |
| E | Editar uma venda de pedido faturado e ver o selo de divergência |

- [ ] **Push (com autorização)**

O repo não usa PR. O push para `master` dispara deploy de produção.
