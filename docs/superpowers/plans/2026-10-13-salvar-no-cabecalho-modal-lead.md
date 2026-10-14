# Botão "Salvar alterações" no cabeçalho do modal de lead — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mover o botão "Salvar alterações" do rodapé da aba "Dados" para o cabeçalho do `LeadDetailModal`, visível só com alteração pendente, em qualquer aba.

**Architecture:** Mudança só de JSX em `lead-detail-modal.tsx`; `dirty`, `saving` e `handleSave` já existem e não mudam. Um teste de componente novo (vitest + Testing Library, jsdom) cobre o comportamento.

**Tech Stack:** Next.js (App Router), React, Tailwind, vitest, @testing-library/react (sem jest-dom).

Spec: `docs/superpowers/specs/2026-10-13-salvar-no-cabecalho-modal-lead-design.md`

---

### Task 1: Botão no cabeçalho (TDD)

**Files:**
- Create: `frontend/src/components/leads/lead-detail-modal.test.tsx`
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx` (div do cabeçalho ~linha 219; bloco `{dirty && (...)}` ~linhas 433-443)

- [ ] **Step 1: Escrever o teste que falha**

`frontend/src/components/leads/lead-detail-modal.test.tsx`:

```tsx
/**
 * @vitest-environment jsdom
 *
 * Sem `@testing-library/jest-dom` (não está nas dependências): asserções com a API crua do
 * DOM/`screen`, mesmo padrão de lead-timeline.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Lead } from "@/lib/types";

// Filhos com fetch/Supabase próprios não interessam aqui.
vi.mock("./lead-broadcast-history", () => ({ LeadBroadcastHistory: () => null }));
vi.mock("./lead-bling-section", () => ({ LeadBlingSection: () => null }));
vi.mock("./lead-funis-tab", () => ({ LeadFunisTab: () => null }));
vi.mock("./lead-timeline", () => ({ LeadTimeline: () => null }));
vi.mock("@/components/leads/lead-origin-block", () => ({ LeadOriginBlock: () => null }));
vi.mock("@/components/sales/sale-create-modal", () => ({ SaleCreateModal: () => null }));
vi.mock("@/hooks/use-current-user", () => ({ useCurrentUserEmail: () => "teste@x.com" }));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({ select: () => ({ eq: () => Promise.resolve({ data: [] }) }) }),
  }),
}));

import { LeadDetailModal } from "./lead-detail-modal";

const LEAD = {
  id: "lead-1",
  name: "Lead Teste",
  phone: "5534999999999",
  email: "",
  instagram: "",
  company: "teste",
  created_at: "2026-10-01T12:00:00Z",
  last_msg_at: null,
  first_response_at: null,
} as unknown as Lead;

function renderModal(onSave = vi.fn(() => Promise.resolve())) {
  render(
    <LeadDetailModal
      lead={LEAD}
      tags={[]}
      pipelines={[]}
      leadTagIds={[]}
      onClose={() => {}}
      onSave={onSave}
      onTagsChange={() => Promise.resolve()}
    />,
  );
  return onSave;
}

const header = () => screen.getByTestId("lead-detail-header");
const botaoSalvar = () => screen.queryByRole("button", { name: /Salvar altera/ });

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, status: 200, json: async () => [] } as Response),
  ) as unknown as typeof fetch;
});
afterEach(cleanup);

describe("LeadDetailModal — Salvar alterações no cabeçalho", () => {
  it("sem edição, não mostra o botão", () => {
    renderModal();
    expect(botaoSalvar()).toBeNull();
  });

  it("ao editar um campo, o botão aparece dentro do cabeçalho, com acento", () => {
    renderModal();
    fireEvent.change(screen.getByDisplayValue("teste"), { target: { value: "teste agente" } });
    const botao = botaoSalvar();
    expect(botao).not.toBeNull();
    expect(botao!.textContent).toBe("Salvar alterações");
    expect(header().contains(botao)).toBe(true);
    // Não existe uma segunda cópia no rodapé da aba.
    expect(screen.getAllByRole("button", { name: /Salvar altera/ })).toHaveLength(1);
  });

  it("trocando de aba depois de editar, o botão continua visível", () => {
    renderModal();
    fireEvent.change(screen.getByDisplayValue("teste"), { target: { value: "teste agente" } });
    fireEvent.click(screen.getByRole("button", { name: "Metricas" }));
    expect(botaoSalvar()).not.toBeNull();
  });

  it("clicar salva só o campo alterado, mostra Salvando... e some ao terminar", async () => {
    let terminar!: () => void;
    const onSave = vi.fn(() => new Promise<void>((r) => { terminar = r; }));
    renderModal(onSave);
    fireEvent.change(screen.getByDisplayValue("teste"), { target: { value: "teste agente" } });
    fireEvent.click(botaoSalvar()!);

    expect(onSave).toHaveBeenCalledWith("lead-1", { company: "teste agente" });
    const salvando = screen.getByRole("button", { name: "Salvando..." }) as HTMLButtonElement;
    expect(salvando.disabled).toBe(true);

    await act(async () => { terminar(); });
    expect(botaoSalvar()).toBeNull();
    expect(screen.queryByRole("button", { name: "Salvando..." })).toBeNull();
  });
});
```

Se `getByDisplayValue("teste")` achar mais de um input (ex.: Nome também "teste"), o LEAD acima já usa nomes distintos; ajustar só o dado do teste, nunca o componente.

- [ ] **Step 2: Rodar e ver falhar**

Run (em `frontend/`): `npx vitest run src/components/leads/lead-detail-modal.test.tsx`
Expected: FAIL — `Unable to find an element by: [data-testid="lead-detail-header"]` e texto "Salvar alteracoes" sem acento.

- [ ] **Step 3: Implementação mínima**

Em `lead-detail-modal.tsx`:

1. Na div do cabeçalho, adicionar o testid:

```tsx
        {/* Header */}
        <div data-testid="lead-detail-header" className="px-6 py-5 border-b border-[#dedbd6] flex justify-between items-center">
```

2. No grupo da direita (`<div className="flex items-center gap-2.5">`), como PRIMEIRO filho, antes do `<span>` da temperatura:

```tsx
            {dirty && (
              <button
                onClick={handleSave}
                disabled={saving}
                className="h-8 bg-[#111111] text-white px-3 rounded-[4px] text-[13px] border border-[#111111] transition-colors hover:bg-white hover:text-[#111111] disabled:opacity-50"
              >
                {saving ? "Salvando..." : "Salvar alterações"}
              </button>
            )}
```

3. Remover por inteiro o bloco antigo no fim da aba "Dados":

```tsx
              {dirty && (
                <div className="mt-4 flex justify-end">
                  <button
                    onClick={handleSave}
                    ...
                    {saving ? "Salvando..." : "Salvar alteracoes"}
                  </button>
                </div>
              )}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `npx vitest run src/components/leads/lead-detail-modal.test.tsx`
Expected: 4 passed.

- [ ] **Step 5: Suíte, lint e tipos**

Run (em `frontend/`): `npm test` → tudo verde (mesmo número de falhas pré-existentes que a master, idealmente 0).
Run: `npx eslint src/components/leads/lead-detail-modal.tsx src/components/leads/lead-detail-modal.test.tsx` → sem erros.
Run: `npx tsc --noEmit -p .` → sem erros novos.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/leads/lead-detail-modal.tsx frontend/src/components/leads/lead-detail-modal.test.tsx
git commit -m "feat(leads): botao Salvar alteracoes no cabecalho do modal do lead"
```

### Task 2: Verificação em modo teste (controlador, não subagente)

- [ ] `npm run build` em `frontend/`.
- [ ] `next dev` local no worktree; abrir `/leads?lead_id=8c064847-27f3-42a5-82b6-2c0ecc071a1d`, editar Empresa "teste" → "teste agente", print com botão no topo, salvar, conferir no banco (SELECT company), print pós-salvar, restaurar "teste" e conferir no banco.
