# Link /conversas?lead_id= que abre a conversa: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** o link `/conversas?lead_id=<id>` abre a conversa do lead no PC e no celular, troca de conversa quando já se está em /conversas e, quando o lead não tem conversa, avisa na tela. No /trafego o botão "Abrir conversa" já aparece desabilitado para esse lead.

**Architecture:** a lógica do deep-link sai do `page.tsx` para um hook testável (`use-deep-link-lead.ts`) que guarda o último `lead_id` aplicado em vez de um booleano. A página liga o hook a `setSelectedId` + `setMobileView("chat")` e mostra um aviso (`LeadSemConversaAviso`) quando o lead não tem conversa. A rota `/api/leads/[id]/overview` ganha `has_conversation`, calculado por um helper testável, e o painel do /trafego desabilita o botão com texto visível.

**Tech Stack:** Next.js (App Router), React 19, TanStack Query, Supabase JS, Vitest + Testing Library (jsdom).

Spec: `docs/superpowers/specs/2026-10-30-deep-link-conversa-lead-design.md`.

Comandos rodam em `frontend/` do worktree `C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA\.claude\worktrees\agente-70d844a6`.

## Arquivos

| Arquivo | Papel |
|---|---|
| Create `frontend/src/app/(authenticated)/conversas/use-deep-link-lead.ts` | Hook do deep-link: acha a conversa na lista ou busca na API; avisa "sem conversa" |
| Create `frontend/src/app/(authenticated)/conversas/use-deep-link-lead.test.tsx` | Testes do hook |
| Create `frontend/src/components/conversas/lead-sem-conversa-aviso.tsx` | Aviso "Este lead não tem conversa no WhatsApp." + link da ficha |
| Modify `frontend/src/app/(authenticated)/conversas/page.tsx` | Troca o `useEffect` do deep-link pelo hook; mostra o aviso |
| Create `frontend/src/app/(authenticated)/conversas/page.deeplink.test.tsx` | Testes de orquestração: celular abre o chat; aviso aparece |
| Create `frontend/src/lib/lead-has-conversation.ts` + `.test.ts` | Helper: o lead tem conversa não bloqueada? |
| Modify `frontend/src/lib/lead-overview.ts` | Campo `has_conversation?: boolean \| null` |
| Modify `frontend/src/app/api/leads/[id]/overview/route.ts` | Preenche `has_conversation` |
| Modify `frontend/src/components/trafego/campaign-lead-panel.tsx` + `.test.tsx` | Botão desabilitado com "Sem conversa no WhatsApp" |

As Tarefas 1 e 2 são independentes (arquivos diferentes) e podem rodar em paralelo. A Tarefa 3 é a verificação final.

---

### Task 1: deep-link em /conversas (hook + aviso + página)

**Files:**
- Create: `frontend/src/app/(authenticated)/conversas/use-deep-link-lead.ts`
- Create: `frontend/src/app/(authenticated)/conversas/use-deep-link-lead.test.tsx`
- Create: `frontend/src/components/conversas/lead-sem-conversa-aviso.tsx`
- Create: `frontend/src/app/(authenticated)/conversas/page.deeplink.test.tsx`
- Modify: `frontend/src/app/(authenticated)/conversas/page.tsx` (efeito do deep-link, ~linhas 114-145; `handleSelectConversation`, `handleSelectMessageResult`, `handleChannelChange`; bloco mobile da lista; estado vazio do desktop)

- [ ] **Step 1: teste do hook (falha)**

`frontend/src/app/(authenticated)/conversas/use-deep-link-lead.test.tsx`:

```tsx
/**
 * @vitest-environment jsdom
 *
 * Cartão 70d844a6: o link /conversas?lead_id= precisa abrir a conversa do lead,
 * trocar de conversa quando chega um segundo link e avisar quando o lead não tem
 * conversa (em vez de ficar calado na lista).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor, cleanup } from "@testing-library/react";
import type { Conversation } from "@/lib/types";
import { useDeepLinkLead, type DeepLinkLeadOptions } from "./use-deep-link-lead";

const conv = (id: string, leadId: string) =>
  ({ id, lead_id: leadId, leads: { id: leadId, name: id } }) as unknown as Conversation;

function opcoes(over: Partial<DeepLinkLeadOptions> = {}): DeepLinkLeadOptions {
  return {
    leadId: null,
    ready: true,
    conversations: [],
    ensureInList: vi.fn(),
    onFound: vi.fn(),
    onNotFound: vi.fn(),
    clearUrl: vi.fn(),
    ...over,
  };
}

function apiResponde(conversations: Conversation[], ok = true) {
  const f = vi.fn(async () => ({ ok, status: ok ? 200 : 500, json: async () => ({ conversations, next_cursor: null }) }));
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("useDeepLinkLead", () => {
  it("lead na lista carregada: seleciona sem ir à API e limpa a URL", () => {
    const f = apiResponde([]);
    const o = opcoes({ leadId: "L1", conversations: [conv("c1", "L1")] });
    renderHook(() => useDeepLinkLead(o));
    expect(o.onFound).toHaveBeenCalledWith(expect.objectContaining({ id: "c1" }));
    expect(o.clearUrl).toHaveBeenCalled();
    expect(f).not.toHaveBeenCalled();
  });

  it("espera a lista carregar (ready=false não faz nada)", () => {
    const f = apiResponde([]);
    const o = opcoes({ leadId: "L1", ready: false });
    renderHook(() => useDeepLinkLead(o));
    expect(o.onFound).not.toHaveBeenCalled();
    expect(f).not.toHaveBeenCalled();
  });

  it("lead fora da lista: busca na API, injeta e seleciona", async () => {
    const f = apiResponde([conv("c9", "L9")]);
    const o = opcoes({ leadId: "L9" });
    const { result } = renderHook(() => useDeepLinkLead(o));
    await waitFor(() => expect(o.onFound).toHaveBeenCalledWith(expect.objectContaining({ id: "c9" })));
    expect(f).toHaveBeenCalledWith("/api/conversations?lead_id=L9");
    expect(o.ensureInList).toHaveBeenCalledWith(expect.objectContaining({ id: "c9" }));
    expect(o.clearUrl).toHaveBeenCalled();
    expect(result.current.leadSemConversa).toBeNull();
  });

  it("lead sem conversa: avisa com o id do lead e chama onNotFound", async () => {
    apiResponde([]);
    const o = opcoes({ leadId: "L0" });
    const { result } = renderHook(() => useDeepLinkLead(o));
    await waitFor(() => expect(result.current.leadSemConversa).toBe("L0"));
    expect(o.onNotFound).toHaveBeenCalled();
    expect(o.onFound).not.toHaveBeenCalled();
    expect(o.clearUrl).toHaveBeenCalled();
  });

  it("falha da API não afirma que o lead não tem conversa", async () => {
    apiResponde([], false);
    const o = opcoes({ leadId: "L0" });
    const { result } = renderHook(() => useDeepLinkLead(o));
    await waitFor(() => expect(o.clearUrl).toHaveBeenCalled());
    expect(result.current.leadSemConversa).toBeNull();
    expect(o.onNotFound).not.toHaveBeenCalled();
  });

  it("segundo link com outro lead na mesma montagem troca a seleção", () => {
    apiResponde([]);
    const lista = [conv("c1", "L1"), conv("c2", "L2")];
    const o = opcoes({ leadId: "L1", conversations: lista });
    const { rerender } = renderHook((p: DeepLinkLeadOptions) => useDeepLinkLead(p), { initialProps: o });
    rerender({ ...o, leadId: null }); // router.replace("/conversas") limpou a URL
    rerender({ ...o, leadId: "L2" }); // popup de SLA / notificação empurra outro lead
    expect(o.onFound).toHaveBeenNthCalledWith(1, expect.objectContaining({ id: "c1" }));
    expect(o.onFound).toHaveBeenNthCalledWith(2, expect.objectContaining({ id: "c2" }));
  });

  it("o mesmo link não é reaplicado a cada mudança da lista", () => {
    apiResponde([]);
    const o = opcoes({ leadId: "L1", conversations: [conv("c1", "L1")] });
    const { rerender } = renderHook((p: DeepLinkLeadOptions) => useDeepLinkLead(p), { initialProps: o });
    rerender({ ...o, conversations: [conv("c1", "L1"), conv("c3", "L3")] });
    expect(o.onFound).toHaveBeenCalledTimes(1);
  });

  it("dispensar apaga o aviso", async () => {
    apiResponde([]);
    const o = opcoes({ leadId: "L0" });
    const { result } = renderHook(() => useDeepLinkLead(o));
    await waitFor(() => expect(result.current.leadSemConversa).toBe("L0"));
    result.current.dispensar();
    await waitFor(() => expect(result.current.leadSemConversa).toBeNull());
  });
});
```

- [ ] **Step 2: rodar e ver falhar**

Run: `npx vitest run "src/app/(authenticated)/conversas/use-deep-link-lead.test.tsx"`
Expected: FAIL (módulo `./use-deep-link-lead` não existe).

- [ ] **Step 3: implementar o hook**

`frontend/src/app/(authenticated)/conversas/use-deep-link-lead.ts`:

```ts
"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  conversationsListUrl,
  type ConversationsPage,
} from "@/app/api/conversations/list-params";
import type { Conversation, Lead } from "@/lib/types";

export interface DeepLinkLeadOptions {
  /** `lead_id` da URL (null quando não há ou depois de limpar a URL). */
  leadId: string | null;
  /** A lista inicial já carregou (antes disso não dá para procurar nela). */
  ready: boolean;
  conversations: Conversation[];
  ensureInList: (conv: Conversation) => void;
  /** Conversa achada: a página seleciona e, no celular, abre o chat. */
  onFound: (conv: Conversation) => void;
  /** Lead sem conversa visível: a página desfaz a seleção anterior. */
  onNotFound: () => void;
  /** Tira o `lead_id` da URL (router.replace). */
  clearUrl: () => void;
}

/**
 * Deep-link `/conversas?lead_id=` (cartão 70d844a6).
 *
 * Guarda o último lead APLICADO em vez de um booleano "já aplicou": um segundo link
 * (popup de SLA, notificação) com a página montada também precisa abrir. A URL
 * limpa (leadId null) zera a marca, então o mesmo lead pode vir de novo depois.
 *
 * Lead sem conversa visível (nenhuma, só bloqueada ou de canal sem acesso) vira
 * `leadSemConversa` para a página avisar, em vez de deixar a lista calada. Falha
 * de rede NÃO vira aviso: não dá para afirmar que a conversa não existe.
 */
export function useDeepLinkLead({
  leadId,
  ready,
  conversations,
  ensureInList,
  onFound,
  onNotFound,
  clearUrl,
}: DeepLinkLeadOptions): { leadSemConversa: string | null; dispensar: () => void } {
  const aplicado = useRef<string | null>(null);
  const [leadSemConversa, setLeadSemConversa] = useState<string | null>(null);

  // Callbacks por ref: a página recria as funções a cada render, e o efeito não
  // pode rodar de novo por isso.
  const cb = useRef({ ensureInList, onFound, onNotFound, clearUrl });
  useLayoutEffect(() => {
    cb.current = { ensureInList, onFound, onNotFound, clearUrl };
  });

  useEffect(() => {
    if (!leadId) {
      aplicado.current = null;
      return;
    }
    if (!ready || aplicado.current === leadId) return;
    aplicado.current = leadId;

    const match = conversations.find((c) => (c.leads as Lead | undefined | null)?.id === leadId);
    if (match) {
      cb.current.onFound(match);
      cb.current.clearUrl();
      return;
    }

    // Lead fora da lista carregada (paginação): busca sob demanda.
    void (async () => {
      try {
        const res = await fetch(conversationsListUrl({ leadId }));
        if (!res.ok) return;
        const data = (await res.json()) as ConversationsPage<Conversation>;
        if (aplicado.current !== leadId) return; // chegou outro link no meio
        const conv = Array.isArray(data?.conversations) ? data.conversations[0] : null; // a rota ordena por last_msg_at desc
        if (!conv) {
          setLeadSemConversa(leadId);
          cb.current.onNotFound();
          return;
        }
        cb.current.ensureInList(conv);
        cb.current.onFound(conv);
      } catch {
        // falha de rede: lista continua utilizável, sem aviso de "sem conversa"
      } finally {
        cb.current.clearUrl();
      }
    })();
  }, [leadId, ready, conversations]);

  const dispensar = useCallback(() => setLeadSemConversa(null), []);
  return { leadSemConversa, dispensar };
}
```

Observação: se o `onFound` for chamado para um lead novo, a página esconde o aviso porque há conversa selecionada (o aviso só aparece sem seleção) e também chama `dispensar` (Step 6).

- [ ] **Step 4: rodar e ver passar**

Run: `npx vitest run "src/app/(authenticated)/conversas/use-deep-link-lead.test.tsx"`
Expected: 8 passed.

- [ ] **Step 5: componente do aviso**

`frontend/src/components/conversas/lead-sem-conversa-aviso.tsx`:

```tsx
import Link from "next/link";

/**
 * Aviso do deep-link /conversas?lead_id= quando o lead não tem conversa visível
 * (ex.: cliente importado do Bling que nunca falou no WhatsApp). Texto visível,
 * não tooltip: quem abre o link precisa saber na hora por que nada abriu.
 */
export function LeadSemConversaAviso({ leadId }: { leadId: string }) {
  return (
    <div
      role="status"
      data-testid="lead-sem-conversa"
      className="mx-3 my-2 rounded-[4px] border border-[#dedbd6] bg-white px-4 py-3 text-left"
    >
      <p className="text-[14px] font-medium text-[#111111]">Este lead não tem conversa no WhatsApp.</p>
      <Link
        href={`/leads?lead_id=${leadId}`}
        className="mt-1 inline-block text-[13px] text-[#111111] underline underline-offset-2"
      >
        Abrir ficha do lead
      </Link>
    </div>
  );
}
```

- [ ] **Step 6: teste de orquestração da página (falha)**

`frontend/src/app/(authenticated)/conversas/page.deeplink.test.tsx`:

```tsx
/**
 * @vitest-environment jsdom
 *
 * Cartão 70d844a6: no celular o link /conversas?lead_id= marcava a conversa na
 * lista mas não abria o chat; e lead sem conversa deixava a tela calada.
 * Lista, chat e detalhe são dublês: o que se testa é a orquestração da página.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import type { Conversation } from "@/lib/types";

const h = vi.hoisted(() => ({
  params: new URLSearchParams(),
  conversas: [] as unknown[],
  replace: vi.fn(),
}));

const conversa = {
  id: "conv-a",
  lead_id: "lead-a",
  leads: { id: "lead-a", name: "Vida Natural", phone: "5531999990000", ai_enabled: true },
  channels: { name: "NUMERO JOAO" },
} as unknown as Conversation;

vi.mock("next/navigation", () => ({
  useSearchParams: () => h.params,
  useRouter: () => ({ replace: h.replace }),
}));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({ select: () => ({ eq: async () => ({ data: [], error: null }) }) }),
  }),
}));
vi.mock("./use-conversation-list", () => ({
  useConversationList: () => {
    // Seleção real (useState) para a página derivar selectedConversation.
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const conversations = h.conversas as Conversation[];
    return {
      conversations,
      convPending: false,
      listError: null,
      isRefreshing: false,
      refetchConversations: vi.fn(),
      hasNextPage: false,
      isFetchingNextPage: false,
      loadMore: vi.fn(),
      counts: { total: conversations.length, unread: 0 },
      setSelectedId,
      selectedConversation: conversations.find((c) => c.id === selectedId) ?? null,
      patchList: vi.fn(),
      patchConversation: vi.fn(),
      ensureInList: vi.fn(),
      fetchConversationById: vi.fn(),
      noteMarkedRead: vi.fn(),
      setPendingAi: vi.fn(),
      setPendingFollowup: vi.fn(),
    };
  },
}));
vi.mock("@/components/conversas/chat-list", () => ({
  ChatList: () => <div data-testid="lista" />,
}));
vi.mock("@/components/conversas/chat-view", () => ({
  ChatView: () => <div data-testid="chat" />,
}));
vi.mock("@/components/conversas/contact-detail", () => ({
  ContactDetail: () => <div data-testid="detalhe" />,
}));

import ConversasPage from "./page";

/** Bloco do celular (md:hidden) que contém o elemento. */
const blocoCelular = (el: HTMLElement) => el.closest(".md\\:hidden") as HTMLElement | null;
const visivel = (el: HTMLElement) => !el.className.split(/\s+/).includes("hidden");

beforeEach(() => {
  h.params = new URLSearchParams();
  h.conversas = [];
  h.replace.mockClear();
  window.matchMedia = vi.fn(() => ({
    matches: false, media: "", onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("/conversas — deep-link ?lead_id=", () => {
  it("celular: o link abre o chat do lead, não só a lista", async () => {
    h.params = new URLSearchParams("lead_id=lead-a");
    h.conversas = [conversa];
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })));
    render(<ConversasPage />);

    const chats = await screen.findAllByTestId("chat");
    const chatCelular = chats.map(blocoCelular).find(Boolean) as HTMLElement;
    expect(visivel(chatCelular)).toBe(true);
    const listaCelular = screen.getAllByTestId("lista").map(blocoCelular).find(Boolean) as HTMLElement;
    expect(visivel(listaCelular)).toBe(false);
    expect(h.replace).toHaveBeenCalledWith("/conversas");
  });

  it("lead sem conversa: aviso com link para a ficha, no PC e no celular", async () => {
    h.params = new URLSearchParams("lead_id=lead-sem");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => (String(url).includes("lead_id=lead-sem") ? { conversations: [], next_cursor: null } : []),
    })));
    render(<ConversasPage />);

    const avisos = await screen.findAllByTestId("lead-sem-conversa");
    expect(avisos).toHaveLength(2); // bloco do celular + estado vazio do PC
    expect(avisos[0].textContent).toContain("Este lead não tem conversa no WhatsApp.");
    const links = screen.getAllByRole("link", { name: "Abrir ficha do lead" });
    expect(links[0].getAttribute("href")).toBe("/leads?lead_id=lead-sem");
    expect(screen.queryByText("Selecione uma conversa")).toBeNull();
  });

  it("sem lead_id: estado vazio normal, sem aviso", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })));
    render(<ConversasPage />);
    await waitFor(() => expect(screen.getByText("Selecione uma conversa")).toBeTruthy());
    expect(screen.queryByTestId("lead-sem-conversa")).toBeNull();
  });
});
```

Run: `npx vitest run "src/app/(authenticated)/conversas/page.deeplink.test.tsx"`
Expected: FAIL (1º: chat do celular escondido; 2º: aviso não existe).

- [ ] **Step 7: ligar o hook na página**

Em `frontend/src/app/(authenticated)/conversas/page.tsx`:

1. Imports: remover `conversationsListUrl` / `ConversationsPage` (só eram usados no efeito) e `useRef` se não sobrar uso; adicionar:

```ts
import { LeadSemConversaAviso } from "@/components/conversas/lead-sem-conversa-aviso";
import { useDeepLinkLead } from "./use-deep-link-lead";
```

2. Apagar `const deepLinkApplied = useRef(false);` e o `useEffect` inteiro de "Deep-link: pre-select conversation by lead_id from URL param". No lugar:

```ts
  // Deep-link /conversas?lead_id= (cartão 70d844a6): abre a conversa do lead, no
  // celular inclusive, e avisa quando o lead não tem conversa.
  const { leadSemConversa, dispensar: dispensarAvisoSemConversa } = useDeepLinkLead({
    leadId: searchParams.get("lead_id"),
    ready: !convPending,
    conversations,
    ensureInList,
    onFound: (conv) => {
      setSelectedId(conv.id);
      setPendingScrollMessageId(null);
      setMobileView("chat");
    },
    onNotFound: () => {
      setSelectedId(null);
      setMobileView("list");
    },
    clearUrl: () => router.replace("/conversas"),
  });
  const avisoSemConversa = leadSemConversa && !selectedConversation ? leadSemConversa : null;
```

3. Chamar `dispensarAvisoSemConversa();` na primeira linha de `handleSelectConversation`, de `handleSelectMessageResult` e de `handleChannelChange`.

4. Bloco mobile da lista (`<div className={`md:hidden ... ${mobileView === "list" ? "flex" : "hidden"}`}>`): logo antes do `<ChatList`:

```tsx
        {avisoSemConversa && <LeadSemConversaAviso leadId={avisoSemConversa} />}
```

5. Estado vazio do desktop: trocar o conteúdo de `<div className="flex-1 flex items-center justify-center bg-[#faf9f6]">` por:

```tsx
          <div className="flex-1 flex items-center justify-center bg-[#faf9f6]">
            {avisoSemConversa ? (
              <div className="w-full max-w-sm">
                <LeadSemConversaAviso leadId={avisoSemConversa} />
              </div>
            ) : (
              <div className="text-center">
                {/* svg + "Selecione uma conversa" + contador: exatamente como estavam */}
              </div>
            )}
          </div>
```

(manter o `<svg>`, o "Selecione uma conversa" e o contador `openTotal` sem mudança dentro do ramo `else`.)

- [ ] **Step 8: rodar os testes da página**

Run: `npx vitest run "src/app/(authenticated)/conversas/"`
Expected: todos passam (os novos e os antigos de `page.test.tsx`).

- [ ] **Step 9: lint e tipos dos arquivos tocados**

Run: `npx eslint "src/app/(authenticated)/conversas/page.tsx" "src/app/(authenticated)/conversas/use-deep-link-lead.ts" "src/app/(authenticated)/conversas/use-deep-link-lead.test.tsx" "src/app/(authenticated)/conversas/page.deeplink.test.tsx" src/components/conversas/lead-sem-conversa-aviso.tsx && npx tsc --noEmit -p .`
Expected: sem erro novo nesses arquivos. Se a regra `react-hooks/set-state-in-effect` acusar algo, mover o `setState` para dentro do callback assíncrono (já está) e não usar `eslint-disable`.

- [ ] **Step 10: commit**

```bash
git add "frontend/src/app/(authenticated)/conversas/use-deep-link-lead.ts" "frontend/src/app/(authenticated)/conversas/use-deep-link-lead.test.tsx" "frontend/src/app/(authenticated)/conversas/page.deeplink.test.tsx" "frontend/src/app/(authenticated)/conversas/page.tsx" frontend/src/components/conversas/lead-sem-conversa-aviso.tsx
git commit -m "fix(conversas): link ?lead_id= abre o chat no celular, troca de conversa e avisa lead sem conversa"
```

---

### Task 2: /trafego, botão "Abrir conversa" desabilitado para lead sem conversa

**Files:**
- Create: `frontend/src/lib/lead-has-conversation.ts`
- Create: `frontend/src/lib/lead-has-conversation.test.ts`
- Modify: `frontend/src/lib/lead-overview.ts` (interface `LeadOverview`, ~linha 123)
- Modify: `frontend/src/app/api/leads/[id]/overview/route.ts` (perto do `repassePromise` e do `payload`)
- Modify: `frontend/src/components/trafego/campaign-lead-panel.tsx` (~linhas 404-418, botão "Abrir conversa")
- Modify: `frontend/src/components/trafego/campaign-lead-panel.test.tsx`

- [ ] **Step 1: teste do helper (falha)**

`frontend/src/lib/lead-has-conversation.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";
import { leadTemConversa } from "./lead-has-conversation";

/** Dublê do encadeamento from().select().eq().neq() que grava os filtros. */
function fakeSb(resultado: { count: number | null; error: { message: string } | null } | Error) {
  const filtros: string[] = [];
  const q = {
    select: vi.fn(() => q),
    eq: vi.fn((c: string, v: string) => { filtros.push(`eq ${c}=${v}`); return q; }),
    neq: vi.fn(async (c: string, v: string) => {
      filtros.push(`neq ${c}=${v}`);
      if (resultado instanceof Error) throw resultado;
      return resultado;
    }),
  };
  const sb = { from: vi.fn(() => q) } as unknown as SupabaseClient;
  return { sb, filtros, q };
}

describe("leadTemConversa", () => {
  it("conta conversas do lead que não estão bloqueadas", async () => {
    const { sb, filtros, q } = fakeSb({ count: 2, error: null });
    expect(await leadTemConversa(sb, "L1")).toBe(true);
    expect(sb.from).toHaveBeenCalledWith("conversations");
    expect(q.select).toHaveBeenCalledWith("id", { count: "exact", head: true });
    expect(filtros).toEqual(["eq lead_id=L1", "neq status=blocked"]);
  });

  it("zero conversas → false", async () => {
    expect(await leadTemConversa(fakeSb({ count: 0, error: null }).sb, "L1")).toBe(false);
  });

  it("erro da consulta → null (desconhecido, o botão fica habilitado)", async () => {
    expect(await leadTemConversa(fakeSb({ count: null, error: { message: "x" } }).sb, "L1")).toBeNull();
    expect(await leadTemConversa(fakeSb(new Error("rede")).sb, "L1")).toBeNull();
  });
});
```

Run: `npx vitest run src/lib/lead-has-conversation.test.ts` → Expected: FAIL (módulo não existe).

- [ ] **Step 2: implementar o helper**

`frontend/src/lib/lead-has-conversation.ts`:

```ts
import type { SupabaseClient } from "@supabase/supabase-js";

/**
 * O lead tem conversa que o /conversas consegue abrir? Mesma regra da listagem
 * (`/api/conversations`): conversa bloqueada não aparece. Usado pelo painel do
 * /trafego para desabilitar "Abrir conversa" (cartão 70d844a6). A rota do painel é
 * admin-only, e admin vê todos os canais, então não há filtro de canal aqui.
 *
 * null = não deu para saber (erro): quem chama trata como "pode ter".
 */
export async function leadTemConversa(sb: SupabaseClient, leadId: string): Promise<boolean | null> {
  try {
    const { count, error } = await sb
      .from("conversations")
      .select("id", { count: "exact", head: true })
      .eq("lead_id", leadId)
      .neq("status", "blocked");
    if (error) return null;
    return (count ?? 0) > 0;
  } catch {
    return null;
  }
}
```

Run: `npx vitest run src/lib/lead-has-conversation.test.ts` → Expected: 3 passed.

Se `getServiceSupabase()` não devolver um tipo atribuível a `SupabaseClient`, tipar o parâmetro com `Awaited<ReturnType<typeof getServiceSupabase>>` (importado de `@/lib/supabase/api`) e manter o cast no teste.

- [ ] **Step 3: tipo do payload**

Em `frontend/src/lib/lead-overview.ts`, dentro de `interface LeadOverview`, depois de `repasse?`:

```ts
  /**
   * Existe conversa não bloqueada deste lead (cartão 70d844a6)? false desabilita
   * "Abrir conversa" no painel; null/ausente = desconhecido, botão habilitado.
   */
  has_conversation?: boolean | null;
```

- [ ] **Step 4: rota preenche o campo**

Em `frontend/src/app/api/leads/[id]/overview/route.ts`:

```ts
import { leadTemConversa } from "@/lib/lead-has-conversation";
```

Logo depois do bloco do `repassePromise`:

```ts
  // Painel desabilita "Abrir conversa" quando o lead não tem conversa (cartão 70d844a6).
  const hasConversationPromise = leadTemConversa(sb, id);
```

Depois de `const repasse = await repassePromise;`:

```ts
  const has_conversation = await hasConversationPromise;
```

E no objeto `payload`, depois de `repasse,`: `has_conversation,`.

- [ ] **Step 5: teste do painel (falha)**

Em `frontend/src/components/trafego/campaign-lead-panel.test.tsx`, trocar `mockFetch` para aceitar o payload e adicionar um `describe` no fim:

```tsx
function mockFetch(payload: LeadOverview = PAYLOAD) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = url === "/api/leads/L1/overview" ? payload : { campanhas: [] };
    return { ok: true, status: 200, json: async () => body };
  }));
}
```

```tsx
// Cartão 70d844a6: lead sem conversa (ex.: importado do Bling) não pode levar a um
// /conversas calado. O botão fica à vista, desabilitado, com o motivo escrito.
describe("CampaignLeadPanel — botão de conversa", () => {
  it("lead sem conversa: botão desabilitado com 'Sem conversa no WhatsApp'", async () => {
    mockFetch({ ...PAYLOAD, has_conversation: false });
    render(<CampaignLeadPanel target={TARGET} onClose={() => {}} />);
    const botao = await screen.findByRole("button", { name: /Sem conversa no WhatsApp/ });
    expect((botao as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: /Abrir conversa/ })).toBeNull();
  });

  it("lead com conversa: 'Abrir conversa' habilitado", async () => {
    mockFetch({ ...PAYLOAD, has_conversation: true });
    render(<CampaignLeadPanel target={TARGET} onClose={() => {}} />);
    await screen.findByText("Vendas");
    const botao = screen.getByRole("button", { name: /Abrir conversa/ });
    expect((botao as HTMLButtonElement).disabled).toBe(false);
  });

  it("sem a informação (payload antigo ou erro): continua habilitado", async () => {
    mockFetch(PAYLOAD);
    render(<CampaignLeadPanel target={TARGET} onClose={() => {}} />);
    await screen.findByText("Vendas");
    expect((screen.getByRole("button", { name: /Abrir conversa/ }) as HTMLButtonElement).disabled).toBe(false);
  });
});
```

Run: `npx vitest run src/components/trafego/campaign-lead-panel.test.tsx` → Expected: o 1º teste novo FALHA.

- [ ] **Step 6: botão no painel**

Em `frontend/src/components/trafego/campaign-lead-panel.tsx`, perto de `const nome = ...`:

```ts
  // false = o lead não tem conversa no /conversas (cartão 70d844a6). Carregando ou
  // desconhecido mantém o botão habilitado: o /conversas avisa nesse caso.
  const semConversa = data?.has_conversation === false;
```

Trocar o botão "Abrir conversa" por:

```tsx
            <button
              type="button"
              disabled={semConversa}
              onClick={() => leadId && !semConversa && go(`/conversas?lead_id=${leadId}`)}
              className={
                "flex-1 inline-flex items-center justify-center gap-2 text-[14px] py-2.5 rounded-[4px] transition-all " +
                (semConversa
                  ? "bg-[#f0eee9] text-[#7b7b78] cursor-not-allowed"
                  : "bg-[#111111] text-white hover:bg-[#000000] active:scale-[0.98]")
              }
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                />
              </svg>
              {semConversa ? "Sem conversa no WhatsApp" : "Abrir conversa"}
            </button>
```

Run: `npx vitest run src/components/trafego/campaign-lead-panel.test.tsx src/lib/lead-has-conversation.test.ts` → Expected: todos passam.

- [ ] **Step 7: lint e tipos**

Run: `npx eslint src/lib/lead-has-conversation.ts src/lib/lead-has-conversation.test.ts src/lib/lead-overview.ts "src/app/api/leads/[id]/overview/route.ts" src/components/trafego/campaign-lead-panel.tsx src/components/trafego/campaign-lead-panel.test.tsx && npx tsc --noEmit -p .`
Expected: sem erro novo nesses arquivos.

- [ ] **Step 8: commit**

```bash
git add frontend/src/lib/lead-has-conversation.ts frontend/src/lib/lead-has-conversation.test.ts frontend/src/lib/lead-overview.ts "frontend/src/app/api/leads/[id]/overview/route.ts" frontend/src/components/trafego/campaign-lead-panel.tsx frontend/src/components/trafego/campaign-lead-panel.test.tsx
git commit -m "feat(trafego): botao de conversa desabilitado quando o lead nao tem conversa"
```

---

### Task 3: verificação final (modo teste)

- [ ] **Step 1:** `npx vitest run` em `frontend/` → suíte inteira verde (comparar com `origin/master` se houver falha que já existia).
- [ ] **Step 2:** `npx tsc --noEmit -p .` e `npm run build` → sem erro.
- [ ] **Step 3:** CRM local (`npx next dev -p 3100`) com `frontend/.env.local` copiado do `.env.build` do CRM na VPS (nunca impresso, fora do git). Prints em 1440 px e 390 px:
  - `/conversas?lead_id=1a80f7a4-9150-4bee-adcf-dae488ac1e7e` (com conversa) → chat aberto também no celular;
  - `/conversas?lead_id=0376d44a-2b05-465c-ab78-e17d5cdbf98f` (Micheli, sem conversa) → aviso;
  - painel do lead sem conversa no /trafego → botão desabilitado.
- [ ] **Step 4:** rodar o teste em massa (`massa.mjs` / `clique.mjs`) contra o local com a mesma amostra.
