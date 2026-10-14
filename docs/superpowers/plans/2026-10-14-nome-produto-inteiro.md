# Nome do produto inteiro no orçamento e na venda — plano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** o nome do produto aparece inteiro (quebrando linha, sem "…") na linha do item e na lista de busca do `BlingOrderForm`, usado pelos painéis Novo orçamento e Registrar venda.

**Architecture:** mudança só de classes Tailwind em `frontend/src/components/sales/bling-order-form.tsx`. Botão do produto deixa de ter altura fixa e de truncar; a linha da grade alinha ao topo; a lista de busca fica mais larga e o nome quebra. Spec: `docs/superpowers/specs/2026-10-14-nome-produto-inteiro-design.md`.

**Tech Stack:** Next.js, React, Tailwind 4, Radix Popover, Vitest + Testing Library (jsdom).

---

### Task 1: nome inteiro no botão do item e na lista de busca

**Files:**
- Modify: `frontend/src/components/sales/bling-order-form.tsx` (const `grid` ~l.147; `opcaoDeProduto` ~l.479-481; linha da grade ~l.571; botão do produto ~l.576-586; `PopoverContent` ~l.589; span do total ~l.640; botão remover ~l.650)
- Test: `frontend/src/components/sales/bling-order-form.test.tsx` (novo `describe` no fim)

- [ ] **Step 1: teste que falha** — acrescentar no fim de `bling-order-form.test.tsx` (ajuste o import para incluir `fireEvent`):

```tsx
/**
 * Cartão 7615bf70: o nome do produto aparecia cortado com "…" na linha do
 * item e na lista de busca, e o vendedor não sabia qual item estava escolhido.
 */
const NOME_LONGO =
  "Café Canastra Especial Torra Média Moído 500g Caixa com 12 Unidades";

const linhaLonga = {
  blingProductId: 77,
  descricao: NOME_LONGO,
  codigo: "CC-500-12",
  unidade: "CX",
  quantidade: 1,
  valorUnitario: 10,
  descontoPercentual: 0,
};

describe("BlingOrderForm — nome do produto inteiro", () => {
  it("na linha do item o nome quebra linha em vez de ser cortado", () => {
    mockFetchVazio();
    render(<BlingOrderForm meta={META} onChange={vi.fn()} initialLines={[linhaLonga]} />);
    const nome = screen.getByText(NOME_LONGO);
    expect(nome.className).not.toMatch(/\btruncate\b/);
    expect(nome.className).toMatch(/\bbreak-words\b/);
    const botao = nome.closest("button")!;
    expect(botao.className).not.toMatch(/(^|\s)h-\[34px\]/);
    expect(botao.className).toMatch(/\bmin-h-\[34px\]/);
  });

  it("na lista de busca o nome quebra linha e a lista é mais larga que a coluna", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(
        resposta({
          data: [
            { id: 77, codigo: "CC-500-12", nome: NOME_LONGO, preco: 10, unidade: "CX", saldo_virtual: 5 },
          ],
        }),
      ),
    ) as unknown as typeof fetch;
    render(<BlingOrderForm meta={META} onChange={vi.fn()} />);
    fireEvent.click(screen.getByText("Selecione o produto").closest("button")!);
    const opcao = await screen.findByText(NOME_LONGO);
    expect(opcao.className).not.toMatch(/\btruncate\b/);
    expect(opcao.className).toMatch(/\bbreak-words\b/);
    const lista = screen.getByPlaceholderText("Buscar por nome ou SKU...").closest(
      "[data-radix-popper-content-wrapper] > *, [role='dialog']",
    ) as HTMLElement;
    expect(lista.className).toMatch(/\bmin-w-\[420px\]/);
  });
});
```

Se o Radix Popover não abrir com `fireEvent.click` no jsdom, use `fireEvent.pointerDown` + `fireEvent.click`; se ainda assim não abrir, troque o seletor do `closest` pela busca do elemento com a classe `min-w-` acima do input. Não remova o teste.

- [ ] **Step 2: rodar e ver falhar**

Run (em `frontend/`): `npx vitest run src/components/sales/bling-order-form.test.tsx`
Expected: os 2 testes novos FALHAM (classe `truncate` presente / `min-w-[280px]`); os antigos passam.

- [ ] **Step 3: implementação**

1. `grid` sem alinhamento próprio:
```ts
const grid = "grid grid-cols-[minmax(0,1fr)_58px_92px_58px_86px_26px] gap-2";
```
2. Cabeçalho da tabela: `className={`${grid} items-center bg-[#faf9f6] ...`}` (acrescentar `items-center`).
3. Linha do item: `className={`${grid} items-start px-3 py-2 border-b border-[#dedbd6] last:border-b-0`}`.
4. Botão do produto: trocar `h-[34px]` por `min-h-[34px] py-1.5` e o span:
```tsx
<span className="min-w-0 whitespace-normal break-words leading-snug">
```
5. Span do total: acrescentar `leading-[34px]` (fica na altura dos inputs). Botão remover: acrescentar `mt-1` (centraliza o de 26px contra os 34px).
6. `PopoverContent`: `className="p-0 w-(--radix-popover-trigger-width) min-w-[420px] max-w-[calc(100vw-2rem)]"`.
7. `opcaoDeProduto`: botão com `items-start` em vez de `items-center`; nome:
```tsx
<span className="block whitespace-normal break-words text-[13px] leading-snug text-[#111111]">{p.nome}</span>
```
e o `CheckIcon` ganha `mt-0.5`.

- [ ] **Step 4: rodar e ver passar** — mesmo comando do Step 2. Expected: todos PASS.

- [ ] **Step 5: suíte, lint e build** (em `frontend/`): `npx vitest run`, `npm run lint`, `npx tsc --noEmit`. Expected: sem falhas novas (comparar com `origin/master` se algo já falhava antes).

- [ ] **Step 6: commit**
```bash
git add frontend/src/components/sales/bling-order-form.tsx frontend/src/components/sales/bling-order-form.test.tsx
git commit -m "fix(itens): nome do produto aparece inteiro no orçamento e na venda"
```

### Task 2: conferência visual em modo teste (controlador)

- [ ] `next dev` a partir de `frontend/` do worktree, com cópia do `.env.local` do frontend principal (não imprimir).
- [ ] Com Playwright: login do usuário de teste, abrir Novo orçamento e Registrar venda, escolher produto de nome longo, abrir a lista de busca; prints. Não salvar nada.
- [ ] Olhar cada PNG: nome inteiro, campos alinhados, lista sem estourar o painel.
