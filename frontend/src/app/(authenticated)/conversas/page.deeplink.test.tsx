/**
 * @vitest-environment jsdom
 *
 * Cartão 70d844a6: no celular o link /conversas?lead_id= marcava a conversa na
 * lista mas não abria o chat; e lead sem conversa deixava a tela calada.
 * Lista, chat e detalhe são dublês: o que se testa é a orquestração da página.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import type { Conversation } from "@/lib/types";

const h = vi.hoisted(() => ({
  params: new URLSearchParams(),
  conversas: [] as unknown[],
  replace: vi.fn(),
  fetchConversationById: vi.fn(),
  ensureInList: vi.fn(),
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
      ensureInList: h.ensureInList,
      fetchConversationById: h.fetchConversationById,
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
vi.mock("@/components/conversas/iniciar-conversa-modal", () => ({
  IniciarConversaModal: (p: { leadId: string; onIniciada: (id: string) => void }) => (
    <button data-testid="modal-iniciar" onClick={() => p.onIniciada("conv-novo")}>
      modal {p.leadId}
    </button>
  ),
}));

/** GET /api/leads/<id>/iniciar-conversa que o aviso faz para saber o telefone. */
const rotaIniciar = (url: string, telefone: string | null) =>
  String(url).includes("/iniciar-conversa")
    ? { lead: { id: "lead-sem", name: "Micheli", phone: telefone ?? "bling-1", company: null }, telefone, canais: [] }
    : undefined;

import ConversasPage from "./page";

/** Bloco do celular (md:hidden) que contém o elemento. */
const blocoCelular = (el: HTMLElement) => el.closest(".md\\:hidden") as HTMLElement | null;
const visivel = (el: HTMLElement) => !el.className.split(/\s+/).includes("hidden");

beforeEach(() => {
  h.params = new URLSearchParams();
  h.conversas = [];
  h.replace.mockClear();
  h.fetchConversationById.mockReset();
  h.ensureInList.mockReset();
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
      json: async () =>
        rotaIniciar(url, "5534988861441") ??
        (String(url).includes("lead_id=lead-sem") ? { conversations: [], next_cursor: null } : []),
    })));
    render(<ConversasPage />);

    const avisos = await screen.findAllByTestId("lead-sem-conversa");
    expect(avisos).toHaveLength(2); // bloco do celular + estado vazio do PC
    expect(avisos[0].textContent).toContain("Este lead não tem conversa no WhatsApp.");
    const links = screen.getAllByRole("link", { name: "Abrir ficha do lead" });
    expect(links[0].getAttribute("href")).toBe("/leads?lead_id=lead-sem");
    expect(screen.queryByText("Selecione uma conversa")).toBeNull();
  });

  it("lead sem conversa com telefone: Iniciar conversa abre o modal e, ao dar certo, o chat do celular", async () => {
    h.params = new URLSearchParams("lead_id=lead-sem");
    const nova = { ...conversa, id: "conv-novo", lead_id: "lead-sem", leads: { id: "lead-sem", name: "Micheli", phone: "5534988861441" } } as unknown as Conversation;
    h.fetchConversationById.mockResolvedValue(nova);
    h.ensureInList.mockImplementation((c: Conversation) => { h.conversas = [c]; });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () =>
        rotaIniciar(url, "5534988861441") ??
        (String(url).includes("lead_id=lead-sem") ? { conversations: [], next_cursor: null } : []),
    })));
    render(<ConversasPage />);

    const botoes = await screen.findAllByRole("button", { name: "Iniciar conversa" });
    expect(botoes).toHaveLength(2); // celular + PC
    expect(screen.queryByTestId("modal-iniciar")).toBeNull();
    fireEvent.click(botoes[0]);
    const modal = await screen.findByTestId("modal-iniciar");
    expect(modal.textContent).toContain("lead-sem");
    fireEvent.click(modal);

    await waitFor(() => expect(h.fetchConversationById).toHaveBeenCalledWith("conv-novo"));
    expect(h.ensureInList).toHaveBeenCalledWith(nova);
    const chats = await screen.findAllByTestId("chat");
    const chatCelular = chats.map(blocoCelular).find(Boolean) as HTMLElement;
    expect(visivel(chatCelular)).toBe(true);
    expect(screen.queryByTestId("modal-iniciar")).toBeNull();
    expect(screen.queryByTestId("lead-sem-conversa")).toBeNull();
  });

  it("sem lead_id: estado vazio normal, sem aviso", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })));
    render(<ConversasPage />);
    await waitFor(() => expect(screen.getByText("Selecione uma conversa")).toBeTruthy());
    expect(screen.queryByTestId("lead-sem-conversa")).toBeNull();
  });
});
