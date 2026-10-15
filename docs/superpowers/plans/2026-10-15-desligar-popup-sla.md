# Desligar o pop-up de SLA — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O CRM deixa de mostrar o pop-up "Lead sem resposta há X" para todos.

**Architecture:** Só o `AuthenticatedShell` para de montar `<SlaReminderPopup />`. O componente e a lib dele continuam no repositório, sem uso. Um teste do shell trava a ausência.

**Tech Stack:** Next.js (App Router), React, Vitest + Testing Library (jsdom).

Spec: `docs/superpowers/specs/2026-10-15-desligar-popup-sla-design.md`

---

### Task 1: Shell sem o pop-up de SLA

**Files:**
- Create: `frontend/src/components/authenticated-shell.test.tsx`
- Modify: `frontend/src/components/authenticated-shell.tsx` (import da linha 8 e `<SlaReminderPopup />` da linha 84)

- [ ] **Step 1: Escrever o teste que falha**

```tsx
/**
 * @vitest-environment jsdom
 *
 * O pop-up de SLA ("Lead sem resposta há X") foi desligado a pedido da operação
 * (cartão ca54ae27). O shell não pode voltar a montá-lo sem uma decisão explícita.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  usePathname: () => "/conversas",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/components/sidebar", () => ({ Sidebar: () => null }));
vi.mock("@/components/notification-toast", () => ({ NotificationToast: () => null }));
vi.mock("@/hooks/use-presence", () => ({
  PresenceProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/hooks/use-realtime-keepalive", () => ({ useRealtimeKeepAlive: () => {} }));
vi.mock("@/components/sla-reminder-popup", () => ({
  SlaReminderPopup: () => <div data-testid="sla-popup">Lead sem resposta há</div>,
}));

import { AuthenticatedShell } from "./authenticated-shell";

afterEach(() => cleanup());

describe("AuthenticatedShell", () => {
  it("não monta o pop-up de SLA", () => {
    render(<AuthenticatedShell><p>conteúdo</p></AuthenticatedShell>);
    expect(screen.getByText("conteúdo")).toBeTruthy();
    expect(screen.queryByTestId("sla-popup")).toBeNull();
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd frontend && npx vitest run src/components/authenticated-shell.test.tsx`
Expected: FAIL — `queryByTestId("sla-popup")` encontra o elemento.

- [ ] **Step 3: Implementação mínima**

Em `authenticated-shell.tsx`: remover `import { SlaReminderPopup } from "@/components/sla-reminder-popup";` e trocar `<SlaReminderPopup />` por:

```tsx
      {/* Pop-up de SLA desligado (cartão ca54ae27). Para religar: <SlaReminderPopup /> de @/components/sla-reminder-popup. */}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd frontend && npx vitest run src/components/authenticated-shell.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/authenticated-shell.tsx frontend/src/components/authenticated-shell.test.tsx
git commit -m "feat(sla): desliga o pop-up de lead sem resposta"
```

### Task 2: Verificação

- [ ] `cd frontend && npx vitest run` — suíte inteira verde (inclui os testes do pop-up isolado).
- [ ] `npx tsc --noEmit` e `npm run lint` sem erro novo.
- [ ] `npm run dev` e print de `/conversas` logado.
