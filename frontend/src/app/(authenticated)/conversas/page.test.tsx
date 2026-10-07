/**
 * @vitest-environment jsdom
 *
 * "Painel ao lado do chat" (decisão do dono, 07/10): em /conversas, com o
 * painel de venda/orçamento aberto numa tela larga, a lista de conversas
 * recolhe e o painel vira coluna do layout ao lado do chat. Ao fechar, a
 * lista volta. Abaixo do ponto de corte o painel segue sobreposto.
 *
 * Lista, chat e detalhe são dublês: o que se testa aqui é a orquestração da
 * página (o painel inline em si está em contact-detail.acoplado.test.tsx).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Conversation } from "@/lib/types";

const h = vi.hoisted(() => ({
  telaLarga: true,
  ouvintes: new Set<() => void>(),
}));

const conversa = {
  id: "conv-a",
  lead_id: "lead-a",
  leads: { id: "lead-a", name: "Vida Natural", phone: "5531999990000", ai_enabled: true },
  channels: { name: "NUMERO JOAO" },
} as unknown as Conversation;

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({ select: () => ({ eq: async () => ({ data: [], error: null }) }) }),
  }),
}));
vi.mock("./use-conversation-list", () => ({
  useConversationList: () => ({
    conversations: [conversa],
    convPending: false,
    listError: null,
    isRefreshing: false,
    refetchConversations: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
    loadMore: vi.fn(),
    counts: { total: 1, unread: 0 },
    setSelectedId: vi.fn(),
    selectedConversation: conversa,
    patchList: vi.fn(),
    patchConversation: vi.fn(),
    ensureInList: vi.fn(),
    fetchConversationById: vi.fn(),
    noteMarkedRead: vi.fn(),
    setPendingAi: vi.fn(),
    setPendingFollowup: vi.fn(),
  }),
}));
vi.mock("@/components/conversas/chat-list", () => ({
  ChatList: () => <div data-testid="lista" />,
}));
vi.mock("@/components/conversas/chat-view", () => ({
  ChatView: () => <div data-testid="chat" />,
}));
vi.mock("@/components/conversas/contact-detail", () => ({
  ContactDetail: (p: {
    onBack?: () => void;
    painelAcoplado?: boolean;
    onPainelAcopladoChange?: (aberto: boolean) => void;
  }) =>
    p.onBack ? (
      <div data-testid="detalhe-mobile" data-props={JSON.stringify(Object.keys(p))} />
    ) : (
      <div data-testid="detalhe" data-acoplado={String(p.painelAcoplado)}>
        <button type="button" onClick={() => p.onPainelAcopladoChange?.(true)}>abre painel</button>
        <button type="button" onClick={() => p.onPainelAcopladoChange?.(false)}>fecha painel</button>
      </div>
    ),
}));

import ConversasPage from "./page";

function mockMatchMedia() {
  window.matchMedia = vi.fn((query: string) => ({
    get matches() {
      return query === "(min-width: 1280px)" ? h.telaLarga : false;
    },
    media: query,
    onchange: null,
    addEventListener: (_: string, cb: () => void) => h.ouvintes.add(cb),
    removeEventListener: (_: string, cb: () => void) => h.ouvintes.delete(cb),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

/** A instância desktop da lista (a outra fica no bloco `md:hidden` do celular). */
function listaDesktop(): HTMLElement {
  const listas = screen.getAllByTestId("lista");
  const desktop = listas.filter((el) => !el.closest(".md\\:hidden"));
  expect(desktop).toHaveLength(1);
  return desktop[0];
}
const recolhida = (el: HTMLElement) =>
  (el.closest("[data-slot='coluna-lista']") as HTMLElement).className.split(/\s+/).includes("hidden");

beforeEach(() => {
  h.telaLarga = true;
  h.ouvintes.clear();
  mockMatchMedia();
  global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => [] }) as Response) as unknown as typeof fetch;
});
afterEach(cleanup);

describe("/conversas — painel de venda/orçamento ao lado do chat", () => {
  it("tela larga: abrir o painel recolhe a lista; fechar devolve", async () => {
    render(<ConversasPage />);
    const detalhe = await screen.findByTestId("detalhe");
    expect(detalhe.dataset.acoplado).toBe("true");
    expect(recolhida(listaDesktop())).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "abre painel" }));
    expect(recolhida(listaDesktop())).toBe(true);
    // O chat continua no layout.
    expect(screen.getAllByTestId("chat").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "fecha painel" }));
    expect(recolhida(listaDesktop())).toBe(false);
  });

  it("tela estreita (abaixo de 1280 px): painel não acopla e a lista fica", async () => {
    h.telaLarga = false;
    render(<ConversasPage />);
    const detalhe = await screen.findByTestId("detalhe");
    expect(detalhe.dataset.acoplado).toBe("false");
    expect(recolhida(listaDesktop())).toBe(false);
  });

  it("acompanha a largura da janela (matchMedia change)", async () => {
    h.telaLarga = false;
    render(<ConversasPage />);
    expect((await screen.findByTestId("detalhe")).dataset.acoplado).toBe("false");
    h.telaLarga = true;
    act(() => h.ouvintes.forEach((cb) => cb()));
    expect(screen.getByTestId("detalhe").dataset.acoplado).toBe("true");
  });

  it("o detalhe do celular não recebe o modo acoplado", async () => {
    render(<ConversasPage />);
    const mobile = await screen.findByTestId("detalhe-mobile");
    const props = JSON.parse(mobile.dataset.props ?? "[]") as string[];
    expect(props).not.toContain("painelAcoplado");
    expect(props).not.toContain("onPainelAcopladoChange");
  });
});
