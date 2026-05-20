# Sistema de Vendas CRM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **FRONTEND RULE:** Any task that touches frontend files MUST invoke `superpowers:frontend-design` skill before writing any UI code.

**Goal:** Adicionar registro de vendas (eventos de compra) ao CRM, integrado ao painel `/conversas` e com painel analítico dedicado em `/painel-vendas`.

**Architecture:** Nova entidade `sales` independente de `deals` — cada venda é um evento de compra ligado a um `lead_id`. Registro acontece via modal no painel CRM de `/conversas`. Painel analítico em `/painel-vendas` exibe métricas e lista filtrável. `sold_by` é armazenado como texto (email) para consistência com `assigned_to` em deals.

**Tech Stack:** Next.js App Router, Supabase (service role para API routes, realtime para hooks), TypeScript, Tailwind CSS seguindo design system em `DESIGN.md`.

---

## File Map

**Criar:**
- `frontend/src/app/api/users/route.ts` — lista membros da equipe
- `frontend/src/app/api/sales/route.ts` — GET lista / POST criar
- `frontend/src/app/api/sales/[id]/route.ts` — PATCH / DELETE
- `frontend/src/app/api/sales/metrics/route.ts` — GET agregados
- `frontend/src/app/api/leads/[id]/sales/route.ts` — GET vendas de um lead
- `frontend/src/hooks/use-lead-sales.ts` — realtime hook para vendas de um lead
- `frontend/src/hooks/use-sales.ts` — hook com filtros para o painel
- `frontend/src/components/sales/sale-create-modal.tsx` — modal de registro de venda
- `frontend/src/components/sales/sales-metrics-cards.tsx` — cards de métricas
- `frontend/src/components/sales/sales-filters.tsx` — filtros do painel
- `frontend/src/components/sales/sales-table.tsx` — tabela do painel
- `frontend/src/app/(authenticated)/painel-vendas/page.tsx` — página do painel

**Modificar:**
- `frontend/src/lib/types.ts` — adicionar interfaces `Sale` e `TeamUser`
- `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx` — seção Vendas + prop `onCreateSale`
- `frontend/src/components/conversas/contact-detail.tsx` — wiring do SaleCreateModal
- `frontend/src/components/sidebar.tsx` — item "Painel de Vendas"

---

## Task 1: DB Migration + Types

**Files:**
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Rodar migration no Supabase SQL Editor**

Abra o painel do Supabase → SQL Editor → New query e execute:

```sql
CREATE TABLE IF NOT EXISTS sales (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id         uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  sold_at         timestamptz NOT NULL DEFAULT now(),
  value           numeric(12,2) NOT NULL,
  product         text NOT NULL,
  sold_by         text,
  deal_id         uuid REFERENCES deals(id) ON DELETE SET NULL,
  conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
  notes           text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sales_lead_id_sold_at ON sales(lead_id, sold_at);
CREATE INDEX IF NOT EXISTS idx_sales_sold_at ON sales(sold_at);
CREATE INDEX IF NOT EXISTS idx_sales_sold_by ON sales(sold_by);

ALTER TABLE sales ENABLE ROW LEVEL SECURITY;
CREATE POLICY "authenticated read sales" ON sales FOR SELECT TO authenticated USING (true);
CREATE POLICY "authenticated insert sales" ON sales FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "authenticated update sales" ON sales FOR UPDATE TO authenticated USING (true);
CREATE POLICY "authenticated delete sales" ON sales FOR DELETE TO authenticated USING (true);
```

> Nota: se a tabela `conversations` não existir com esse nome exato, remova a linha `conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL` e adicione `conversation_id text` em vez disso.

- [ ] **Step 2: Adicionar interfaces em `frontend/src/lib/types.ts`**

Abra `frontend/src/lib/types.ts` e adicione ao final do arquivo:

```typescript
export interface Sale {
  id: string;
  lead_id: string;
  sold_at: string;
  value: number;
  product: string;
  sold_by: string | null;
  deal_id: string | null;
  conversation_id: string | null;
  notes: string | null;
  created_at: string;
  leads?: { id: string; name: string | null; phone: string; company: string | null } | null;
  deals?: { id: string; title: string } | null;
}

export interface TeamUser {
  id: string;
  email: string;
  name: string;
}
```

- [ ] **Step 3: Verificar tipos com tsc**

```bash
cd frontend && npx tsc --noEmit
```

Expected: sem erros.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(vendas): adicionar tipos Sale e TeamUser"
```

---

## Task 2: API Routes — Backend

**Files:**
- Create: `frontend/src/app/api/users/route.ts`
- Create: `frontend/src/app/api/leads/[id]/sales/route.ts`
- Create: `frontend/src/app/api/sales/route.ts`
- Create: `frontend/src/app/api/sales/[id]/route.ts`
- Create: `frontend/src/app/api/sales/metrics/route.ts`

- [ ] **Step 1: Criar `frontend/src/app/api/users/route.ts`**

```typescript
import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data: { users }, error } = await supabase.auth.admin.listUsers();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(
    users.map((u) => ({
      id: u.id,
      email: u.email ?? "",
      name: (u.user_metadata?.full_name as string | undefined) ?? u.email ?? "",
    }))
  );
}
```

- [ ] **Step 2: Criar `frontend/src/app/api/leads/[id]/sales/route.ts`**

```typescript
import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sales")
    .select("id, sold_at, value, product, sold_by, deal_id, notes, deals(id, title)")
    .eq("lead_id", id)
    .order("sold_at", { ascending: false });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
```

- [ ] **Step 3: Criar `frontend/src/app/api/sales/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const leadId = searchParams.get("lead_id");
  const soldBy = searchParams.get("sold_by");
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const search = searchParams.get("search");
  const page = parseInt(searchParams.get("page") ?? "1");
  const limit = parseInt(searchParams.get("limit") ?? "25");
  const offset = (page - 1) * limit;

  const supabase = await getServiceSupabase();

  let query = supabase
    .from("sales")
    .select("*, leads(id, name, phone, company), deals(id, title)", { count: "exact" })
    .order("sold_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (leadId) query = query.eq("lead_id", leadId);
  if (soldBy) query = query.eq("sold_by", soldBy);
  if (from) query = query.gte("sold_at", from);
  if (to) query = query.lte("sold_at", to);
  if (search) query = query.ilike("product", `%${search}%`);

  const { data, error, count } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data: data ?? [], count: count ?? 0 });
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  if (!body.lead_id) return NextResponse.json({ error: "lead_id é obrigatório" }, { status: 400 });
  if (!body.product?.trim()) return NextResponse.json({ error: "product é obrigatório" }, { status: 400 });
  if (body.value == null || isNaN(Number(body.value))) {
    return NextResponse.json({ error: "value é obrigatório" }, { status: 400 });
  }

  const { data, error } = await supabase
    .from("sales")
    .insert({
      lead_id: body.lead_id,
      sold_at: body.sold_at || new Date().toISOString(),
      value: Number(body.value),
      product: body.product.trim(),
      sold_by: body.sold_by || null,
      deal_id: body.deal_id || null,
      conversation_id: body.conversation_id || null,
      notes: body.notes?.trim() || null,
    })
    .select("*, leads(id, name, phone, company), deals(id, title)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  if (body.deal_id) {
    const { data: wonStage } = await supabase
      .from("pipeline_stages")
      .select("id")
      .eq("key", "fechado_ganho")
      .limit(1)
      .maybeSingle();
    if (wonStage) {
      await supabase
        .from("deals")
        .update({
          stage_id: wonStage.id,
          closed_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        })
        .eq("id", body.deal_id);
    }
  }

  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 4: Criar `frontend/src/app/api/sales/[id]/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sales")
    .update(body)
    .eq("id", id)
    .select("*, leads(id, name, phone, company), deals(id, title)")
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { error } = await supabase.from("sales").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 5: Criar `frontend/src/app/api/sales/metrics/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const supabase = await getServiceSupabase();

  let periodQuery = supabase.from("sales").select("value");
  if (from) periodQuery = periodQuery.gte("sold_at", from);
  if (to) periodQuery = periodQuery.lte("sold_at", to);

  const { data: periodSales, error } = await periodQuery;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const total_value = periodSales.reduce((sum, s) => sum + Number(s.value), 0);
  const count = periodSales.length;
  const avg_value = count > 0 ? total_value / count : 0;

  const { data: allSales } = await supabase
    .from("sales")
    .select("lead_id, sold_at")
    .order("sold_at", { ascending: true });

  let avg_repurchase_cycle_days: number | null = null;
  if (allSales && allSales.length > 1) {
    const byLead: Record<string, string[]> = {};
    for (const s of allSales) {
      if (!byLead[s.lead_id]) byLead[s.lead_id] = [];
      byLead[s.lead_id].push(s.sold_at);
    }
    const intervals: number[] = [];
    for (const dates of Object.values(byLead)) {
      for (let i = 1; i < dates.length; i++) {
        const days =
          (new Date(dates[i]).getTime() - new Date(dates[i - 1]).getTime()) /
          (1000 * 60 * 60 * 24);
        intervals.push(days);
      }
    }
    if (intervals.length > 0) {
      avg_repurchase_cycle_days = Math.round(
        intervals.reduce((a, b) => a + b, 0) / intervals.length
      );
    }
  }

  return NextResponse.json({ total_value, count, avg_value, avg_repurchase_cycle_days });
}
```

- [ ] **Step 6: Verificar tipos**

```bash
cd frontend && npx tsc --noEmit
```

Expected: sem erros.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/api/users/ frontend/src/app/api/sales/ frontend/src/app/api/leads/
git commit -m "feat(vendas): adicionar API routes de sales, metrics e users"
```

---

## Task 3: Hooks

**Files:**
- Create: `frontend/src/hooks/use-lead-sales.ts`
- Create: `frontend/src/hooks/use-sales.ts`

- [ ] **Step 1: Criar `frontend/src/hooks/use-lead-sales.ts`**

```typescript
"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Sale } from "@/lib/types";

export function useLeadSales(leadId: string | null | undefined) {
  const [sales, setSales] = useState<Sale[]>([]);
  const [loading, setLoading] = useState(false);
  const supabase = useMemo(() => createClient(), []);

  const fetchSales = useCallback(async () => {
    if (!leadId) { setSales([]); return; }
    setLoading(true);
    const res = await fetch(`/api/leads/${leadId}/sales`);
    if (res.ok) setSales(await res.json());
    setLoading(false);
  }, [leadId]);

  useEffect(() => {
    fetchSales();
    if (!leadId) return;
    const channel = supabase
      .channel(`sales-lead-${leadId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "sales", filter: `lead_id=eq.${leadId}` },
        fetchSales
      )
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [fetchSales, leadId, supabase]);

  return { sales, loading, refetch: fetchSales };
}
```

- [ ] **Step 2: Criar `frontend/src/hooks/use-sales.ts`**

```typescript
"use client";

import { useState, useEffect, useCallback } from "react";
import type { Sale } from "@/lib/types";

export interface SalesFilters {
  from?: string;
  to?: string;
  soldBy?: string;
  search?: string;
  page?: number;
}

export function useSales(filters: SalesFilters = {}) {
  const [sales, setSales] = useState<Sale[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchSales = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (filters.from) params.set("from", filters.from);
    if (filters.to) params.set("to", filters.to);
    if (filters.soldBy) params.set("sold_by", filters.soldBy);
    if (filters.search) params.set("search", filters.search);
    if (filters.page) params.set("page", String(filters.page));
    const res = await fetch(`/api/sales?${params}`);
    if (res.ok) {
      const { data, count: c } = await res.json();
      setSales(data ?? []);
      setCount(c ?? 0);
    }
    setLoading(false);
  }, [filters.from, filters.to, filters.soldBy, filters.search, filters.page]);

  useEffect(() => { fetchSales(); }, [fetchSales]);

  return { sales, count, loading, refetch: fetchSales };
}
```

- [ ] **Step 3: Verificar tipos**

```bash
cd frontend && npx tsc --noEmit
```

Expected: sem erros.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/hooks/use-lead-sales.ts frontend/src/hooks/use-sales.ts
git commit -m "feat(vendas): hooks useLeadSales e useSales"
```

---

## Task 4: SaleCreateModal

> **FRONTEND RULE:** Invocar `superpowers:frontend-design` antes de escrever qualquer código desta task.

**Files:**
- Create: `frontend/src/components/sales/sale-create-modal.tsx`

- [ ] **Step 1: Criar `frontend/src/components/sales/sale-create-modal.tsx`**

O modal segue o design system de `DESIGN.md`: fundo branco, bordas `#dedbd6`, radius `4px`, fonte 14px, off-black `#111111`, secondary text `#7b7b78`.

```typescript
"use client";

import { useState, useEffect } from "react";
import type { TeamUser } from "@/lib/types";

interface LeadDeal {
  id: string;
  title: string;
  pipeline_stages?: { is_protected: boolean } | null;
}

interface SaleCreateModalProps {
  leadId: string;
  conversationId?: string | null;
  currentUserEmail?: string;
  onClose: () => void;
  onCreated: () => void;
}

export function SaleCreateModal({
  leadId,
  conversationId,
  currentUserEmail,
  onClose,
  onCreated,
}: SaleCreateModalProps) {
  const [product, setProduct] = useState("");
  const [value, setValue] = useState("");
  const [soldAt, setSoldAt] = useState(new Date().toISOString().slice(0, 10));
  const [soldBy, setSoldBy] = useState(currentUserEmail ?? "");
  const [dealId, setDealId] = useState("");
  const [notes, setNotes] = useState("");
  const [users, setUsers] = useState<TeamUser[]>([]);
  const [deals, setDeals] = useState<LeadDeal[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/users")
      .then((r) => r.json())
      .then((data) => setUsers(Array.isArray(data) ? data : []));
    fetch(`/api/leads/${leadId}/deals`)
      .then((r) => r.json())
      .then((data) =>
        setDeals(
          (Array.isArray(data) ? data : []).filter(
            (d: LeadDeal) => !d.pipeline_stages?.is_protected
          )
        )
      );
  }, [leadId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!product.trim() || !value) {
      setError("Produto e valor são obrigatórios");
      return;
    }
    setSaving(true);
    setError(null);
    const res = await fetch("/api/sales", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lead_id: leadId,
        conversation_id: conversationId || null,
        product: product.trim(),
        value: parseFloat(value),
        sold_at: new Date(soldAt + "T12:00:00").toISOString(),
        sold_by: soldBy || null,
        deal_id: dealId || null,
        notes: notes.trim() || null,
      }),
    });
    if (!res.ok) {
      const d = await res.json();
      setError(d.error ?? "Erro ao salvar venda");
      setSaving(false);
      return;
    }
    onCreated();
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="bg-white rounded-[8px] border border-[#dedbd6] w-full max-w-md mx-4 shadow-lg">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#dedbd6]">
          <h2 className="text-[15px] font-medium text-[#111111]">Registrar Venda</h2>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
              Produto / Serviço *
            </label>
            <input
              type="text"
              value={product}
              onChange={(e) => setProduct(e.target.value)}
              placeholder="Ex: Café especial 5kg"
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
              required
            />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
              Valor (R$) *
            </label>
            <input
              type="number"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="0,00"
              min="0"
              step="0.01"
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
              required
            />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
              Data da Venda
            </label>
            <input
              type="date"
              value={soldAt}
              onChange={(e) => setSoldAt(e.target.value)}
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
            />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
              Vendedor
            </label>
            <select
              value={soldBy}
              onChange={(e) => setSoldBy(e.target.value)}
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
            >
              <option value="">Nenhum</option>
              {users.map((u) => (
                <option key={u.id} value={u.email}>
                  {u.name || u.email}
                </option>
              ))}
            </select>
          </div>
          {deals.length > 0 && (
            <div>
              <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
                Vincular a Deal (opcional)
              </label>
              <select
                value={dealId}
                onChange={(e) => setDealId(e.target.value)}
                className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
              >
                <option value="">Nenhum</option>
                {deals.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.title}
                  </option>
                ))}
              </select>
              {dealId && (
                <p className="text-[11px] text-[#7b7b78] mt-1">
                  O deal será movido para Fechado Ganho automaticamente.
                </p>
              )}
            </div>
          )}
          <div>
            <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
              Observação
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="Observações opcionais"
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none resize-none"
            />
          </div>
          {error && <p className="text-[12px] text-red-600">{error}</p>}
          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 text-[13px] text-[#7b7b78] border border-[#dedbd6] rounded-[4px] hover:bg-[#faf9f6] transition-colors"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 py-2 text-[13px] font-medium bg-[#111111] text-white rounded-[4px] hover:bg-[#222222] transition-colors disabled:opacity-50"
            >
              {saving ? "Salvando..." : "Registrar Venda"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos**

```bash
cd frontend && npx tsc --noEmit
```

Expected: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/sales/sale-create-modal.tsx
git commit -m "feat(vendas): SaleCreateModal component"
```

---

## Task 5: Integração no CRM Panel (/conversas)

> **FRONTEND RULE:** Invocar `superpowers:frontend-design` antes de escrever qualquer código desta task.

**Files:**
- Modify: `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx`
- Modify: `frontend/src/components/conversas/contact-detail.tsx`

**Contexto:** `contact-detail.tsx` gerencia o estado e busca dados; `crm-perfil-tab.tsx` só renderiza. O padrão existente é: `contact-detail` tem o state de `showCreateDeal` + `handleCreateDeal`, passa `onCreateDeal` callback para `CrmPerfilTab`. Vamos seguir o mesmo padrão para vendas.

- [ ] **Step 1: Atualizar `crm-perfil-tab.tsx`**

Adicionar `onCreateSale` prop e seção de Vendas após a seção "Oportunidades". Abra `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx` e aplique as seguintes mudanças:

**Adicionar ao interface `CrmPerfilTabProps` (linha 20-29):**
```typescript
interface CrmPerfilTabProps {
  lead: Lead;
  onSaveField: (field: string, value: string) => Promise<void>;
  deals: LeadDeal[];
  pipelines: Pipeline[];
  tags: Tag[];
  leadTags: Tag[];
  onTagToggle: (tagId: string, add: boolean) => void;
  onCreateDeal: () => void;
  // Novos:
  sales: LeadSale[];
  onCreateSale: () => void;
}
```

**Adicionar interface `LeadSale` antes de `LeadDeal` (linha 8):**
```typescript
interface LeadSale {
  id: string;
  sold_at: string;
  value: number;
  product: string;
  sold_by: string | null;
}
```

**Atualizar destructuring em `export function CrmPerfilTab` (linha 31-39):**
```typescript
export function CrmPerfilTab({
  lead,
  onSaveField,
  deals,
  tags,
  leadTags,
  onTagToggle,
  onCreateDeal,
  sales,
  onCreateSale,
}: CrmPerfilTabProps) {
```

**Adicionar seção Vendas após a seção "Oportunidades" (após a `</div>` que fecha a seção Oportunidades, antes da seção Tags — aprox. linha 153):**

```typescript
      <div className="border-t border-[#dedbd6] pt-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Vendas</span>
          <button
            onClick={onCreateSale}
            className="w-6 h-6 flex items-center justify-center rounded-[4px] border border-[#dedbd6] text-[#7b7b78] hover:border-[#111111] hover:text-[#111111] transition-colors"
            title="Registrar venda"
          >
            <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
            </svg>
          </button>
        </div>
        {sales.length === 0 ? (
          <p className="text-[12px] text-[#7b7b78]">Nenhuma venda registrada</p>
        ) : (
          <div className="space-y-2">
            {sales.slice(0, 3).map((sale) => (
              <div key={sale.id} className="flex items-start gap-2 p-2 rounded-[6px] border border-[#dedbd6] bg-white">
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] text-[#111111] truncate">{sale.product}</p>
                  <p className="text-[11px] text-[#7b7b78]">
                    {new Date(sale.sold_at).toLocaleDateString("pt-BR")}
                    {sale.sold_by ? ` · ${sale.sold_by}` : ""}
                  </p>
                  <p className="text-[12px] text-[#111111]">
                    R$ {Number(sale.value).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                  </p>
                </div>
              </div>
            ))}
            {sales.length > 3 && (
              <p className="text-[11px] text-[#7b7b78]">+{sales.length - 3} mais vendas</p>
            )}
          </div>
        )}
      </div>
```

- [ ] **Step 2: Atualizar `contact-detail.tsx`**

Abra `frontend/src/components/conversas/contact-detail.tsx` e aplique as seguintes mudanças:

**Adicionar imports no topo (após linha 4):**
```typescript
import { SaleCreateModal } from "@/components/sales/sale-create-modal";
import { useLeadSales } from "@/hooks/use-lead-sales";
```

**Dentro de `export function ContactDetail`, após `const [showCreateDeal, setShowCreateDeal] = useState(false);` (aprox. linha 62), adicionar:**
```typescript
  const [showCreateSale, setShowCreateSale] = useState(false);
  const [currentUserEmail, setCurrentUserEmail] = useState<string>("");
  const { sales, refetch: refetchSales } = useLeadSales(lead?.id);

  useEffect(() => {
    import("@/lib/supabase/client").then(({ createClient }) => {
      createClient().auth.getSession().then(({ data: { session } }) => {
        setCurrentUserEmail(session?.user?.email ?? "");
      });
    });
  }, []);
```

**Atualizar o `<CrmPerfilTab>` JSX (aprox. linha 203) adicionando as novas props:**
```typescript
              <CrmPerfilTab
                lead={lead}
                onSaveField={updateLeadField}
                deals={deals}
                pipelines={pipelines}
                tags={tags}
                leadTags={leadTags}
                onTagToggle={onTagToggle}
                onCreateDeal={() => setShowCreateDeal(true)}
                sales={sales}
                onCreateSale={() => setShowCreateSale(true)}
              />
```

**Adicionar o modal após o `{showCreateDeal && ...}` block (aprox. linha 234):**
```typescript
      {showCreateSale && lead && (
        <SaleCreateModal
          leadId={lead.id}
          conversationId={conversation.id}
          currentUserEmail={currentUserEmail}
          onClose={() => setShowCreateSale(false)}
          onCreated={refetchSales}
        />
      )}
```

- [ ] **Step 3: Verificar tipos**

```bash
cd frontend && npx tsc --noEmit
```

Expected: sem erros.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/conversas/tabs/crm-perfil-tab.tsx frontend/src/components/conversas/contact-detail.tsx
git commit -m "feat(vendas): seção Vendas no CRM panel e SaleCreateModal integrado"
```

---

## Task 6: Painel de Vendas — Componentes

> **FRONTEND RULE:** Invocar `superpowers:frontend-design` antes de escrever qualquer código desta task.

**Files:**
- Create: `frontend/src/components/sales/sales-metrics-cards.tsx`
- Create: `frontend/src/components/sales/sales-filters.tsx`
- Create: `frontend/src/components/sales/sales-table.tsx`

- [ ] **Step 1: Criar `frontend/src/components/sales/sales-metrics-cards.tsx`**

```typescript
"use client";

interface SalesMetrics {
  total_value: number;
  count: number;
  avg_value: number;
  avg_repurchase_cycle_days: number | null;
}

interface SalesMetricsCardsProps {
  metrics: SalesMetrics | null;
  loading: boolean;
}

function MetricCard({ label, value, loading }: { label: string; value: string; loading: boolean }) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
      <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">{label}</p>
      {loading ? (
        <div className="h-7 w-24 bg-[#dedbd6]/40 rounded-[4px] animate-pulse" />
      ) : (
        <p className="text-[22px] font-semibold text-[#111111] leading-none">{value}</p>
      )}
    </div>
  );
}

export function SalesMetricsCards({ metrics, loading }: SalesMetricsCardsProps) {
  const fmt = (n: number) =>
    n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <MetricCard
        label="Faturamento do período"
        value={metrics ? `R$ ${fmt(metrics.total_value)}` : "R$ 0,00"}
        loading={loading}
      />
      <MetricCard
        label="Nº de vendas"
        value={metrics ? String(metrics.count) : "0"}
        loading={loading}
      />
      <MetricCard
        label="Ticket médio"
        value={metrics ? `R$ ${fmt(metrics.avg_value)}` : "R$ 0,00"}
        loading={loading}
      />
      <MetricCard
        label="Ciclo médio de recompra"
        value={
          metrics?.avg_repurchase_cycle_days != null
            ? `${metrics.avg_repurchase_cycle_days} dias`
            : "—"
        }
        loading={loading}
      />
    </div>
  );
}
```

- [ ] **Step 2: Criar `frontend/src/components/sales/sales-filters.tsx`**

```typescript
"use client";

import { useEffect, useState } from "react";
import type { TeamUser } from "@/lib/types";
import type { SalesFilters } from "@/hooks/use-sales";

interface SalesFiltersProps {
  filters: SalesFilters;
  onChange: (f: SalesFilters) => void;
}

function startOfMonth(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
}
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function SalesFiltersBar({ filters, onChange }: SalesFiltersProps) {
  const [users, setUsers] = useState<TeamUser[]>([]);

  useEffect(() => {
    fetch("/api/users")
      .then((r) => r.json())
      .then((data) => setUsers(Array.isArray(data) ? data : []));
  }, []);

  return (
    <div className="flex flex-wrap gap-3 items-end">
      <div>
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">De</label>
        <input
          type="date"
          value={filters.from ?? startOfMonth()}
          onChange={(e) => onChange({ ...filters, from: e.target.value, page: 1 })}
          className="bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
        />
      </div>
      <div>
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Até</label>
        <input
          type="date"
          value={filters.to ?? today()}
          onChange={(e) => onChange({ ...filters, to: e.target.value, page: 1 })}
          className="bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
        />
      </div>
      <div>
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Vendedor</label>
        <select
          value={filters.soldBy ?? ""}
          onChange={(e) => onChange({ ...filters, soldBy: e.target.value || undefined, page: 1 })}
          className="bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
        >
          <option value="">Todos</option>
          {users.map((u) => (
            <option key={u.id} value={u.email}>{u.name || u.email}</option>
          ))}
        </select>
      </div>
      <div className="flex-1 min-w-[200px]">
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Buscar produto</label>
        <input
          type="text"
          value={filters.search ?? ""}
          onChange={(e) => onChange({ ...filters, search: e.target.value || undefined, page: 1 })}
          placeholder="Ex: Café especial"
          className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Criar `frontend/src/components/sales/sales-table.tsx`**

```typescript
"use client";

import Link from "next/link";
import type { Sale } from "@/lib/types";

interface SalesTableProps {
  sales: Sale[];
  loading: boolean;
  count: number;
  page: number;
  onPageChange: (p: number) => void;
}

const LIMIT = 25;

export function SalesTable({ sales, loading, count, page, onPageChange }: SalesTableProps) {
  const totalPages = Math.ceil(count / LIMIT);

  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-12 bg-[#dedbd6]/30 rounded-[6px] animate-pulse" />
        ))}
      </div>
    );
  }

  if (sales.length === 0) {
    return (
      <div className="py-12 text-center">
        <p className="text-[14px] text-[#7b7b78]">Nenhuma venda encontrada para o período selecionado.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-[#dedbd6]">
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Data</th>
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Lead</th>
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Produto</th>
              <th className="text-right py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Valor</th>
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Vendedor</th>
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Deal</th>
            </tr>
          </thead>
          <tbody>
            {sales.map((sale) => (
              <tr key={sale.id} className="border-b border-[#dedbd6]/50 hover:bg-[#faf9f6] transition-colors">
                <td className="py-3 px-3 text-[#7b7b78] whitespace-nowrap">
                  {new Date(sale.sold_at).toLocaleDateString("pt-BR")}
                </td>
                <td className="py-3 px-3">
                  {sale.leads ? (
                    <Link
                      href={`/conversas?lead_id=${sale.lead_id}`}
                      className="text-[#111111] hover:underline truncate block max-w-[140px]"
                    >
                      {sale.leads.name || sale.leads.phone}
                    </Link>
                  ) : (
                    <span className="text-[#7b7b78]">—</span>
                  )}
                </td>
                <td className="py-3 px-3 text-[#111111] max-w-[200px] truncate">{sale.product}</td>
                <td className="py-3 px-3 text-[#111111] text-right whitespace-nowrap font-medium">
                  R$ {Number(sale.value).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                </td>
                <td className="py-3 px-3 text-[#7b7b78] max-w-[140px] truncate">{sale.sold_by || "—"}</td>
                <td className="py-3 px-3">
                  {sale.deals ? (
                    <span className="text-[12px] text-[#7b7b78] truncate block max-w-[120px]">{sale.deals.title}</span>
                  ) : (
                    <span className="text-[#7b7b78]">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-4">
          <p className="text-[12px] text-[#7b7b78]">
            {count} vendas · página {page} de {totalPages}
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => onPageChange(page - 1)}
              disabled={page === 1}
              className="px-3 py-1.5 text-[12px] border border-[#dedbd6] rounded-[4px] text-[#111111] hover:bg-[#faf9f6] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Anterior
            </button>
            <button
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
              className="px-3 py-1.5 text-[12px] border border-[#dedbd6] rounded-[4px] text-[#111111] hover:bg-[#faf9f6] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Próxima
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verificar tipos**

```bash
cd frontend && npx tsc --noEmit
```

Expected: sem erros.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sales/
git commit -m "feat(vendas): SalesMetricsCards, SalesFiltersBar e SalesTable"
```

---

## Task 7: Página /painel-vendas + Sidebar

> **FRONTEND RULE:** Invocar `superpowers:frontend-design` antes de escrever qualquer código desta task.

**Files:**
- Create: `frontend/src/app/(authenticated)/painel-vendas/page.tsx`
- Modify: `frontend/src/components/sidebar.tsx`

- [ ] **Step 1: Criar `frontend/src/app/(authenticated)/painel-vendas/page.tsx`**

```typescript
"use client";

import { useState, useEffect } from "react";
import { SalesMetricsCards } from "@/components/sales/sales-metrics-cards";
import { SalesFiltersBar } from "@/components/sales/sales-filters";
import { SalesTable } from "@/components/sales/sales-table";
import { useSales, type SalesFilters } from "@/hooks/use-sales";

interface SalesMetrics {
  total_value: number;
  count: number;
  avg_value: number;
  avg_repurchase_cycle_days: number | null;
}

function startOfMonth(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
}
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function PainelVendasPage() {
  const [filters, setFilters] = useState<SalesFilters>({
    from: startOfMonth(),
    to: today(),
    page: 1,
  });
  const [metrics, setMetrics] = useState<SalesMetrics | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(true);

  const { sales, count, loading } = useSales(filters);

  useEffect(() => {
    setMetricsLoading(true);
    const params = new URLSearchParams();
    if (filters.from) params.set("from", filters.from);
    if (filters.to) params.set("to", filters.to);
    fetch(`/api/sales/metrics?${params}`)
      .then((r) => r.json())
      .then((data) => { setMetrics(data); setMetricsLoading(false); })
      .catch(() => setMetricsLoading(false));
  }, [filters.from, filters.to]);

  return (
    <div className="flex-1 overflow-y-auto bg-[#faf9f6]">
      <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        <div>
          <h1 className="text-[22px] font-semibold text-[#111111] tracking-tight">Painel de Vendas</h1>
          <p className="text-[13px] text-[#7b7b78] mt-0.5">Histórico de vendas e métricas de recompra</p>
        </div>

        <SalesMetricsCards metrics={metrics} loading={metricsLoading} />

        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5 space-y-5">
          <SalesFiltersBar filters={filters} onChange={setFilters} />
          <SalesTable
            sales={sales}
            loading={loading}
            count={count}
            page={filters.page ?? 1}
            onPageChange={(p) => setFilters((f) => ({ ...f, page: p }))}
          />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Adicionar item "Painel de Vendas" no sidebar**

Abra `frontend/src/components/sidebar.tsx`. Dentro do array `NAV_GROUPS`, no grupo `"Vendas"`, adicione o item após `"Funis de venda"` (após a linha com `href: "/vendas"`):

```typescript
      {
        href: "/painel-vendas",
        label: "Painel de Vendas",
        icon: (
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" />
          </svg>
        ),
      },
```

- [ ] **Step 3: Verificar tipos**

```bash
cd frontend && npx tsc --noEmit
```

Expected: sem erros.

- [ ] **Step 4: Testar no dev server**

```bash
cd frontend && npm run dev
```

Verificar:
1. "Painel de Vendas" aparece no sidebar abaixo de "Funis de venda"
2. Navegar para `/painel-vendas` → página carrega com 4 cards e tabela
3. Navegar para `/conversas` → selecionar uma conversa com lead → aba Perfil mostra seção "Vendas" com botão `+`
4. Clicar `+` → modal abre com campos corretos
5. Preencher e salvar → venda aparece na seção e no painel

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/\(authenticated\)/painel-vendas/ frontend/src/components/sidebar.tsx
git commit -m "feat(vendas): página /painel-vendas e item no sidebar"
```

---

## Self-Review Notes

- **Spec coverage:** DB ✓ | API routes ✓ | Hooks ✓ | CRM panel ✓ | Painel ✓ | Sidebar ✓ | Real-time via useLeadSales ✓ | Move deal to Fechado Ganho on sale ✓
- **Parallelismo possível:** Tasks 1–3 (foundation) podem correr em paralelo com o subagent-driven-development. Tasks 4–5 (CRM panel) e Tasks 6–7 (painel) são independentes entre si e podem ser despachadas em paralelo após Task 1–3.
- **Nota sobre `conversations` FK:** Se o nome da tabela for diferente, remover o FK e deixar `conversation_id text` — o ID ainda é salvo mas sem constraint de FK.
