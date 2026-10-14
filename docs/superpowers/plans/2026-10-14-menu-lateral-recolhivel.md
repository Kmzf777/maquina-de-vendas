# Menu lateral recolhível — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O menu da esquerda do CRM recolhe para só ícones. Em /conversas, ele recolhe sozinho ao abrir venda/orçamento, para o painel ficar ao lado do chat a partir de 1100 px.

**Architecture:**
- Um contexto novo (`MenuLateralProvider`, em `components/menu-lateral.tsx`) é o dono do estado do menu: recolhido ou não, e se foi o painel que recolheu.
- A preferência manual fica no `localStorage`.
- O `AuthenticatedShell` envolve tudo com o provider e passa o estado ao `Sidebar`.
- O `ContactDetail` avisa quando um painel de venda/orçamento abre ou fecha (`onPainelAbertoChange`). A página /conversas recolhe ou restaura o menu por esse aviso e baixa o corte do modo acoplado para 1100 px.

**Tech Stack:** Next.js (App Router), React 19, Tailwind, Vitest + Testing Library (jsdom via docblock).

Spec: `docs/superpowers/specs/2026-10-14-menu-lateral-recolhivel-design.md`

**Decisão técnica (registrada):**
- O `ContactDetail` já fixa o modo do painel (acoplado × sobreposto) **na abertura**, então nada remonta no meio do pedido.
- Como o menu recolhe ao abrir o painel, na abertura o menu "vai estar recolhido". Por isso a página acopla quando a tela tem pelo menos 1100 px, que é a regra da spec avaliada no momento da abertura.
- Se o vendedor reabrir o menu com o painel acoplado, o painel continua acoplado até fechar, porque o modo é fixo.

Todos os comandos rodam em `ValerIA/.claude/worktrees/agente-a22d0f72/frontend`.

---

### Task 1: Estado do menu (`components/menu-lateral.tsx`)

**Files:**
- Create: `src/components/menu-lateral.tsx`
- Test: `src/components/menu-lateral.test.tsx`

API:
```ts
export type EstadoMenu = { recolhido: boolean; peloPainel: boolean };
export type AcaoMenu =
  | { tipo: "alternar" }
  | { tipo: "recolherPeloPainel" }
  | { tipo: "restaurarDoPainel" }
  | { tipo: "carregar"; recolhido: boolean };
export function reduzirMenu(estado: EstadoMenu, acao: AcaoMenu): EstadoMenu;
export const CHAVE_MENU = "valeria:menu-recolhido";
export function MenuLateralProvider({ children }: { children: React.ReactNode }): JSX.Element;
export function useMenuLateral(): {
  recolhido: boolean;
  alternar: () => void;
  recolherPeloPainel: () => void;
  restaurarDoPainel: () => void;
};
```

Regras:
- `alternar`: inverte `recolhido`, zera `peloPainel` e grava `"1"`/`"0"` no `localStorage`. A vontade do vendedor prevalece.
- `recolherPeloPainel`: se já está recolhido, não muda nada (`peloPainel` continua `false`). Senão, `{recolhido: true, peloPainel: true}`. **Não grava** no `localStorage`: é temporário.
- `restaurarDoPainel`: só age se `peloPainel`, e aí volta a `{recolhido:false, peloPainel:false}`.
- `carregar`: lê o `localStorage` num `useEffect` após montar. O primeiro render é sempre aberto, igual ao SSR, para não dar erro de hidratação.
- Sem provider, `useMenuLateral()` devolve `{recolhido:false}` e funções vazias, para os testes e telas existentes não quebrarem.

- [ ] **Step 1: Teste que falha** — `src/components/menu-lateral.test.tsx`:

```tsx
/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { CHAVE_MENU, MenuLateralProvider, reduzirMenu, useMenuLateral } from "./menu-lateral";

const ABERTO = { recolhido: false, peloPainel: false };

describe("reduzirMenu", () => {
  it("alternar inverte e zera o 'pelo painel'", () => {
    expect(reduzirMenu(ABERTO, { tipo: "alternar" })).toEqual({ recolhido: true, peloPainel: false });
    expect(reduzirMenu({ recolhido: true, peloPainel: true }, { tipo: "alternar" })).toEqual(ABERTO);
  });
  it("painel recolhe o menu aberto e restaura ao fechar", () => {
    const r = reduzirMenu(ABERTO, { tipo: "recolherPeloPainel" });
    expect(r).toEqual({ recolhido: true, peloPainel: true });
    expect(reduzirMenu(r, { tipo: "restaurarDoPainel" })).toEqual(ABERTO);
  });
  it("menu recolhido à mão continua recolhido ao fechar o painel", () => {
    const mao = { recolhido: true, peloPainel: false };
    const r = reduzirMenu(mao, { tipo: "recolherPeloPainel" });
    expect(r).toEqual(mao);
    expect(reduzirMenu(r, { tipo: "restaurarDoPainel" })).toEqual(mao);
  });
  it("reabrir à mão com o painel aberto vence: fechar o painel não mexe", () => {
    let e = reduzirMenu(ABERTO, { tipo: "recolherPeloPainel" });
    e = reduzirMenu(e, { tipo: "alternar" });
    expect(reduzirMenu(e, { tipo: "restaurarDoPainel" })).toEqual(ABERTO);
  });
});

function Sonda() {
  const m = useMenuLateral();
  return (
    <div>
      <span data-testid="estado">{m.recolhido ? "recolhido" : "aberto"}</span>
      <button onClick={m.alternar}>alternar</button>
      <button onClick={m.recolherPeloPainel}>painel abre</button>
      <button onClick={m.restaurarDoPainel}>painel fecha</button>
    </div>
  );
}

describe("MenuLateralProvider", () => {
  beforeEach(() => localStorage.clear());
  afterEach(cleanup);

  it("lembra a escolha manual no localStorage", () => {
    render(<MenuLateralProvider><Sonda /></MenuLateralProvider>);
    act(() => screen.getByText("alternar").click());
    expect(screen.getByTestId("estado").textContent).toBe("recolhido");
    expect(localStorage.getItem(CHAVE_MENU)).toBe("1");
  });
  it("nasce recolhido se a escolha salva foi recolher", () => {
    localStorage.setItem(CHAVE_MENU, "1");
    render(<MenuLateralProvider><Sonda /></MenuLateralProvider>);
    expect(screen.getByTestId("estado").textContent).toBe("recolhido");
  });
  it("recolher pelo painel não grava preferência", () => {
    render(<MenuLateralProvider><Sonda /></MenuLateralProvider>);
    act(() => screen.getByText("painel abre").click());
    expect(screen.getByTestId("estado").textContent).toBe("recolhido");
    expect(localStorage.getItem(CHAVE_MENU)).toBeNull();
    act(() => screen.getByText("painel fecha").click());
    expect(screen.getByTestId("estado").textContent).toBe("aberto");
  });
  it("sem provider: aberto e funções inertes", () => {
    render(<Sonda />);
    act(() => screen.getByText("alternar").click());
    expect(screen.getByTestId("estado").textContent).toBe("aberto");
  });
});
```

- [ ] **Step 2:** `npx vitest run src/components/menu-lateral.test.tsx`. Esperado: FAIL, porque o módulo não existe.
- [ ] **Step 3: Implementar** — `src/components/menu-lateral.tsx`:

```tsx
"use client";

/**
 * Estado do menu lateral (desktop): aberto (220 px) ou recolhido (só ícones).
 *
 * Cartão a22d0f72: o painel de orçamento/venda tampava o chat em telas < 1280
 * e o vendedor não conseguia copiar CPF/endereço da conversa. Recolher o menu
 * devolve ~164 px, o bastante para o painel caber ao lado do chat a partir de
 * 1100 px. O painel recolhe o menu sozinho ao abrir e devolve ao fechar —
 * só se foi ele quem recolheu; a escolha manual (salva no localStorage)
 * sempre vence.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer } from "react";

export type EstadoMenu = { recolhido: boolean; peloPainel: boolean };
export type AcaoMenu =
  | { tipo: "alternar" }
  | { tipo: "recolherPeloPainel" }
  | { tipo: "restaurarDoPainel" }
  | { tipo: "carregar"; recolhido: boolean };

export const CHAVE_MENU = "valeria:menu-recolhido";

export function reduzirMenu(estado: EstadoMenu, acao: AcaoMenu): EstadoMenu {
  switch (acao.tipo) {
    case "alternar":
      return { recolhido: !estado.recolhido, peloPainel: false };
    case "recolherPeloPainel":
      return estado.recolhido ? estado : { recolhido: true, peloPainel: true };
    case "restaurarDoPainel":
      return estado.peloPainel ? { recolhido: false, peloPainel: false } : estado;
    case "carregar":
      return { recolhido: acao.recolhido, peloPainel: false };
  }
}

type MenuLateral = {
  recolhido: boolean;
  alternar: () => void;
  recolherPeloPainel: () => void;
  restaurarDoPainel: () => void;
};

const nada = () => {};
const MenuLateralContext = createContext<MenuLateral>({
  recolhido: false,
  alternar: nada,
  recolherPeloPainel: nada,
  restaurarDoPainel: nada,
});

export function MenuLateralProvider({ children }: { children: React.ReactNode }) {
  const [estado, despachar] = useReducer(reduzirMenu, { recolhido: false, peloPainel: false });

  // Depois de montar: o servidor não conhece o localStorage, e nascer aberto
  // nos dois lados evita erro de hidratação.
  useEffect(() => {
    try {
      if (localStorage.getItem(CHAVE_MENU) === "1") despachar({ tipo: "carregar", recolhido: true });
    } catch {}
  }, []);

  // Grava só a escolha manual: o recolher do painel é temporário.
  const alternar = useCallback(() => {
    const novo = !estado.recolhido;
    despachar({ tipo: "alternar" });
    try {
      localStorage.setItem(CHAVE_MENU, novo ? "1" : "0");
    } catch {}
  }, [estado.recolhido]);

  const recolherPeloPainel = useCallback(() => despachar({ tipo: "recolherPeloPainel" }), []);
  const restaurarDoPainel = useCallback(() => despachar({ tipo: "restaurarDoPainel" }), []);

  const valor = useMemo(
    () => ({ recolhido: estado.recolhido, alternar, recolherPeloPainel, restaurarDoPainel }),
    [estado.recolhido, alternar, recolherPeloPainel, restaurarDoPainel],
  );
  return <MenuLateralContext value={valor}>{children}</MenuLateralContext>;
}

export function useMenuLateral(): MenuLateral {
  return useContext(MenuLateralContext);
}
```

- [ ] **Step 4:** `npx vitest run src/components/menu-lateral.test.tsx`. Esperado: PASS (8 testes).
- [ ] **Step 5:** não commitar. O orquestrador commita.

---

### Task 2: Sidebar com modo recolhido (`components/sidebar.tsx`)

**Files:**
- Modify: `src/components/sidebar.tsx`
- Test: `src/components/sidebar.test.tsx`

Nova assinatura: `Sidebar({ onClose, recolhido = false, onAlternar }: { onClose?: () => void; recolhido?: boolean; onAlternar?: () => void })`.

**Aberto (`recolhido=false`):** igual a hoje. Se `onAlternar` vier, aparece no cabeçalho, à direita do logo, um botão `aria-label="Recolher menu"` com ícone de chevron duplo para a esquerda (`M18.75 19.5l-7.5-7.5 7.5-7.5m-6 15L5.25 12l7.5-7.5`).

**Recolhido:**
- `<aside>` com `w-[56px]` no lugar de `w-[220px]`.
- Cabeçalho: `px-0 justify-center`. O logo "V" vira o próprio botão de abrir, com `aria-label="Abrir menu"` e `title="Abrir menu"`, e o texto "ValerIA·" some.
- `nav` com `px-2`. Os rótulos de grupo (`<p>` uppercase) somem; no lugar, um separador `border-t border-[#dedbd6] mx-2` entre grupos (exceto o primeiro).
- Cada `Link` tem `title={item.label}` e `aria-label={item.label}`, `justify-center px-0 py-2`, e só o ícone, sem texto.
- Rodapé: só o avatar e o botão Sair (`aria-label="Sair"`), empilhados (`flex-col`), sem o e-mail.
- `transition-[width] duration-150` no `aside`.

`onClose` (drawer mobile) segue igual. O drawer nunca passa `recolhido`/`onAlternar`.

- [ ] **Step 1: Teste que falha** — `src/components/sidebar.test.tsx`:

```tsx
/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  usePathname: () => "/conversas",
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: {
      getSession: () => Promise.resolve({ data: { session: { user: { email: "joao@cafecanastra.com", app_metadata: { role: "vendedor" } } } } }),
      signOut: () => Promise.resolve(),
    },
  }),
}));

import { Sidebar } from "./sidebar";

afterEach(cleanup);

describe("Sidebar", () => {
  it("aberto: mostra os nomes e o botão de recolher", () => {
    const onAlternar = vi.fn();
    render(<Sidebar onAlternar={onAlternar} />);
    expect(screen.getByText("WhatsApp")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Recolher menu" }));
    expect(onAlternar).toHaveBeenCalledTimes(1);
  });

  it("recolhido: só ícones, com o nome na dica, e botão de abrir", () => {
    const onAlternar = vi.fn();
    const { container } = render(<Sidebar recolhido onAlternar={onAlternar} />);
    expect(screen.queryByText("WhatsApp")).toBeNull();
    expect(screen.queryByText("Comunicação")).toBeNull();
    const link = screen.getByRole("link", { name: "WhatsApp" });
    expect(link.getAttribute("href")).toBe("/conversas");
    expect(link.getAttribute("title")).toBe("WhatsApp");
    expect(container.querySelector("aside")!.className).toContain("w-[56px]");
    fireEvent.click(screen.getByRole("button", { name: "Abrir menu" }));
    expect(onAlternar).toHaveBeenCalledTimes(1);
  });

  it("sem onAlternar (drawer mobile): sem botão de recolher", () => {
    render(<Sidebar onClose={() => {}} />);
    expect(screen.queryByRole("button", { name: "Recolher menu" })).toBeNull();
    expect(screen.getByRole("button", { name: "Fechar menu" })).toBeTruthy();
  });
});
```

- [ ] **Step 2:** `npx vitest run src/components/sidebar.test.tsx`. Esperado: FAIL, sem "Recolher menu".
- [ ] **Step 3:** implementar o descrito acima no `sidebar.tsx`, no estilo do arquivo (classes Tailwind com as mesmas cores `#f0ede8`/`#dedbd6`/`#7b7b78`).
- [ ] **Step 4:** `npx vitest run src/components/sidebar.test.tsx`. Esperado: PASS.
- [ ] **Step 5:** não commitar.

---

### Task 3: ContactDetail avisa abrir/fechar de qualquer painel

**Files:**
- Modify: `src/components/conversas/contact-detail.tsx`
- Test: `src/components/conversas/contact-detail.acoplado.test.tsx` (acrescentar casos)

Nova prop, ao lado de `onPainelAcopladoChange`:
```ts
/** Avisa a página quando um painel de venda/orçamento abre/fecha, acoplado ou não (ela recolhe o menu). */
onPainelAbertoChange?: (aberto: boolean) => void;
```

Efeito, logo após o efeito de `acoplado`:
```ts
useEffect(() => {
  if (!painelAberto || !onPainelAbertoChange) return;
  onPainelAbertoChange(true);
  return () => onPainelAbertoChange(false);
}, [painelAberto, onPainelAbertoChange]);
```

- [ ] **Step 1: Testes que falham.** Acrescentar ao `contact-detail.acoplado.test.tsx` um `describe("onPainelAbertoChange")`. Reaproveitar os mocks e o helper de render/conversa que o arquivo já usa (ler o arquivo inteiro antes). Casos:
  1. `painelAcoplado={false}`: clicar "abrir orçamento" chama `onPainelAbertoChange(true)`; fechar o painel (botão de fechar do `PainelLateral`, ver como o arquivo já fecha) chama `onPainelAbertoChange(false)`.
  2. `painelAcoplado={true}`: abrir "abrir venda" chama `(true)`.
  3. Trocar de conversa (rerender com outro `conversation.id`) com o painel aberto chama `(false)`.
- [ ] **Step 2:** `npx vitest run src/components/conversas/contact-detail.acoplado.test.tsx`. Esperado: FAIL nos novos.
- [ ] **Step 3:** implementar a prop e o efeito.
- [ ] **Step 4:** rodar de novo. Esperado: todos PASS, incluindo os antigos.
- [ ] **Step 5:** não commitar.

---

### Task 4: Ligar tudo (shell + /conversas)

Depende das Tasks 1–3.

**Files:**
- Modify: `src/components/authenticated-shell.tsx`
- Modify: `src/app/(authenticated)/conversas/page.tsx`

**Shell:**
- Envolver o conteúdo de `PresenceProvider` com `<MenuLateralProvider>`.
- Extrair o sidebar de desktop para um componente interno, para poder usar o hook dentro do provider:

```tsx
function SidebarDesktop() {
  const { recolhido, alternar } = useMenuLateral();
  return <Sidebar recolhido={recolhido} onAlternar={alternar} />;
}
```

- Trocar `<Sidebar />` do bloco `hidden md:flex` por `<SidebarDesktop />`. O drawer mobile segue `<Sidebar onClose=... />`.

**Página /conversas:**
- `QUERY_PAINEL_ACOPLADO = "(min-width: 1100px)"`. Atualizar o comentário: menu recolhido 56 + painel 672 + chat ~360 ≈ 1090. Ao abrir o painel o menu recolhe sozinho (cartão a22d0f72), e o modo é fixado na abertura pelo `ContactDetail`.
- `const { recolherPeloPainel, restaurarDoPainel } = useMenuLateral();`
- Criar o callback:

```ts
const handlePainelAbertoChange = useCallback(
  (aberto: boolean) => (aberto ? recolherPeloPainel() : restaurarDoPainel()),
  [recolherPeloPainel, restaurarDoPainel],
);
```

- Passar `onPainelAbertoChange={handlePainelAbertoChange}` **só** ao `ContactDetail` do bloco desktop (`hidden md:flex`), não ao do mobile, porque no mobile não há menu fixo.
- Ao sair da página com o painel aberto, o cleanup do efeito do `ContactDetail` chama `(false)`, e o menu volta.

- [ ] **Step 1:** implementar.
- [ ] **Step 2:** `npm test` (suíte inteira). Esperado: tudo PASS.
- [ ] **Step 3:** `npm run lint` e `npx tsc --noEmit`. Esperado: sem erros novos.
- [ ] **Step 4:** `npm run build`. Esperado: build ok.
- [ ] **Step 5:** commit.

---

### Task 5: Teste visual em modo teste

- [ ] `next dev` no worktree (copiar `frontend/.env.local` do checkout principal se faltar, sem imprimir).
- [ ] Prints com `print-frontend.mjs`, no viewport padrão do script ou ajustando a janela, se o script permitir:
  - /conversas com o menu aberto;
  - /conversas com uma conversa e "Novo orçamento" aberto, mostrando menu recolhido e painel ao lado do chat;
  - /dashboard com o menu recolhido.
- [ ] Conferir cada PNG olhando a imagem.
- [ ] Não salvar orçamento nem venda.
