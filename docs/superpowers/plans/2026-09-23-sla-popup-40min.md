# Popup de SLA (40 min) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar ao vendedor um popup insistente (um por lead, em fila, reabrindo a cada troca de rota) quando um lead dele passa de 40 min de atendimento sem resposta, com o lembrete do horário de atendimento.

**Architecture:** O popup reaproveita `useOverdueLeads` (fonte única da regra de SLA) com um limite de 40 min. A fila é calculada por uma função pura. Um store mínimo publica a conversa aberta em `/conversas` para não mostrar popup da conversa que o vendedor já está respondendo. O componente fica montado no `AuthenticatedShell`.

**Tech Stack:** Next.js App Router (client components), React 19 `useSyncExternalStore`, Supabase JS, Radix Dialog (`@/components/ui/dialog`), Vitest.

**Spec:** `docs/superpowers/specs/2026-09-23-sla-popup-40min-design.md`

**Paralelismo:** as Tasks 1 a 4 mexem em arquivos disjuntos e os contratos estão fixados abaixo. Podem rodar em paralelo. **Subagentes NÃO fazem commit.** O orquestrador revisa e comita no final. Todos os comandos rodam em `frontend/`.

## Contratos (fixos, todas as tasks respeitam)

```ts
// frontend/src/lib/active-conversation.ts
export interface ActiveConversation { conversationId: string | null; leadId: string | null }
export function getActiveConversation(): ActiveConversation
export function setActiveConversation(next: ActiveConversation): void
export function subscribeActiveConversation(cb: () => void): () => void
export function useActiveConversation(): ActiveConversation

// frontend/src/lib/sla-reminder.ts
export const SLA_REMINDER_MINUTES = 40
export interface ReminderCandidate { conversationId: string; leadId: string; elapsedMinutes: number }
export function buildReminderQueue<T extends ReminderCandidate>(
  leads: readonly T[], dismissed: ReadonlySet<string>, active: ActiveConversation,
): T[]
export function formatWindowHour(minuteOfDay: number): string   // 600 -> "10h", 630 -> "10h30"

// frontend/src/hooks/use-overdue-leads.ts (alterado)
export function useOverdueLeads(opts?: { targetMinutes?: number }): OverdueData
// OverdueLead ganha: windowStartMin: number; windowEndMin: number
```

---

### Task 1: Lógica pura da fila (`lib/sla-reminder.ts`)

**Files:**
- Create: `frontend/src/lib/sla-reminder.ts`
- Test: `frontend/src/lib/sla-reminder.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
import { describe, it, expect } from "vitest";
import { buildReminderQueue, formatWindowHour, SLA_REMINDER_MINUTES } from "./sla-reminder";

const none = { conversationId: null, leadId: null };
const lead = (conversationId: string, leadId: string, elapsedMinutes: number) => ({
  conversationId, leadId, elapsedMinutes,
});

describe("buildReminderQueue", () => {
  it("ordena pela maior espera primeiro", () => {
    const q = buildReminderQueue([lead("c1", "l1", 45), lead("c2", "l2", 90)], new Set(), none);
    expect(q.map((l) => l.conversationId)).toEqual(["c2", "c1"]);
  });

  it("ignora quem está em até 40 min", () => {
    const q = buildReminderQueue([lead("c1", "l1", SLA_REMINDER_MINUTES), lead("c2", "l2", 41)], new Set(), none);
    expect(q.map((l) => l.conversationId)).toEqual(["c2"]);
  });

  it("remove os dispensados nesta página", () => {
    const q = buildReminderQueue([lead("c1", "l1", 50), lead("c2", "l2", 60)], new Set(["c2"]), none);
    expect(q.map((l) => l.conversationId)).toEqual(["c1"]);
  });

  it("remove a conversa aberta, por conversa ou por lead", () => {
    const leads = [lead("c1", "l1", 50), lead("c2", "l2", 60), lead("c3", "l3", 70)];
    expect(buildReminderQueue(leads, new Set(), { conversationId: "c1", leadId: null }).map((l) => l.conversationId))
      .toEqual(["c3", "c2"]);
    expect(buildReminderQueue(leads, new Set(), { conversationId: null, leadId: "l3" }).map((l) => l.conversationId))
      .toEqual(["c2", "c1"]);
  });

  it("não muta a entrada", () => {
    const leads = [lead("c1", "l1", 45), lead("c2", "l2", 90)];
    buildReminderQueue(leads, new Set(), none);
    expect(leads.map((l) => l.conversationId)).toEqual(["c1", "c2"]);
  });
});

describe("formatWindowHour", () => {
  it("formata hora cheia e quebrada", () => {
    expect(formatWindowHour(600)).toBe("10h");
    expect(formatWindowHour(960)).toBe("16h");
    expect(formatWindowHour(630)).toBe("10h30");
    expect(formatWindowHour(545)).toBe("9h05");
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `npx vitest run src/lib/sla-reminder.test.ts`
Expected: FAIL (módulo `./sla-reminder` não existe)

- [ ] **Step 3: Implementar**

```ts
import type { ActiveConversation } from "@/lib/active-conversation";

/**
 * Limite do popup de SLA do vendedor, em minutos de atendimento. É fixo e
 * separado da meta configurável de "em atraso" (sla_settings.target_minutes).
 */
export const SLA_REMINDER_MINUTES = 40;

export interface ReminderCandidate {
  conversationId: string;
  leadId: string;
  elapsedMinutes: number;
}

/**
 * Fila do popup: leads acima do limite, sem os dispensados nesta página e sem a
 * conversa que o vendedor já está com aberta. A maior espera vem primeiro.
 */
export function buildReminderQueue<T extends ReminderCandidate>(
  leads: readonly T[],
  dismissed: ReadonlySet<string>,
  active: ActiveConversation,
): T[] {
  return leads
    .filter((l) => l.elapsedMinutes > SLA_REMINDER_MINUTES)
    .filter((l) => !dismissed.has(l.conversationId))
    .filter((l) => l.conversationId !== active.conversationId && l.leadId !== active.leadId)
    .sort((a, b) => b.elapsedMinutes - a.elapsedMinutes);
}

/** Minuto do dia -> "10h" / "10h30". */
export function formatWindowHour(minuteOfDay: number): string {
  const h = Math.floor(minuteOfDay / 60);
  const m = minuteOfDay % 60;
  return m === 0 ? `${h}h` : `${h}h${String(m).padStart(2, "0")}`;
}
```

Observação: o `import type` depende da Task 2. Se a Task 2 ainda não criou o arquivo, o vitest continua passando, porque o esbuild apaga imports de tipo. O `tsc` só fica verde quando as duas tasks terminam.

- [ ] **Step 4: Rodar e ver passar**

Run: `npx vitest run src/lib/sla-reminder.test.ts`
Expected: PASS (6 testes)

---

### Task 2: Store da conversa aberta + publicação em `/conversas`

**Files:**
- Create: `frontend/src/lib/active-conversation.ts`
- Test: `frontend/src/lib/active-conversation.test.ts`
- Modify: `frontend/src/app/(authenticated)/conversas/page.tsx` (imports e um `useEffect` logo depois do `useMemo` de `selectedConversation`)

- [ ] **Step 1: Escrever o teste que falha**

```ts
import { describe, it, expect, vi } from "vitest";
import {
  getActiveConversation, setActiveConversation, subscribeActiveConversation,
} from "./active-conversation";

describe("active-conversation store", () => {
  it("começa vazio", () => {
    expect(getActiveConversation()).toEqual({ conversationId: null, leadId: null });
  });

  it("set notifica os inscritos e o get devolve o valor novo", () => {
    const cb = vi.fn();
    const unsub = subscribeActiveConversation(cb);
    setActiveConversation({ conversationId: "c1", leadId: "l1" });
    expect(cb).toHaveBeenCalledTimes(1);
    expect(getActiveConversation()).toEqual({ conversationId: "c1", leadId: "l1" });
    unsub();
    setActiveConversation({ conversationId: null, leadId: null });
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it("set com o mesmo valor não notifica (snapshot estável)", () => {
    setActiveConversation({ conversationId: "c9", leadId: "l9" });
    const snap = getActiveConversation();
    const cb = vi.fn();
    const unsub = subscribeActiveConversation(cb);
    setActiveConversation({ conversationId: "c9", leadId: "l9" });
    expect(cb).not.toHaveBeenCalled();
    expect(getActiveConversation()).toBe(snap);
    unsub();
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `npx vitest run src/lib/active-conversation.test.ts`
Expected: FAIL (módulo não existe)

- [ ] **Step 3: Implementar o store**

```ts
"use client";

import { useSyncExternalStore } from "react";

/**
 * Conversa que o vendedor está com aberta em /conversas. O popup de SLA lê este
 * valor para não interromper justamente a resposta ao lead que está atrasado.
 */
export interface ActiveConversation {
  conversationId: string | null;
  leadId: string | null;
}

const EMPTY: ActiveConversation = { conversationId: null, leadId: null };
let current: ActiveConversation = EMPTY;
const listeners = new Set<() => void>();

export function getActiveConversation(): ActiveConversation {
  return current;
}

export function setActiveConversation(next: ActiveConversation): void {
  if (next.conversationId === current.conversationId && next.leadId === current.leadId) return;
  current = next.conversationId === null && next.leadId === null ? EMPTY : { ...next };
  listeners.forEach((l) => l());
}

export function subscribeActiveConversation(cb: () => void): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

export function useActiveConversation(): ActiveConversation {
  return useSyncExternalStore(subscribeActiveConversation, getActiveConversation, () => EMPTY);
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `npx vitest run src/lib/active-conversation.test.ts`
Expected: PASS (3 testes)

- [ ] **Step 5: Publicar a seleção na página de conversas**

Em `frontend/src/app/(authenticated)/conversas/page.tsx`, adicionar o import:

```ts
import { setActiveConversation } from "@/lib/active-conversation";
```

Logo depois do `useMemo` que define `selectedConversation`, adicionar:

```ts
  // Publica a conversa aberta para o popup de SLA (shell) não interromper a
  // resposta a este lead. Só publica seleção não-nula: o popup já grava o lead
  // antes de navegar pelo "Responder agora", e limpar no mount apagaria isso.
  const selectedConvId = selectedConversation?.id ?? null;
  const selectedLeadId = (selectedConversation?.leads as Lead | undefined | null)?.id ?? null;
  useEffect(() => {
    if (selectedConvId) setActiveConversation({ conversationId: selectedConvId, leadId: selectedLeadId });
  }, [selectedConvId, selectedLeadId]);
  useEffect(() => () => setActiveConversation({ conversationId: null, leadId: null }), []);
```

(`useEffect` e `Lead` já estão importados no arquivo. Confira e ajuste se não estiverem.)

- [ ] **Step 6: Typecheck**

Run: `npx tsc --noEmit -p .`
Expected: sem erros novos em `conversas/page.tsx` e `active-conversation.ts`

---

### Task 3: `useOverdueLeads` aceita limite e expõe a janela

**Files:**
- Modify: `frontend/src/hooks/use-overdue-leads.ts`

- [ ] **Step 1: Adicionar a janela em `OverdueLead`**

```ts
export interface OverdueLead {
  conversationId: string;
  leadId: string;
  leadName: string;
  leadPhone: string;
  channelId: string;
  userId: string;
  vendedorName: string;
  elapsedMinutes: number;
  /** Janela de atendimento do vendedor (minuto do dia, fuso SP). */
  windowStartMin: number;
  windowEndMin: number;
}
```

E no `result.push({...})` do `recompute`, acrescentar:

```ts
          windowStartMin: cfg.window_start_minute,
          windowEndMin: cfg.window_end_minute,
```

- [ ] **Step 2: Aceitar `targetMinutes` opcional**

Trocar a assinatura e a leitura do target:

```ts
export function useOverdueLeads(opts: { targetMinutes?: number } = {}): OverdueData {
  const targetOverride = opts.targetMinutes;
```

```ts
    const target = (targetOverride ?? settingsData?.target_minutes ?? 20) as number;
```

Incluir `targetOverride` nas deps do `useCallback` de `fetchAndCompute`: `[supabase, recompute, targetOverride]`.

- [ ] **Step 3: Nome de canal realtime único por instância**

O dashboard e o shell podem montar o hook ao mesmo tempo. Dois `supabase.channel()` com o mesmo tópico colidem. Trocar:

```ts
      .channel("overdue-leads-realtime")
```

por:

```ts
      .channel(`overdue-leads-realtime-${targetOverride ?? "cfg"}`)
```

- [ ] **Step 4: Typecheck e testes existentes**

Run: `npx tsc --noEmit -p . && npx vitest run src/lib/sla-rounds.test.ts`
Expected: sem erros novos. O único consumidor atual (`overdue-leads-section.tsx`) chama sem argumentos e continua compilando. Se não existir `sla-rounds.test.ts`, rode `npx vitest run src/lib`.

---

### Task 4: Componente `SlaReminderPopup` + montagem no shell

**Files:**
- Create: `frontend/src/components/sla-reminder-popup.tsx`
- Modify: `frontend/src/components/authenticated-shell.tsx`

Antes de escrever, invoque a skill `frontend-design:frontend-design` (regra do projeto). Siga a paleta do app: texto `#111111`, secundário `#7b7b78`, fundo `#faf9f6`, borda `#dedbd6`, acento `#ff5600`, `rounded-[8px]`.

- [ ] **Step 1: Criar o componente**

```tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { useCurrentRole } from "@/hooks/use-current-role";
import { useOverdueLeads, type OverdueLead } from "@/hooks/use-overdue-leads";
import { setActiveConversation, useActiveConversation } from "@/lib/active-conversation";
import { buildReminderQueue, formatWindowHour, SLA_REMINDER_MINUTES } from "@/lib/sla-reminder";
import { formatBusinessDuration } from "@/lib/business-hours";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

/** Popup de SLA: só para vendedor (admin acompanha pelo dashboard). */
export function SlaReminderPopup() {
  const { role, loading } = useCurrentRole();
  if (loading || role !== "vendedor") return null;
  return <SlaReminderQueue />;
}

function SlaReminderQueue() {
  const { leads } = useOverdueLeads({ targetMinutes: SLA_REMINDER_MINUTES });
  const pathname = usePathname();
  const router = useRouter();
  const active = useActiveConversation();

  // "Depois" vale só para a página atual: toda troca de rota reabre a fila inteira.
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  useEffect(() => { setDismissed(new Set()); }, [pathname]);

  const queue = useMemo(() => buildReminderQueue(leads, dismissed, active), [leads, dismissed, active]);
  const current = queue[0] ?? null;
  const lastText = useLastCustomerMessage(current?.conversationId ?? null);

  function dismissCurrent() {
    if (!current) return;
    const id = current.conversationId;
    setDismissed((prev) => new Set(prev).add(id));
  }

  function respond(lead: OverdueLead) {
    // Grava antes de navegar: evita o popup piscar até /conversas abrir a conversa.
    setActiveConversation({ conversationId: lead.conversationId, leadId: lead.leadId });
    router.push(`/conversas?lead_id=${lead.leadId}`);
  }

  if (!current) return null;

  return (
    <Dialog open onOpenChange={(open) => { if (!open) dismissCurrent(); }}>
      <DialogContent key={current.conversationId} showCloseButton={false} className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>Lead sem resposta há {formatBusinessDuration(current.elapsedMinutes)}</DialogTitle>
          <DialogDescription>
            {current.leadName}
            {current.leadPhone && current.leadPhone !== current.leadName ? ` · ${current.leadPhone}` : ""}
          </DialogDescription>
        </DialogHeader>

        {lastText && (
          <blockquote className="border-l-2 border-[#dedbd6] pl-3 text-[13px] text-[#313130] line-clamp-3 break-words">
            {lastText}
          </blockquote>
        )}

        <p className="rounded-[8px] bg-[#fff1e8] border border-[#ffd6bd] px-3 py-2 text-[13px] text-[#111111]">
          Lembre-se: seu horário de atendimento é das{" "}
          <strong>{formatWindowHour(current.windowStartMin)}</strong> às{" "}
          <strong>{formatWindowHour(current.windowEndMin)}</strong>. Responda os leads dentro desse horário.
        </p>

        {queue.length > 1 && (
          <p className="text-[12px] text-[#7b7b78]">+{queue.length - 1} lead(s) aguardando resposta</p>
        )}

        <DialogFooter>
          <button type="button" onClick={dismissCurrent}
            className="h-9 px-4 rounded-[8px] border border-[#dedbd6] text-[13px] text-[#313130] hover:bg-[#f0ede8]">
            Depois
          </button>
          <button type="button" onClick={() => respond(current)} autoFocus
            className="h-9 px-4 rounded-[8px] bg-[#ff5600] text-[13px] font-medium text-white hover:bg-[#e64d00]">
            Responder agora
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Última mensagem do cliente na conversa (1 query por popup exibido). Falha = null. */
function useLastCustomerMessage(conversationId: string | null): string | null {
  const [state, setState] = useState<{ id: string; text: string | null } | null>(null);
  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    const supabase = createClient();
    supabase
      .from("messages")
      .select("content")
      .eq("conversation_id", conversationId)
      .eq("sent_by", "user")
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle()
      .then(({ data }) => {
        if (!cancelled) setState({ id: conversationId, text: (data?.content as string | null) || null });
      }, () => { /* sem trecho: o popup abre mesmo assim */ });
    return () => { cancelled = true; };
  }, [conversationId]);
  return state && state.id === conversationId ? state.text : null;
}
```

O desenho visual pode ser refinado pela skill frontend-design. Mantenha o comportamento, os textos e os dois botões.

- [ ] **Step 2: Montar no shell**

Em `frontend/src/components/authenticated-shell.tsx`:

```ts
import { SlaReminderPopup } from "@/components/sla-reminder-popup";
```

e logo depois de `<NotificationToast />`:

```tsx
      <SlaReminderPopup />
```

- [ ] **Step 3: Typecheck e lint**

Run: `npx tsc --noEmit -p . && npx eslint src/components/sla-reminder-popup.tsx src/components/authenticated-shell.tsx`
Expected: sem erros (depende das Tasks 1 a 3 estarem aplicadas; rodar ao final).

---

### Task 5 (orquestrador): integração, verificação e commit

- [ ] `npx tsc --noEmit -p .` limpo
- [ ] `npx vitest run` com a suíte inteira verde
- [ ] `npx next build` (ou `npm run build`) passando
- [ ] Revisão de código do diff
- [ ] Commit na branch `feat/sla-popup-40min`: spec, plano e implementação
- [ ] Push para `master` só com autorização do usuário (CLAUDE.md §1)
