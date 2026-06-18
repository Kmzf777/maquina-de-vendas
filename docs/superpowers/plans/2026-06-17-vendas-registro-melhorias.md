# Melhorias no Registro de Vendas — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar toda venda obrigatoriamente vinculada a um deal (com criação inline), adicionar botões verdes de finalizar/registrar venda em `/vendas` e `/conversas`, permitir editar/excluir venda e registrar venda no Painel, e otimizar a métrica de recompra.

**Architecture:** Next.js 16 App Router (Server Components + route handlers) + Supabase (service client) no frontend; UI com primitivos shadcn (`src/components/ui/*`) estilizados na paleta quente (`#faf9f6`/`#dedbd6`/`#111111`). Vínculo deal↔venda resolvido atomicamente no servidor em `POST /api/sales`. Recompra movida para RPC Postgres.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind v4, shadcn/ui (estilo radix-nova), Supabase JS, lucide-react.

---

## Convenção de verificação (LEIA ANTES)

O frontend **não tem suíte de testes** (vitest está no `package.json` mas não há config nem specs; o time verifica o front por type-check/lint/build/smoke). Portanto, em cada task a verificação é:

```
cd frontend
npm run type-check   # tsc --noEmit — precisa passar limpo
npm run lint         # eslint — sem novos erros
```
`npm run build` roda **uma vez ao final** (Task 8), pois é caro. Não fabrique infra de teste vitest — isso é scope creep.

**Regra para tasks de frontend:** todo agente que tocar arquivos em `frontend/src` DEVE invocar a skill `frontend-design` antes de escrever JSX e usar os primitivos shadcn de `@/components/ui`. A paleta quente deve ser respeitada (não usar o neutral cru do shadcn).

**Commits:** frequentes, um por task. Mensagens em pt-BR, terminar com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `frontend/src/app/api/sales/route.ts` | Modify | POST exige vínculo de deal; cria deal inline atômico |
| `frontend/src/db/migrations/sales_repurchase_rpc.sql` | Create | RPC `get_avg_repurchase_cycle_days` |
| `frontend/src/app/api/sales/metrics/route.ts` | Modify | Recompra via RPC |
| `frontend/src/components/ui/dialog.tsx` | Create (shadcn add) | Primitivo Dialog |
| `frontend/src/components/ui/textarea.tsx` | Create (shadcn add) | Primitivo Textarea |
| `frontend/src/components/sales/sale-create-modal.tsx` | Rewrite | Modal unificado: criar/editar, 3 contextos, deal inline |
| `frontend/src/components/deals/deal-detail-sidebar.tsx` | Modify | Botão verde "Finalizar Venda" |
| `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx` | Modify | Botão verde "Registrar Venda" + editar/excluir na lista |
| `frontend/src/components/conversas/contact-detail.tsx` | Modify | Passar modo edição ao modal |
| `frontend/src/app/(authenticated)/painel-vendas/page.tsx` | Modify | Botão "Registrar Venda" + estado do modal |
| `frontend/src/components/sales/sales-table.tsx` | Modify | Ações editar/excluir por linha |

---

## Task 1: API — `POST /api/sales` exige vínculo de deal + criação inline atômica

**Files:**
- Modify: `frontend/src/app/api/sales/route.ts` (função POST, linhas 34-98)

- [ ] **Step 1: Substituir a função POST inteira**

Abra `frontend/src/app/api/sales/route.ts`. Mantenha o `GET` como está. Substitua a função `POST` (da linha `export async function POST` até o `}` final) por:

```ts
export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  if (!body.lead_id) return NextResponse.json({ error: "lead_id é obrigatório" }, { status: 400 });
  if (!body.product?.trim()) return NextResponse.json({ error: "product é obrigatório" }, { status: 400 });
  if (body.value == null || isNaN(Number(body.value))) {
    return NextResponse.json({ error: "value é obrigatório" }, { status: 400 });
  }

  // Vínculo de deal é obrigatório: deal_id existente OU new_deal para criar inline.
  const hasExistingDeal = !!body.deal_id;
  const hasNewDeal = !!body.new_deal?.title?.trim() && !!body.new_deal?.pipeline_id;
  if (!hasExistingDeal && !hasNewDeal) {
    return NextResponse.json(
      { error: "Toda venda precisa estar vinculada a um deal. Selecione um deal ou crie um novo." },
      { status: 400 }
    );
  }

  // Resolve o deal_id: cria o deal inline quando necessário (antes de inserir a venda).
  let dealId: string = body.deal_id;
  if (!hasExistingDeal) {
    const pipelineId: string = body.new_deal.pipeline_id;
    const { data: firstStage, error: stageError } = await supabase
      .from("pipeline_stages")
      .select("id")
      .eq("pipeline_id", pipelineId)
      .eq("is_protected", false)
      .order("order_index", { ascending: true })
      .limit(1)
      .maybeSingle();
    if (stageError) return NextResponse.json({ error: stageError.message }, { status: 500 });
    if (!firstStage) return NextResponse.json({ error: "Funil não tem stages disponíveis." }, { status: 422 });

    const { data: createdDeal, error: dealError } = await supabase
      .from("deals")
      .insert({
        lead_id: body.lead_id,
        title: body.new_deal.title.trim(),
        value: Number(body.value) || 0,
        pipeline_id: pipelineId,
        stage_id: firstStage.id,
        stage: "novo",
      })
      .select("id")
      .single();
    if (dealError || !createdDeal) {
      return NextResponse.json({ error: dealError?.message || "Erro ao criar deal." }, { status: 500 });
    }
    dealId = createdDeal.id;
  }

  const { data, error } = await supabase
    .from("sales")
    .insert({
      lead_id: body.lead_id,
      sold_at: body.sold_at || new Date().toISOString(),
      value: Number(body.value),
      product: body.product.trim(),
      sold_by: body.sold_by || null,
      deal_id: dealId,
      conversation_id: body.conversation_id || null,
      notes: body.notes?.trim() || null,
    })
    .select("*, leads(id, name, phone, company), deals(id, title)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Fire-and-forget: notify automation engine of the new sale
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  void fetch(`${backendUrl}/api/automation/trigger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_type: "sale_created",
      lead_id: data.lead_id,
      data: { sale_id: data.id, value: data.value, product: data.product, deal_id: data.deal_id },
    }),
  }).catch(() => {});

  // Move o deal vinculado para Fechado Ganho (vale tanto para deal existente quanto recém-criado).
  const { data: wonStage } = await supabase
    .from("pipeline_stages")
    .select("id")
    .eq("key", "fechado_ganho")
    .limit(1)
    .maybeSingle();
  if (wonStage) {
    await supabase
      .from("deals")
      .update({ stage_id: wonStage.id, closed_at: new Date().toISOString(), updated_at: new Date().toISOString() })
      .eq("id", dealId);
  }

  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 2: Verificar tipos e lint**

Run:
```
cd frontend
npm run type-check
npm run lint
```
Expected: sem erros.

- [ ] **Step 3: Commit**

```
git add frontend/src/app/api/sales/route.ts
git commit -m "feat(sales-api): exigir vinculo de deal e criar deal inline ao registrar venda" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: API — RPC de recompra + métricas otimizadas

**Files:**
- Create: `frontend/src/db/migrations/sales_repurchase_rpc.sql`
- Modify: `frontend/src/app/api/sales/metrics/route.ts` (linhas 21-49)

- [ ] **Step 1: Criar a migration da RPC**

Crie `frontend/src/db/migrations/sales_repurchase_rpc.sql`:

```sql
-- Ciclo médio de recompra (dias) calculado no banco, evitando carregar toda a tabela sales no Node.
-- Média dos intervalos entre vendas consecutivas do mesmo lead.
CREATE OR REPLACE FUNCTION get_avg_repurchase_cycle_days()
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
  WITH ordered AS (
    SELECT
      lead_id,
      sold_at,
      LAG(sold_at) OVER (PARTITION BY lead_id ORDER BY sold_at) AS prev_sold_at
    FROM sales
  ),
  intervals AS (
    SELECT EXTRACT(EPOCH FROM (sold_at - prev_sold_at)) / 86400.0 AS days
    FROM ordered
    WHERE prev_sold_at IS NOT NULL
  )
  SELECT ROUND(AVG(days)) FROM intervals;
$$;
```

- [ ] **Step 2: Substituir o cálculo de recompra na rota de métricas**

Em `frontend/src/app/api/sales/metrics/route.ts`, remova o bloco que busca `allSales` e itera os intervalos (da linha `const { data: allSales }` até o cálculo de `avg_repurchase_cycle_days`) e substitua por uma chamada à RPC. O arquivo final fica:

```ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const supabase = await getServiceSupabase();

  let periodQuery = supabase.from("sales").select("value");
  if (from) periodQuery = periodQuery.gte("sold_at", from.length === 10 ? `${from}T00:00:00.000Z` : from);
  if (to) periodQuery = periodQuery.lte("sold_at", to.length === 10 ? `${to}T23:59:59.999Z` : to);

  const { data: periodSales, error } = await periodQuery;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const total_value = periodSales.reduce((sum, s) => sum + Number(s.value), 0);
  const count = periodSales.length;
  const avg_value = count > 0 ? total_value / count : 0;

  // Recompra agregada no banco via RPC (não carrega a tabela inteira no Node).
  const { data: rpcValue } = await supabase.rpc("get_avg_repurchase_cycle_days");
  const avg_repurchase_cycle_days: number | null = rpcValue == null ? null : Number(rpcValue);

  return NextResponse.json({ total_value, count, avg_value, avg_repurchase_cycle_days });
}
```

- [ ] **Step 3: Verificar tipos e lint**

Run:
```
cd frontend
npm run type-check
npm run lint
```
Expected: sem erros. (A RPC só funciona em runtime após aplicada no Supabase — ver Task 9.)

- [ ] **Step 4: Commit**

```
git add frontend/src/db/migrations/sales_repurchase_rpc.sql frontend/src/app/api/sales/metrics/route.ts
git commit -m "perf(sales-metrics): mover ciclo de recompra para RPC Postgres" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Adicionar primitivos shadcn faltantes (Dialog, Textarea)

**Files:**
- Create: `frontend/src/components/ui/dialog.tsx`
- Create: `frontend/src/components/ui/textarea.tsx`

A pasta `src/components/ui` já tem button, select, input, label, alert-dialog, etc., mas **não tem `dialog` nem `textarea`**, necessários para o modal.

- [ ] **Step 1: Adicionar via shadcn CLI**

Run:
```
cd frontend
npx shadcn@latest add dialog textarea --yes
```
Expected: cria `src/components/ui/dialog.tsx` e `src/components/ui/textarea.tsx` no estilo radix-nova já configurado em `components.json`.

Se a CLI falhar (rede/sandbox), o agente cria os dois arquivos manualmente seguindo o padrão dos primitivos existentes (mesma estrutura de `src/components/ui/select.tsx`: `data-slot`, `cn`, radix-ui), usando `radix-ui` Dialog e um `<textarea>` estilizado com as classes do `input.tsx`.

- [ ] **Step 2: Verificar tipos e lint**

Run:
```
cd frontend
npm run type-check
npm run lint
```
Expected: sem erros.

- [ ] **Step 3: Commit**

```
git add frontend/src/components/ui/dialog.tsx frontend/src/components/ui/textarea.tsx
git commit -m "chore(ui): adicionar primitivos shadcn dialog e textarea" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Reescrever `SaleCreateModal` (shadcn, 3 contextos, criar/editar, deal inline)

**REQUIRED:** invoque a skill `frontend-design` antes de escrever o JSX.

**Files:**
- Rewrite: `frontend/src/components/sales/sale-create-modal.tsx`

**Contrato de props (deve ser exatamente este — outros arquivos dependem dele):**

```ts
import type { Sale } from "@/lib/types";

interface SaleCreateModalProps {
  // Contexto de lead:
  leadId?: string;            // fixo quando aberto do chat ou do deal
  pickLead?: boolean;         // true quando aberto do Painel (mostra seletor de lead)
  // Contexto de deal:
  lockedDealId?: string;      // quando aberto de um deal específico (/vendas): deal travado
  lockedDealTitle?: string;   // título para exibir o deal travado
  conversationId?: string | null;
  currentUserEmail?: string;
  // Modo edição:
  editingSale?: Sale | null;  // quando presente, abre em modo edição
  onClose: () => void;
  onSaved: () => void;        // renomeado de onCreated; chamado após criar OU editar
}
```

**Comportamento por contexto:**
- `editingSale` presente → modo editar: pré-preenche campos, salva via `PATCH /api/sales/${editingSale.id}` (campos: product, value, sold_at, sold_by, notes). NÃO mexe em deal nesse modo.
- `lockedDealId` presente → deal travado: exibe o título do deal como read-only, envia `deal_id: lockedDealId`.
- `pickLead` true → mostra `<Select>` de lead (carrega de `/api/leads`), depois resolve deals desse lead.
- Caso geral (chat) → `leadId` fixo; mostra seletor de deal existente (carrega `/api/leads/${leadId}/deals`, filtra `!pipeline_stages?.is_protected`) com opção "➕ Criar novo deal" que revela campos: título do deal + funil (`<Select>` de `/api/pipelines`). Sempre exige um deal escolhido OU criado.

- [ ] **Step 1: Escrever o componente completo**

Substitua todo o conteúdo de `frontend/src/components/sales/sale-create-modal.tsx`. Estrutura de referência (o agente frontend-design refina o visual mantendo este comportamento, props e chamadas de API; usar `Dialog`, `Button`, `Select`, `Input`, `Label`, `Textarea` de `@/components/ui`, estilizados na paleta quente):

```tsx
"use client";

import { useState, useEffect } from "react";
import type { TeamUser, Sale } from "@/lib/types";

interface LeadDeal {
  id: string;
  title: string;
  pipeline_stages?: { is_protected: boolean } | null;
}
interface Pipeline { id: string; name: string }
interface LeadOption { id: string; name: string | null; phone: string }

interface SaleCreateModalProps {
  leadId?: string;
  pickLead?: boolean;
  lockedDealId?: string;
  lockedDealTitle?: string;
  conversationId?: string | null;
  currentUserEmail?: string;
  editingSale?: Sale | null;
  onClose: () => void;
  onSaved: () => void;
}

export function SaleCreateModal({
  leadId, pickLead, lockedDealId, lockedDealTitle, conversationId,
  currentUserEmail, editingSale, onClose, onSaved,
}: SaleCreateModalProps) {
  const isEditing = !!editingSale;
  const [selectedLeadId, setSelectedLeadId] = useState(editingSale?.lead_id ?? leadId ?? "");
  const [product, setProduct] = useState(editingSale?.product ?? "");
  const [value, setValue] = useState(editingSale ? String(editingSale.value) : "");
  const [soldAt, setSoldAt] = useState(
    (editingSale?.sold_at ?? new Date().toISOString()).slice(0, 10)
  );
  const [soldBy, setSoldBy] = useState(editingSale?.sold_by ?? currentUserEmail ?? "");
  const [dealId, setDealId] = useState(lockedDealId ?? "");
  const [creatingDeal, setCreatingDeal] = useState(false);
  const [newDealTitle, setNewDealTitle] = useState("");
  const [newDealPipeline, setNewDealPipeline] = useState("");
  const [notes, setNotes] = useState(editingSale?.notes ?? "");

  const [users, setUsers] = useState<TeamUser[]>([]);
  const [leads, setLeads] = useState<LeadOption[]>([]);
  const [deals, setDeals] = useState<LeadDeal[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Carrega usuários sempre; leads só quando pickLead; pipelines só quando pode criar deal.
  useEffect(() => {
    fetch("/api/users").then((r) => r.json()).then((d) => setUsers(Array.isArray(d) ? d : []));
    if (pickLead && !isEditing) {
      fetch("/api/leads").then((r) => r.json()).then((d) => {
        const arr = Array.isArray(d) ? d : d?.data ?? [];
        setLeads(arr);
      });
    }
    if (!isEditing && !lockedDealId) {
      fetch("/api/pipelines").then((r) => r.json()).then((d) => setPipelines(Array.isArray(d) ? d : []));
    }
  }, [pickLead, isEditing, lockedDealId]);

  // Carrega deals do lead selecionado (quando não há deal travado e não é edição).
  useEffect(() => {
    if (isEditing || lockedDealId || !selectedLeadId) return;
    fetch(`/api/leads/${selectedLeadId}/deals`)
      .then((r) => r.json())
      .then((d) =>
        setDeals((Array.isArray(d) ? d : []).filter((x: LeadDeal) => !x.pipeline_stages?.is_protected))
      );
  }, [selectedLeadId, isEditing, lockedDealId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!product.trim() || !value) { setError("Produto e valor são obrigatórios"); return; }

    if (isEditing) {
      setSaving(true); setError(null);
      const res = await fetch(`/api/sales/${editingSale!.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product: product.trim(),
          value: parseFloat(value),
          sold_at: new Date(soldAt + "T12:00:00").toISOString(),
          sold_by: soldBy || null,
          notes: notes.trim() || null,
        }),
      });
      if (!res.ok) { setError((await res.json()).error ?? "Erro ao salvar venda"); setSaving(false); return; }
      onSaved(); onClose(); return;
    }

    // Criação: precisa de lead e de vínculo de deal.
    if (!selectedLeadId) { setError("Selecione o lead"); return; }
    const linkExisting = !!dealId && !creatingDeal;
    const linkNew = creatingDeal && newDealTitle.trim() && newDealPipeline;
    if (!lockedDealId && !linkExisting && !linkNew) {
      setError("Vincule a um deal existente ou crie um novo deal");
      return;
    }

    setSaving(true); setError(null);
    const payload: Record<string, unknown> = {
      lead_id: selectedLeadId,
      conversation_id: conversationId || null,
      product: product.trim(),
      value: parseFloat(value),
      sold_at: new Date(soldAt + "T12:00:00").toISOString(),
      sold_by: soldBy || null,
      notes: notes.trim() || null,
    };
    if (lockedDealId) payload.deal_id = lockedDealId;
    else if (linkExisting) payload.deal_id = dealId;
    else payload.new_deal = { title: newDealTitle.trim(), pipeline_id: newDealPipeline };

    const res = await fetch("/api/sales", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) { setError((await res.json()).error ?? "Erro ao salvar venda"); setSaving(false); return; }
    onSaved(); onClose();
  }

  // ----- O agente frontend-design substitui o markup abaixo por uma versão shadcn
  //       (Dialog/Button/Select/Input/Label/Textarea) na paleta quente, preservando
  //       todos os campos, estados e a função handleSubmit acima. -----
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <form onSubmit={handleSubmit} className="bg-white rounded-[8px] border border-[#dedbd6] w-full max-w-md mx-4 p-5 space-y-4">
        <h2 className="text-[15px] font-medium text-[#111111]">{isEditing ? "Editar Venda" : "Registrar Venda"}</h2>

        {pickLead && !isEditing && (
          <select value={selectedLeadId} onChange={(e) => setSelectedLeadId(e.target.value)} required
            className="w-full border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px]">
            <option value="">Selecione o lead</option>
            {leads.map((l) => <option key={l.id} value={l.id}>{l.name || l.phone}</option>)}
          </select>
        )}

        <input value={product} onChange={(e) => setProduct(e.target.value)} placeholder="Produto / Serviço *" required
          className="w-full border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px]" />
        <input type="number" min="0" step="0.01" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Valor (R$) *" required
          className="w-full border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px]" />
        <input type="date" value={soldAt} onChange={(e) => setSoldAt(e.target.value)}
          className="w-full border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px]" />
        <select value={soldBy} onChange={(e) => setSoldBy(e.target.value)}
          className="w-full border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px]">
          <option value="">Vendedor: nenhum</option>
          {users.map((u) => <option key={u.id} value={u.email}>{u.name || u.email}</option>)}
        </select>

        {/* Vínculo de deal — oculto em modo edição e quando o deal está travado */}
        {!isEditing && lockedDealId && (
          <p className="text-[12px] text-[#7b7b78]">Deal: <strong>{lockedDealTitle}</strong> (será movido para Fechado Ganho)</p>
        )}
        {!isEditing && !lockedDealId && (
          <div className="space-y-2">
            {!creatingDeal ? (
              <>
                <select value={dealId} onChange={(e) => setDealId(e.target.value)}
                  className="w-full border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px]">
                  <option value="">Vincular a deal...</option>
                  {deals.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
                </select>
                <button type="button" onClick={() => { setCreatingDeal(true); setDealId(""); }}
                  className="text-[12px] text-[#111111] underline">➕ Criar novo deal</button>
              </>
            ) : (
              <div className="space-y-2 border border-[#dedbd6] rounded-[6px] p-3">
                <input value={newDealTitle} onChange={(e) => setNewDealTitle(e.target.value)} placeholder="Título do novo deal"
                  className="w-full border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px]" />
                <select value={newDealPipeline} onChange={(e) => setNewDealPipeline(e.target.value)}
                  className="w-full border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px]">
                  <option value="">Selecione o funil</option>
                  {pipelines.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
                <button type="button" onClick={() => setCreatingDeal(false)} className="text-[12px] text-[#7b7b78] underline">Cancelar novo deal</button>
              </div>
            )}
          </div>
        )}

        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="Observação"
          className="w-full border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] resize-none" />
        {error && <p className="text-[12px] text-red-600">{error}</p>}
        <div className="flex gap-2 pt-2">
          <button type="button" onClick={onClose} className="flex-1 py-2 text-[13px] border border-[#dedbd6] rounded-[4px]">Cancelar</button>
          <button type="submit" disabled={saving} className="flex-1 py-2 text-[13px] font-medium bg-[#111111] text-white rounded-[4px] disabled:opacity-50">
            {saving ? "Salvando..." : isEditing ? "Salvar" : "Registrar Venda"}
          </button>
        </div>
      </form>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos e lint**

Run:
```
cd frontend
npm run type-check
npm run lint
```
Expected: sem erros. Atenção: o tipo `Sale` já existe em `@/lib/types`.

- [ ] **Step 3: Commit**

```
git add frontend/src/components/sales/sale-create-modal.tsx
git commit -m "feat(sales): modal unificado de venda (criar/editar, 3 contextos, deal inline) com shadcn" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `/conversas` — botão verde "Registrar Venda" + editar/excluir na lista (CrmPerfilTab)

**REQUIRED:** invoque a skill `frontend-design` antes de escrever o JSX.

**Files:**
- Modify: `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx` (seção "Vendas", linhas ~105-141)
- Modify: `frontend/src/components/conversas/contact-detail.tsx` (passa `onSaved` e estado de edição)

**Mudança de contrato:** o `SaleCreateModal` agora usa `onSaved` (não `onCreated`). O `contact-detail.tsx` já renderiza o modal — atualizar a prop e adicionar estado para editar.

- [ ] **Step 1: Atualizar `contact-detail.tsx`**

Em `frontend/src/components/conversas/contact-detail.tsx`:
- Adicione um estado para a venda em edição perto de `showCreateSale`:
  ```tsx
  const [editingSale, setEditingSale] = useState<Sale | null>(null);
  ```
  (importe `Sale` de `@/lib/types` se ainda não importado.)
- Onde o `<SaleCreateModal ... />` é renderizado (linhas ~270-278), troque `onCreated={refetchSales}` por `onSaved={refetchSales}` e adicione suporte a edição. O bloco fica:
  ```tsx
  {(showCreateSale || editingSale) && lead && (
    <SaleCreateModal
      leadId={lead.id}
      conversationId={conversation.id}
      currentUserEmail={currentUserEmail}
      editingSale={editingSale}
      onClose={() => { setShowCreateSale(false); setEditingSale(null); }}
      onSaved={() => { refetchSales(); setShowCreateSale(false); setEditingSale(null); }}
    />
  )}
  ```
- Passe `onEditSale` e `onDeleteSale` ao `<CrmPerfilTab>` (render por volta da linha 227):
  ```tsx
  onEditSale={(s) => setEditingSale(s)}
  onDeleteSale={async (saleId) => {
    if (!window.confirm("Excluir esta venda? Esta ação não pode ser desfeita.")) return;
    const res = await fetch(`/api/sales/${saleId}`, { method: "DELETE" });
    if (res.ok) refetchSales(); else alert("Erro ao excluir venda.");
  }}
  ```

- [ ] **Step 2: Atualizar `crm-perfil-tab.tsx`**

Adicione ao bloco de props da interface (perto de `onCreateSale: () => void;`):
```tsx
  onEditSale: (sale: LeadSale) => void;
  onDeleteSale: (saleId: string) => void;
```
e desestruture `onEditSale, onDeleteSale` nos params do componente.

Troque o cabeçalho da seção "Vendas": o `<button>` com o "+" (linhas ~108-116) vira um **botão verde "Registrar Venda"** (o agente frontend-design define o tom de verde da paleta; sugestão de base: `bg-[#1f9d57] hover:bg-[#1b8a4c] text-white`). Estrutura:
```tsx
<button
  onClick={onCreateSale}
  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[4px] bg-[#1f9d57] text-white text-[12px] font-medium hover:bg-[#1b8a4c] transition-colors"
>
  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
  </svg>
  Registrar Venda
</button>
```
Em cada item de venda renderizado (loop `sales.slice(0, 3).map`), adicione dois botões pequenos (ícones lucide `Pencil` e `Trash2`) que chamam `onEditSale(sale)` e `onDeleteSale(sale.id)`. Manter discreto, alinhado à direita do card.

- [ ] **Step 3: Verificar tipos e lint**

Run:
```
cd frontend
npm run type-check
npm run lint
```
Expected: sem erros.

- [ ] **Step 4: Commit**

```
git add frontend/src/components/conversas/tabs/crm-perfil-tab.tsx frontend/src/components/conversas/contact-detail.tsx
git commit -m "feat(conversas): botao verde Registrar Venda + editar/excluir vendas no perfil" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `/vendas` — botão verde "Finalizar Venda" no DealDetailSidebar

**REQUIRED:** invoque a skill `frontend-design` antes de escrever o JSX.

**Files:**
- Modify: `frontend/src/components/deals/deal-detail-sidebar.tsx`

- [ ] **Step 1: Importar o modal e adicionar estado**

No topo de `deal-detail-sidebar.tsx`, importe:
```tsx
import { SaleCreateModal } from "@/components/sales/sale-create-modal";
```
Dentro do componente, adicione:
```tsx
const [showFinalizeSale, setShowFinalizeSale] = useState(false);
```

- [ ] **Step 2: Adicionar o botão verde no modo visualização**

No bloco `!editing` (logo após o `<div>` que mostra título + valor, dentro do `<>...</>` por volta das linhas 177-188), adicione um botão verde proeminente, largura total:
```tsx
<button
  onClick={() => setShowFinalizeSale(true)}
  className="w-full inline-flex items-center justify-center gap-2 py-2.5 rounded-[6px] bg-[#1f9d57] text-white text-[14px] font-medium hover:bg-[#1b8a4c] active:scale-[0.98] transition-all"
>
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 6L9 17l-5-5" />
  </svg>
  Finalizar Venda
</button>
```
(O agente frontend-design ajusta o tom de verde à paleta e o posicionamento; o botão deve ser claramente o CTA primário do sidebar.)

- [ ] **Step 3: Renderizar o modal com deal travado**

Antes do fechamento do componente (último `</div>` do JSX raiz), adicione:
```tsx
{showFinalizeSale && deal.lead_id && (
  <SaleCreateModal
    leadId={deal.lead_id}
    lockedDealId={deal.id}
    lockedDealTitle={deal.title}
    onClose={() => setShowFinalizeSale(false)}
    onSaved={() => setShowFinalizeSale(false)}
  />
)}
```

- [ ] **Step 4: Verificar tipos e lint**

Run:
```
cd frontend
npm run type-check
npm run lint
```
Expected: sem erros.

- [ ] **Step 5: Commit**

```
git add frontend/src/components/deals/deal-detail-sidebar.tsx
git commit -m "feat(vendas): botao verde Finalizar Venda no detalhe do deal" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `/painel-vendas` — botão "Registrar Venda" + editar/excluir na tabela

**REQUIRED:** invoque a skill `frontend-design` antes de escrever o JSX.

**Files:**
- Modify: `frontend/src/app/(authenticated)/painel-vendas/page.tsx`
- Modify: `frontend/src/components/sales/sales-table.tsx`

- [ ] **Step 1: Adicionar botão e estados na página**

Em `painel-vendas/page.tsx`:
- Importe `SaleCreateModal` e `Sale`:
  ```tsx
  import { SaleCreateModal } from "@/components/sales/sale-create-modal";
  import type { Sale } from "@/lib/types";
  ```
- Adicione estados:
  ```tsx
  const [showCreate, setShowCreate] = useState(false);
  const [editingSale, setEditingSale] = useState<Sale | null>(null);
  ```
- Pegue `refetch` do hook: troque `const { sales, count, loading } = useSales(filters);` por `const { sales, count, loading, refetch } = useSales(filters);`
- No header (`<div>` com o `<h1>Painel de Vendas`), adicione à direita um botão verde "Registrar Venda" que faz `setShowCreate(true)` (mesmo estilo verde das outras telas).
- Passe ações à tabela: `onEdit={(s) => setEditingSale(s)}` e `onDelete={async (id) => { if (!window.confirm("Excluir esta venda?")) return; const r = await fetch(`/api/sales/${id}`, { method: "DELETE" }); if (r.ok) refetch(); else alert("Erro ao excluir venda."); }}`
- Renderize o modal no fim do componente:
  ```tsx
  {(showCreate || editingSale) && (
    <SaleCreateModal
      pickLead={!editingSale}
      editingSale={editingSale}
      onClose={() => { setShowCreate(false); setEditingSale(null); }}
      onSaved={() => { refetch(); setShowCreate(false); setEditingSale(null); }}
    />
  )}
  ```

- [ ] **Step 2: Adicionar coluna de ações em `sales-table.tsx`**

Estenda as props:
```tsx
interface SalesTableProps {
  sales: Sale[];
  loading: boolean;
  count: number;
  page: number;
  onPageChange: (p: number) => void;
  onEdit?: (sale: Sale) => void;
  onDelete?: (saleId: string) => void;
}
```
Adicione um `<th>` vazio no fim do `<thead>` e, em cada `<tr>`, uma `<td>` final com dois botões (ícones lucide `Pencil` e `Trash2`) chamando `onEdit?.(sale)` e `onDelete?.(sale.id)`. Discreto, à direita.

- [ ] **Step 3: Verificar tipos e lint**

Run:
```
cd frontend
npm run type-check
npm run lint
```
Expected: sem erros.

- [ ] **Step 4: Commit**

```
git add frontend/src/app/\(authenticated\)/painel-vendas/page.tsx frontend/src/components/sales/sales-table.tsx
git commit -m "feat(painel-vendas): registrar venda + editar/excluir na tabela" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Build de verificação final

**Files:** nenhum (verificação).

- [ ] **Step 1: Build completo**

Run:
```
cd frontend
npm run type-check
npm run lint
npm run build
```
Expected: build do Next.js conclui sem erros. Se houver erro, corrija no arquivo apontado e rode de novo antes de prosseguir.

- [ ] **Step 2: Commit (se houver ajustes do build)**

```
git add -A
git commit -m "fix(vendas): ajustes do build de verificacao" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
(Se nada mudou, pule o commit.)

---

## Task 9: Registrar pendência da migration (RPC)

A RPC `get_avg_repurchase_cycle_days` precisa ser **aplicada no Supabase** (igual às migrations anteriores que ficam pendentes). Até lá, `GET /api/sales/metrics` retornará `avg_repurchase_cycle_days: null`.

- [ ] **Step 1:** Registrar na memória do projeto que `frontend/src/db/migrations/sales_repurchase_rpc.sql` está pendente de aplicação no Supabase, e avisar o usuário no resumo final.

---

## Self-Review (preenchido)

- **Cobertura do spec:** venda↔deal obrigatório (Task 1) ✓; deal inline (Task 1 + 4) ✓; botão verde /vendas (Task 6) ✓; registro chamativo /conversas (Task 5) ✓; editar/excluir (Tasks 5, 7) ✓; registrar no Painel (Task 7) ✓; recompra otimizada (Task 2) ✓; shadcn na paleta quente (Tasks 3-7, frontend-design) ✓.
- **Placeholders:** nenhum "TBD"/"TODO"; o markup do modal é funcional e completo, com o refino visual delegado ao agente frontend-design por instrução explícita do usuário.
- **Consistência de tipos:** prop `onSaved` (não `onCreated`) usada de forma consistente em Tasks 4, 5, 6, 7; `editingSale`, `lockedDealId`, `pickLead` batem entre o contrato (Task 4) e os call-sites (5, 6, 7).
