# Ficha do lead: ações no topo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Barra fixa no topo da ficha do lead com Registrar Venda, Fazer Orçamento e Salvar alterações (sempre visível, desabilitado sem edição).

**Architecture:** Só `LeadDetailModal` muda. Nova `<div data-testid="lead-detail-actions">` entre o cabeçalho e as abas (fora da área com scroll). O botão Salvar sai do cabeçalho; o bloco "Vendas" do fim de "Dados Gerais" é removido; `QuoteCreateModal` é montado igual ao `SaleCreateModal` (com `stopPropagation`).

**Tech Stack:** Next.js / React, Tailwind, vitest + @testing-library/react (sem jest-dom).

Spec: `docs/superpowers/specs/2026-10-14-ficha-lead-acoes-no-topo-design.md`

---

### Task 1: Barra de ações no topo

**Files:**
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx`
- Test: `frontend/src/components/leads/lead-detail-modal.test.tsx`

- [ ] **Step 1: Ajustar testes (falhando)**

No topo do teste, mockar o modal de orçamento expondo as props, e o de venda idem:

```tsx
vi.mock("@/components/sales/sale-create-modal", () => ({
  SaleCreateModal: (p: { leadId?: string }) => <div data-testid="sale-modal">{p.leadId}</div>,
}));
vi.mock("@/components/quotes/quote-create-modal", () => ({
  QuoteCreateModal: (p: { leadId?: string; currentUserEmail?: string }) => (
    <div data-testid="quote-modal">{p.leadId}|{p.currentUserEmail}</div>
  ),
}));
```

Helpers:

```tsx
const barra = () => screen.getByTestId("lead-detail-actions");
const botaoSalvar = () => screen.getByRole("button", { name: /Salvar altera/ }) as HTMLButtonElement;
```

Substituir o describe "Salvar alterações no cabeçalho" por "barra de ações no topo":

```tsx
describe("LeadDetailModal — barra de ações no topo", () => {
  it("ao abrir, mostra Registrar Venda, Fazer Orçamento e Salvar alterações na barra", () => {
    renderModal();
    for (const nome of [/Registrar Venda/, /Fazer Orçamento/, /Salvar altera/]) {
      const b = screen.getByRole("button", { name: nome });
      expect(barra().contains(b)).toBe(true);
      expect(screen.getAllByRole("button", { name: nome })).toHaveLength(1);
    }
  });

  it("sem edição, Salvar fica visível e desabilitado; editando, habilita", () => {
    renderModal();
    expect(botaoSalvar().disabled).toBe(true);
    expect(botaoSalvar().textContent).toBe("Salvar alterações");
    fireEvent.change(screen.getByDisplayValue("teste"), { target: { value: "teste agente" } });
    expect(botaoSalvar().disabled).toBe(false);
  });

  it("trocando de aba, a barra continua com os 3 botões", () => {
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Metricas" }));
    expect(barra().textContent).toContain("Registrar Venda");
    expect(barra().textContent).toContain("Fazer Orçamento");
    expect(barra().textContent).toContain("Salvar alterações");
  });

  it("Registrar Venda abre o modal de venda do lead", () => {
    renderModal();
    expect(screen.queryByTestId("sale-modal")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Registrar Venda/ }));
    expect(screen.getByTestId("sale-modal").textContent).toBe("lead-1");
  });

  it("Fazer Orçamento abre o modal de orçamento com o lead e o usuário", () => {
    renderModal();
    expect(screen.queryByTestId("quote-modal")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Fazer Orçamento/ }));
    expect(screen.getByTestId("quote-modal").textContent).toBe("lead-1|teste@x.com");
  });

  it("clicar salva só o campo alterado, mostra Salvando... e volta a desabilitar", async () => {
    let terminar!: () => void;
    const onSave = vi.fn(() => new Promise<void>((r) => { terminar = r; }));
    renderModal(onSave);
    fireEvent.change(screen.getByDisplayValue("teste"), { target: { value: "teste agente" } });
    fireEvent.click(botaoSalvar());

    expect(onSave).toHaveBeenCalledWith("lead-1", { nome_fantasia: "teste agente" });
    const salvando = screen.getByRole("button", { name: "Salvando..." }) as HTMLButtonElement;
    expect(salvando.disabled).toBe(true);

    await act(async () => { terminar(); });
    expect(botaoSalvar().disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Salvando..." })).toBeNull();
  });
});
```

Nos testes de endereço, trocar `botaoSalvar()!` por `botaoSalvar()` (agora `getByRole`). Remover a const `header` se ficar sem uso.

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd frontend && npx vitest run src/components/leads/lead-detail-modal.test.tsx`
Expected: FAIL (sem `lead-detail-actions`, sem "Fazer Orçamento").

- [ ] **Step 3: Implementar em `lead-detail-modal.tsx`**

1. Import: `import { QuoteCreateModal } from "@/components/quotes/quote-create-modal";`
2. Estado: `const [showCreateQuote, setShowCreateQuote] = useState(false);` ao lado de `showCreateSale`.
3. No cabeçalho, remover o bloco `{dirty && (<button ...>Salvar alterações</button>)}` (o status do Bling fica).
4. Logo depois do `</div>` do cabeçalho e antes de `{/* Tabs */}`:

```tsx
        {/* Ações — fora da área com scroll, visíveis em qualquer aba. */}
        <div
          data-testid="lead-detail-actions"
          className="px-6 py-3 border-b border-[#dedbd6] flex items-center gap-2"
        >
          <button
            type="button"
            onClick={() => setShowCreateSale(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-[#1f9d57] px-3 py-1.5 text-[13px] font-medium text-white hover:bg-[#1b8a4c]"
          >
            Registrar Venda
          </button>
          <button
            type="button"
            onClick={() => setShowCreateQuote(true)}
            className="inline-flex items-center gap-1.5 rounded-md border border-[#dedbd6] bg-white px-3 py-1.5 text-[13px] font-medium text-[#111111] hover:border-[#111111] hover:bg-[#faf9f6] transition-colors"
          >
            Fazer Orçamento
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!dirty || saving}
            className="ml-auto h-8 bg-[#111111] text-white px-3 rounded-[4px] text-[13px] border border-[#111111] transition-colors hover:bg-white hover:text-[#111111] disabled:opacity-40 disabled:hover:bg-[#111111] disabled:hover:text-white disabled:cursor-not-allowed"
          >
            {saving ? "Salvando..." : "Salvar alterações"}
          </button>
        </div>
```

5. Remover o bloco "Vendas" no fim de "Dados Gerais" (o comentário "A lista de oportunidades virou a aba Funis..." + a `<div className="mt-5 pt-4 border-t ...">` com o botão Registrar Venda).
6. Depois do bloco `{showCreateSale && (...)}`:

```tsx
      {showCreateQuote && (
        // Mesmo motivo do SaleCreateModal: cliques no portal não podem fechar a ficha.
        <div onClick={(e) => e.stopPropagation()}>
          <QuoteCreateModal
            leadId={lead.id}
            currentUserEmail={currentUserEmail}
            onClose={() => setShowCreateQuote(false)}
            onSaved={() => setShowCreateQuote(false)}
          />
        </div>
      )}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd frontend && npx vitest run src/components/leads/lead-detail-modal.test.tsx`
Expected: PASS.

- [ ] **Step 5: Suíte, tipos, build**

Run: `cd frontend && npm run type-check && npm run test && npm run build` (build com envs placeholder do CI se faltar `.env`).
Expected: tudo verde.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/leads/lead-detail-modal.tsx frontend/src/components/leads/lead-detail-modal.test.tsx
git commit -m "feat(leads): ficha com Registrar Venda, Fazer Orçamento e Salvar no topo"
```

### Task 2: Verificação visual em modo teste

- [ ] Subir `npm run dev` no worktree e tentar o print de `/leads` com a ficha aberta (`print-frontend.mjs`). Se o login automático não servir para a origem local, montar uma página de verificação estática não é permitido em produção — registrar que o print visual fica para a produção e usar os testes como prova.
