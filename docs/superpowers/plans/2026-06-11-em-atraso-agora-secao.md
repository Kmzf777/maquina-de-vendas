# Seção "Em atraso agora" acionável — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Frontend rule:** Qualquer tarefa que mexe em componentes/UI do frontend
> (`*.tsx` de UI: Tasks 3 e 4) DEVE invocar a skill `frontend-design` antes de codar.

**Goal:** Transformar o "Em atraso agora" de uma coluna (com bug de filtro) numa seção dedicada e acionável no dashboard, listando cada lead atrasado com tempo de espera e botão para abrir a conversa, com escopo por papel (admin vê tudo + filtro por vendedor; vendedor vê só o canal dele).

**Architecture:** Reusa o motor da rodada de espera (`sla-rounds.ts`), extraindo o passe cronológico para uma função interna compartilhada e adicionando `collectOpenRounds` que preserva a identidade da conversa. Um hook novo (`useOverdueLeads`) busca conversas sem filtro de período (corrige o bug), junta lead+vendedor, e aplica escopo por role. Um componente novo (`OverdueLeadsSection`) renderiza a lista acima da tabela de SLA, de onde a coluna de atraso é removida.

**Tech Stack:** Next.js (App Router) + TypeScript, Supabase (Postgres + Auth + Realtime), Vitest, Tailwind.

**Spec:** `docs/superpowers/specs/2026-06-11-em-atraso-agora-secao-design.md`

---

## File Structure

**Criar:**
- `frontend/src/hooks/use-overdue-leads.ts` — hook que busca/junta/escopa os leads em atraso
- `frontend/src/components/dashboard/overdue-leads-section.tsx` — a seção acionável

**Modificar:**
- `frontend/src/lib/sla-rounds.ts` — extrai `walkConversation` (interno) + adiciona `collectOpenRounds`
- `frontend/src/lib/sla-rounds.test.ts` — testes do `collectOpenRounds`
- `frontend/src/components/dashboard/sla-table.tsx` — remove a coluna "Em atraso agora"
- `frontend/src/app/(authenticated)/dashboard/page.tsx` — adiciona `<OverdueLeadsSection />` acima de `<SlaTable />`

---

## Task 1: Refatorar `sla-rounds.ts` — `walkConversation` + `collectOpenRounds` (TDD)

**Files:**
- Modify: `frontend/src/lib/sla-rounds.ts`
- Test: `frontend/src/lib/sla-rounds.test.ts`

- [ ] **Step 1: Adicionar os testes do `collectOpenRounds` ao final de `sla-rounds.test.ts`**

Abra `frontend/src/lib/sla-rounds.test.ts`. Ele já importa `collectRounds, summarizeRounds, type SlaConversation` e tem os helpers `U` e `conv`. ADICIONE ao import o `collectOpenRounds`:
```ts
import { collectRounds, summarizeRounds, collectOpenRounds, type SlaConversation } from "@/lib/sla-rounds";
```

E ADICIONE este bloco de testes ao final do arquivo:
```ts
describe("collectOpenRounds — rodadas abertas com identidade", () => {
  it("rodada aberta retorna conversationId + elapsedMinutes", () => {
    const c: SlaConversation = {
      id: "conv-1",
      last_seller_response_at: null,
      messages: [{ sent_by: "user", created_at: U("13:00:00") }],
    };
    const now = new Date("2026-06-10T13:25:00Z"); // 10:25 SP
    const open = collectOpenRounds([c], DEFAULT_WINDOW, now);
    expect(open).toEqual([{ conversationId: "conv-1", elapsedMinutes: 25 }]);
  });

  it("rodada fechada por resposta do vendedor não entra", () => {
    const c: SlaConversation = {
      id: "conv-2",
      last_seller_response_at: null,
      messages: [
        { sent_by: "user", created_at: U("13:00:00") },
        { sent_by: "seller", created_at: U("13:05:00") },
      ],
    };
    const open = collectOpenRounds([c], DEFAULT_WINDOW, new Date("2026-06-10T20:00:00Z"));
    expect(open).toEqual([]);
  });

  it("rodada fechada via Finalizar (last_seller_response_at) não entra", () => {
    const c: SlaConversation = {
      id: "conv-3",
      last_seller_response_at: U("13:15:00"),
      messages: [{ sent_by: "user", created_at: U("13:00:00") }],
    };
    const open = collectOpenRounds([c], DEFAULT_WINDOW, new Date("2026-06-10T20:00:00Z"));
    expect(open).toEqual([]);
  });

  it("dois leads abertos → dois itens com os conversationIds certos", () => {
    const a: SlaConversation = {
      id: "conv-a",
      last_seller_response_at: null,
      messages: [{ sent_by: "user", created_at: U("13:00:00") }],
    };
    const b: SlaConversation = {
      id: "conv-b",
      last_seller_response_at: null,
      messages: [{ sent_by: "user", created_at: U("13:10:00") }],
    };
    const now = new Date("2026-06-10T13:30:00Z"); // 10:30 SP
    const open = collectOpenRounds([a, b], DEFAULT_WINDOW, now);
    expect(open).toEqual([
      { conversationId: "conv-a", elapsedMinutes: 30 },
      { conversationId: "conv-b", elapsedMinutes: 20 },
    ]);
  });
});
```

> NOTA: o `sla-rounds.test.ts` já tem `import { DEFAULT_WINDOW } from "@/lib/business-hours";` no topo (usado pelos testes existentes). Não duplique o import.

- [ ] **Step 2: Rodar e verificar que falha**

Run (em `frontend`): `npm test src/lib/sla-rounds.test.ts`
Expected: FAIL — `collectOpenRounds` não existe / não é exportado.

- [ ] **Step 3: Refatorar `sla-rounds.ts`**

Abra `frontend/src/lib/sla-rounds.ts`. Mantenha as interfaces existentes (`SlaMessage`, `SlaConversation`, `SellerRounds`, `SellerSlaResult`) e `summarizeRounds` inalterados. ADICIONE a interface `OpenRound` junto às outras interfaces:
```ts
export interface OpenRound {
  conversationId: string;
  elapsedMinutes: number;
}
```

SUBSTITUA a função `collectRounds` inteira por esta função interna compartilhada + a `collectRounds` reescrita em cima dela:
```ts
/**
 * Um único passe cronológico por conversa. Retorna os minutos comerciais das
 * rodadas fechadas e, se houver uma rodada aberta no fim, seus minutos decorridos.
 * Regras: rodada começa na primeira msg do cliente sem resposta; fecha na primeira
 * resposta do vendedor (msg 'seller' ou Finalizar via last_seller_response_at);
 * rajadas do cliente não reiniciam; msg proativa do vendedor é ignorada.
 */
function walkConversation(
  conv: SlaConversation,
  win: BusinessWindow,
  now: Date
): { closed: number[]; openElapsedMinutes: number | null } {
  const closed: number[] = [];
  let waitStart: string | null = null;

  for (const msg of conv.messages) {
    if (msg.sent_by === "user") {
      if (waitStart === null) waitStart = msg.created_at;
    } else if (msg.sent_by === "seller") {
      if (waitStart !== null) {
        const mins = businessMinutesBetween(new Date(waitStart), new Date(msg.created_at), win);
        if (mins >= 0) closed.push(mins);
        waitStart = null;
      }
    }
  }

  if (waitStart !== null) {
    const finalize = conv.last_seller_response_at;
    if (finalize && finalize > waitStart) {
      const mins = businessMinutesBetween(new Date(waitStart), new Date(finalize), win);
      if (mins >= 0) closed.push(mins);
      return { closed, openElapsedMinutes: null };
    }
    const elapsed = businessMinutesBetween(new Date(waitStart), now, win);
    return { closed, openElapsedMinutes: elapsed };
  }

  return { closed, openElapsedMinutes: null };
}

/**
 * Percorre as conversas e extrai as rodadas de espera (fechadas + aberta).
 */
export function collectRounds(
  conversations: SlaConversation[],
  win: BusinessWindow,
  now: Date = new Date()
): SellerRounds {
  const closed: number[] = [];
  const openElapsed: number[] = [];

  for (const conv of conversations) {
    const r = walkConversation(conv, win, now);
    closed.push(...r.closed);
    if (r.openElapsedMinutes !== null) openElapsed.push(r.openElapsedMinutes);
  }

  return { closed, openElapsed };
}

/**
 * Retorna só as rodadas ABERTAS, preservando o conversationId, para a seção
 * acionável "Em atraso agora". O filtro por alvo (> target) é aplicado pelo chamador.
 */
export function collectOpenRounds(
  conversations: SlaConversation[],
  win: BusinessWindow,
  now: Date = new Date()
): OpenRound[] {
  const out: OpenRound[] = [];
  for (const conv of conversations) {
    const r = walkConversation(conv, win, now);
    if (r.openElapsedMinutes !== null) {
      out.push({ conversationId: conv.id, elapsedMinutes: r.openElapsedMinutes });
    }
  }
  return out;
}
```

- [ ] **Step 4: Rodar e verificar verde (incluindo testes antigos)**

Run (em `frontend`): `npm test src/lib/sla-rounds.test.ts`
Expected: todos PASS — os 7 testes antigos de `collectRounds`/`summarizeRounds` + os 4 novos de `collectOpenRounds`.

- [ ] **Step 5: Type-check**

Run (em `frontend`): `npx tsc --noEmit`
Expected: sem erros (o `use-sla-stats.ts` segue usando `collectRounds`/`summarizeRounds` com as mesmas assinaturas).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/sla-rounds.ts frontend/src/lib/sla-rounds.test.ts
git commit -m "feat(sla): collectOpenRounds preservando conversationId (rodadas abertas)"
```

---

## Task 2: Hook `use-overdue-leads.ts`

**Files:**
- Create: `frontend/src/hooks/use-overdue-leads.ts`

> Sem teste unitário (I/O Supabase + tempo + role). Lógica pura já coberta na Task 1.
> Validação: `tsc` + teste manual no dashboard (Task 4).

- [ ] **Step 1: Implementar o hook**

Create `frontend/src/hooks/use-overdue-leads.ts`:
```ts
"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import { spDateString, type BusinessWindow } from "@/lib/business-hours";
import { collectOpenRounds, type SlaConversation } from "@/lib/sla-rounds";

interface SellerConfigRow {
  user_id: string;
  channel_id: string;
  display_name: string;
  window_start_minute: number;
  window_end_minute: number;
  active_weekdays: number[];
  active: boolean;
}

interface OverrideRow {
  user_id: string | null;
  start_date: string;
  end_date: string;
}

interface LeadJoin {
  name: string | null;
  phone: string | null;
}

interface ConvRow {
  id: string;
  channel_id: string;
  lead_id: string | null;
  last_seller_response_at: string | null;
  leads: LeadJoin | null;
}

interface MsgRow {
  conversation_id: string;
  sent_by: string;
  created_at: string;
}

export interface OverdueLead {
  conversationId: string;
  leadId: string;
  leadName: string;
  leadPhone: string;
  channelId: string;
  userId: string;        // user_id do vendedor (filtro robusto do admin)
  vendedorName: string;
  elapsedMinutes: number;
}

export interface OverdueData {
  leads: OverdueLead[];
  vendedores: { userId: string; name: string }[];
  isAdmin: boolean;
  loading: boolean;
}

function buildExcludedDates(overrides: OverrideRow[], userId: string): Set<string> {
  const out = new Set<string>();
  for (const o of overrides) {
    if (o.user_id !== null && o.user_id !== userId) continue;
    const start = new Date(`${o.start_date}T12:00:00Z`);
    const end = new Date(`${o.end_date}T12:00:00Z`);
    for (let d = start; d <= end; d = new Date(d.getTime() + 86_400_000)) {
      out.add(spDateString(d));
    }
  }
  return out;
}

function windowFor(cfg: SellerConfigRow, overrides: OverrideRow[]): BusinessWindow {
  return {
    startMin: cfg.window_start_minute,
    endMin: cfg.window_end_minute,
    weekdays: new Set(cfg.active_weekdays),
    excludedDates: buildExcludedDates(overrides, cfg.user_id),
  };
}

async function fetchConversations(
  supabase: ReturnType<typeof createClient>,
  channelIds: string[]
): Promise<ConvRow[]> {
  if (channelIds.length === 0) return [];
  const PAGE = 1000;
  const all: ConvRow[] = [];
  let offset = 0;
  while (true) {
    const { data, error } = await supabase
      .from("conversations")
      .select("id, channel_id, lead_id, last_seller_response_at, leads(name, phone)")
      .in("channel_id", channelIds)
      .order("created_at", { ascending: false })
      .range(offset, offset + PAGE - 1);
    if (error || !data || data.length === 0) break;
    all.push(...(data as unknown as ConvRow[]));
    if (data.length < PAGE) break;
    offset += PAGE;
  }
  return all;
}

async function fetchMessages(
  supabase: ReturnType<typeof createClient>,
  convIds: string[]
): Promise<MsgRow[]> {
  if (convIds.length === 0) return [];
  const PAGE = 1000;
  const CHUNK = 200;
  const all: MsgRow[] = [];
  for (let i = 0; i < convIds.length; i += CHUNK) {
    const slice = convIds.slice(i, i + CHUNK);
    let offset = 0;
    while (true) {
      const { data, error } = await supabase
        .from("messages")
        .select("conversation_id, sent_by, created_at")
        .in("conversation_id", slice)
        .in("sent_by", ["user", "seller"])
        .order("created_at", { ascending: true })
        .range(offset, offset + PAGE - 1);
      if (error || !data || data.length === 0) break;
      all.push(...(data as MsgRow[]));
      if (data.length < PAGE) break;
      offset += PAGE;
    }
  }
  return all;
}

export function useOverdueLeads(): OverdueData {
  const [leads, setLeads] = useState<OverdueLead[]>([]);
  const [vendedores, setVendedores] = useState<{ userId: string; name: string }[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchAndCompute = useCallback(async () => {
    const { data: userData } = await supabase.auth.getUser();
    const user = userData.user;
    const admin = user?.app_metadata?.role === "admin";
    setIsAdmin(admin);

    const [{ data: cfgData }, { data: ovData }, { data: settingsData }] = await Promise.all([
      supabase.from("sla_seller_config").select("*").eq("active", true),
      supabase.from("sla_overrides").select("user_id, start_date, end_date"),
      supabase.from("sla_settings").select("target_minutes").eq("id", 1).single(),
    ]);

    const allConfigs = (cfgData ?? []) as SellerConfigRow[];
    const overrides = (ovData ?? []) as OverrideRow[];
    const target = (settingsData?.target_minutes ?? 20) as number;

    // Escopo por role: admin = todos; vendedor = só a config dele.
    const configs = admin
      ? allConfigs
      : allConfigs.filter((c) => c.user_id === user?.id);

    setVendedores(
      admin ? allConfigs.map((c) => ({ userId: c.user_id, name: c.display_name || "(sem nome)" })) : []
    );

    const channelIds = configs.map((c) => c.channel_id);
    const convs = await fetchConversations(supabase, channelIds);
    const msgs = await fetchMessages(supabase, convs.map((c) => c.id));

    // Agrupa mensagens por conversa
    const msgsByConv = new Map<string, MsgRow[]>();
    for (const m of msgs) {
      if (!msgsByConv.has(m.conversation_id)) msgsByConv.set(m.conversation_id, []);
      msgsByConv.get(m.conversation_id)!.push(m);
    }
    // Indexa conversa por id
    const convById = new Map<string, ConvRow>();
    for (const c of convs) convById.set(c.id, c);

    // Conversas por canal (apenas com lead_id válido — sem lead não dá pra abrir conversa)
    const convsByChannel = new Map<string, SlaConversation[]>();
    for (const c of convs) {
      if (!c.lead_id) continue;
      const slaConv: SlaConversation = {
        id: c.id,
        last_seller_response_at: c.last_seller_response_at,
        messages: msgsByConv.get(c.id) ?? [],
      };
      if (!convsByChannel.has(c.channel_id)) convsByChannel.set(c.channel_id, []);
      convsByChannel.get(c.channel_id)!.push(slaConv);
    }

    const now = new Date();
    const result: OverdueLead[] = [];

    for (const cfg of configs) {
      const win = windowFor(cfg, overrides);
      const channelConvs = convsByChannel.get(cfg.channel_id) ?? [];
      const open = collectOpenRounds(channelConvs, win, now);
      for (const o of open) {
        if (o.elapsedMinutes <= target) continue;
        const conv = convById.get(o.conversationId);
        if (!conv || !conv.lead_id) continue;
        const phone = conv.leads?.phone ?? "";
        result.push({
          conversationId: o.conversationId,
          leadId: conv.lead_id,
          leadName: conv.leads?.name || phone || "(sem nome)",
          leadPhone: phone,
          channelId: cfg.channel_id,
          userId: cfg.user_id,
          vendedorName: cfg.display_name || "(sem nome)",
          elapsedMinutes: o.elapsedMinutes,
        });
      }
    }

    result.sort((a, b) => b.elapsedMinutes - a.elapsedMinutes);
    setLeads(result);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    setLoading(true);
    fetchAndCompute();

    const channel = supabase
      .channel("overdue-leads-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "conversations" }, fetchAndCompute)
      .on("postgres_changes", { event: "*", schema: "public", table: "messages" }, fetchAndCompute)
      .subscribe();

    const ticker = setInterval(fetchAndCompute, 60_000);

    return () => {
      supabase.removeChannel(channel);
      clearInterval(ticker);
    };
  }, [fetchAndCompute]);

  return { leads, vendedores, isAdmin, loading };
}
```

- [ ] **Step 2: Type-check**

Run (em `frontend`): `npx tsc --noEmit`
Expected: sem erros.

> NOTA sobre o join `leads(name, phone)`: o supabase-js às vezes tipa o relacionamento
> como array. Se o `tsc` reclamar do tipo de `leads`, ajuste a interface `LeadJoin`
> para o que o cliente retornar (ex.: `leads: LeadJoin | LeadJoin[] | null` e normalize
> com `Array.isArray(c.leads) ? c.leads[0] : c.leads`). O cast `as unknown as ConvRow[]`
> já existe para absorver essa variação; mantenha o acesso seguro com `?.`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/use-overdue-leads.ts
git commit -m "feat(sla): hook use-overdue-leads com escopo por role"
```

---

## Task 3: Componente `OverdueLeadsSection`

**Files:**
- Create: `frontend/src/components/dashboard/overdue-leads-section.tsx`

> **FRONTEND:** invoque a skill `frontend-design` antes de codar este componente.

- [ ] **Step 1: Implementar o componente**

Create `frontend/src/components/dashboard/overdue-leads-section.tsx` com esta implementação completa. O filtro do admin guarda o `userId` do vendedor e compara pelo `vendedorName` (mapeado a partir da lista `vendedores`):
```tsx
"use client";

import { useState } from "react";
import Link from "next/link";
import { useOverdueLeads, type OverdueLead } from "@/hooks/use-overdue-leads";
import { formatBusinessDuration } from "@/lib/business-hours";

function SkeletonRow() {
  return <div className="animate-pulse bg-[#dedbd6]/40 rounded-[8px] h-12" />;
}

export function OverdueLeadsSection() {
  const { leads, vendedores, isAdmin, loading } = useOverdueLeads();
  // Filtro por vendedor (admin), pelo userId — robusto a nomes repetidos.
  const [vendedorFilter, setVendedorFilter] = useState<string>(""); // "" = todos

  const visible: OverdueLead[] =
    isAdmin && vendedorFilter
      ? leads.filter((l) => l.userId === vendedorFilter)
      : leads;

  return (
    <div className="mb-8">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Em atraso agora
          </p>
          <span
            className={`text-[12px] font-medium px-2 py-0.5 rounded-[4px] ${
              visible.length > 0 ? "bg-[#c41c1c]/10 text-[#c41c1c]" : "bg-[#dedbd6]/40 text-[#7b7b78]"
            }`}
          >
            {visible.length}
          </span>
        </div>
        {isAdmin && vendedores.length > 0 && (
          <select
            value={vendedorFilter}
            onChange={(e) => setVendedorFilter(e.target.value)}
            className="h-7 px-2 text-[13px] border border-[#dedbd6] bg-white rounded-[6px] text-[#111111] focus:outline-none focus:border-[#111111]"
          >
            <option value="">Todos os vendedores</option>
            {vendedores.map((v) => (
              <option key={v.userId} value={v.userId}>{v.name}</option>
            ))}
          </select>
        )}
      </div>

      <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
        {loading ? (
          <div className="p-3 space-y-2">
            <SkeletonRow />
            <SkeletonRow />
            <SkeletonRow />
          </div>
        ) : visible.length === 0 ? (
          <div className="px-4 py-8 text-center text-[14px] text-[#7b7b78]">
            Nenhum lead em atraso agora.
          </div>
        ) : (
          <ul className="divide-y divide-[#f0ede8]">
            {visible.map((l) => (
              <li key={l.conversationId} className="flex items-center gap-3 px-4 py-3">
                <span className="w-2 h-2 rounded-full bg-[#c41c1c] flex-shrink-0" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] text-[#111111] truncate">{l.leadName}</p>
                  {isAdmin && (
                    <p className="text-[12px] text-[#7b7b78] truncate">{l.vendedorName}</p>
                  )}
                </div>
                <span className="text-[14px] text-[#c41c1c] font-medium whitespace-nowrap">
                  {formatBusinessDuration(l.elapsedMinutes)}
                </span>
                <Link
                  href={`/conversas?lead_id=${l.leadId}`}
                  className="bg-[#111111] text-white px-[12px] py-1.5 rounded-[4px] text-[13px] whitespace-nowrap transition-transform hover:scale-105 active:scale-[0.95]"
                >
                  Abrir conversa
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run (em `frontend`): `npx tsc --noEmit`
Expected: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/overdue-leads-section.tsx
git commit -m "feat(sla): secao acionavel 'Em atraso agora' com botao abrir conversa"
```

---

## Task 4: Wire no dashboard + remover coluna da `SlaTable`

**Files:**
- Modify: `frontend/src/components/dashboard/sla-table.tsx`
- Modify: `frontend/src/app/(authenticated)/dashboard/page.tsx`

> **FRONTEND:** invoque a skill `frontend-design` antes de mexer nestes componentes.

- [ ] **Step 1: Remover a coluna "Em atraso agora" da `SlaTable`**

Abra `frontend/src/components/dashboard/sla-table.tsx`. Faça TRÊS remoções:

(a) No `<thead>`, remova a célula de cabeçalho da coluna de atraso:
```tsx
              <th className="text-right font-normal px-4 py-3">Em atraso agora</th>
```

(b) Nas linhas (`rows.map`), remova a célula:
```tsx
                  <td className={`px-4 py-3 text-right font-medium ${r.overdueCount > 0 ? "text-[#c41c1c]" : "text-[#111111]"}`}>
                    {r.overdueCount}
                  </td>
```

(c) No `<tfoot>` (linha do Total), remova a célula:
```tsx
                <td className={`px-4 py-3 text-right ${total.overdueCount > 0 ? "text-[#c41c1c]" : "text-[#111111]"}`}>
                  {total.overdueCount}
                </td>
```

E ajuste os `colSpan` dos estados de loading/vazio de `4` para `3`:
```tsx
              <tr><td colSpan={3} className="px-4 py-6 text-center text-[#7b7b78]">Carregando…</td></tr>
```
```tsx
              <tr><td colSpan={3} className="px-4 py-6 text-center text-[#7b7b78]">Nenhum vendedor configurado.</td></tr>
```

A tabela passa a ter 3 colunas: Vendedor · Média resp. · Pior SLA.

- [ ] **Step 2: Adicionar a seção ao dashboard**

Abra `frontend/src/app/(authenticated)/dashboard/page.tsx`. Adicione o import junto aos outros imports de dashboard (perto da linha do `SlaTable`):
```tsx
import { OverdueLeadsSection } from "@/components/dashboard/overdue-leads-section";
```

E renderize a seção imediatamente ANTES de `<SlaTable />` (no JSX, perto da linha 132):
```tsx
        <OnlineUsersSection />
        <OverdueLeadsSection />
        <SlaTable />
```

> NOTA: confirme o nome/ordem reais dos componentes nessa região do JSX antes de editar.
> Hoje a ordem é `<OnlineUsersSection /> <SlaHeroSection />` foi trocada por
> `<SlaTable />` numa task anterior — então o alvo é inserir `<OverdueLeadsSection />`
> entre `<OnlineUsersSection />` e `<SlaTable />`.

- [ ] **Step 3: Type-check + testes**

Run (em `frontend`): `npx tsc --noEmit` e depois `npm test`
Expected: `tsc` sem erros; todos os testes (business-hours + sla-rounds) PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/dashboard/sla-table.tsx "frontend/src/app/(authenticated)/dashboard/page.tsx"
git commit -m "feat(sla): remove coluna de atraso da tabela e adiciona secao ao dashboard"
```

---

## Self-Review (preenchido pelo autor do plano)

- **Cobertura do spec:** motor (`collectOpenRounds` + `walkConversation`, Task 1),
  hook com escopo por role e correção do bug de período (Task 2), seção acionável com
  botão abrir conversa + filtro admin (Task 3), remoção da coluna + wire no dashboard
  (Task 4). ✓
- **Placeholders:** o andaime explícito no início da Task 3 Step 1 é marcado como
  descartável e seguido pela implementação completa — não é placeholder solto. As duas
  NOTAs (tipo do join `leads`, ordem do JSX) são pontos de conferência contra o código
  real, sinalizados.
- **Consistência de tipos:** `SlaConversation`, `OpenRound`, `OverdueLead`, `OverdueData`,
  `collectOpenRounds`, `useOverdueLeads` usados de forma idêntica entre Tasks 1-4. O
  `collectRounds`/`summarizeRounds` mantêm assinatura, então `use-sla-stats.ts` não quebra.
