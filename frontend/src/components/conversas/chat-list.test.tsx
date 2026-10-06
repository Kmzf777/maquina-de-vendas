/**
 * @vitest-environment jsdom
 *
 * P5 — a lista de conversas deixou de ser a base inteira (cortada em 1.000 linhas pelo
 * PostgREST) e passou a ser paginada: o fim da lista pede a próxima página e o badge de
 * "Não lidas" vem do servidor, não da contagem do que está carregado.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent, screen, act } from "@testing-library/react";
import type { Conversation } from "@/lib/types";
import { ChatList } from "./chat-list";

let ioCallback: ((entries: { isIntersecting: boolean }[]) => void) | null = null;

class FakeIntersectionObserver {
  constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
    ioCallback = cb;
  }
  observe() {}
  disconnect() {}
  unobserve() {}
}

function conv(id: string, unread = 0): Conversation {
  return {
    id,
    lead_id: `l-${id}`,
    channel_id: "c1",
    stage: "secretaria",
    status: "active",
    last_msg_at: "2026-10-06T12:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    agent_profile_id: null,
    last_message_text: null,
    unread_count: unread,
    last_customer_message_at: null,
    whatsapp_window_expires_at: null,
    followup_enabled: true,
    first_seller_response_at: null,
    last_seller_response_at: null,
    leads: { id: `l-${id}`, name: `Lead ${id}`, phone: "5534999990000", stage: "atacado" } as never,
  } as Conversation;
}

type Props = Parameters<typeof ChatList>[0];

function renderList(over: Partial<Props> = {}) {
  const props: Props = {
    conversations: [conv("a", 1), conv("b")],
    channels: [],
    activeTab: "todos",
    selectedConversationId: null,
    selectedChannelId: "",
    onSelectConversation: vi.fn(),
    onTabChange: vi.fn(),
    onChannelChange: vi.fn(),
    ...over,
  };
  return { ...render(<ChatList {...props} />), props };
}

beforeEach(() => {
  ioCallback = null;
  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve([]) }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ChatList — contador de não lidas", () => {
  it("shows the server-side total instead of counting the loaded page", () => {
    renderList({ unreadTotal: 37 });
    expect(screen.getByLabelText("37 conversas não lidas").textContent).toBe("9+");
  });

  it("falls back to the loaded page when there is no server total", () => {
    renderList();
    expect(screen.getByLabelText("1 conversas não lidas")).toBeTruthy();
  });
});

describe("ChatList — rolagem infinita", () => {
  it("loads the next page when the end of the list becomes visible", () => {
    const onLoadMore = vi.fn();
    renderList({ hasMore: true, onLoadMore });
    act(() => ioCallback?.([{ isIntersecting: true }]));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it("does not ask again while a page is loading", () => {
    const onLoadMore = vi.fn();
    renderList({ hasMore: true, loadingMore: true, onLoadMore });
    act(() => ioCallback?.([{ isIntersecting: true }]));
    expect(onLoadMore).not.toHaveBeenCalled();
    expect(screen.getByText("Carregando mais conversas...")).toBeTruthy();
  });

  it("offers a manual button as fallback", () => {
    const onLoadMore = vi.fn();
    renderList({ hasMore: true, onLoadMore });
    fireEvent.click(screen.getByText("Carregar mais conversas"));
    expect(onLoadMore).toHaveBeenCalled();
  });

  it("does not auto-load while the list is in error (only the manual button retries)", () => {
    const onLoadMore = vi.fn();
    renderList({ hasMore: true, listError: true, onLoadMore });
    act(() => ioCallback?.([{ isIntersecting: true }]));
    expect(onLoadMore).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Carregar mais conversas"));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it("has no sentinel when everything is loaded", () => {
    renderList({ hasMore: false, onLoadMore: vi.fn() });
    expect(screen.queryByText("Carregar mais conversas")).toBeNull();
  });

  it("does not claim 'nothing found' while more pages exist", () => {
    renderList({ conversations: [], hasMore: true, onLoadMore: vi.fn() });
    expect(screen.queryByText("Nenhuma conversa encontrada.")).toBeNull();
  });

  it("does not page while searching (search is server-side)", () => {
    const onLoadMore = vi.fn();
    renderList({ hasMore: true, onLoadMore });
    fireEvent.change(screen.getByPlaceholderText("Buscar conversa..."), { target: { value: "hiago" } });
    expect(screen.queryByText("Carregar mais conversas")).toBeNull();
    act(() => ioCallback?.([{ isIntersecting: true }]));
    expect(onLoadMore).not.toHaveBeenCalled();
  });
});

describe("ChatList — seleção", () => {
  it("still selects a conversation from the list", () => {
    const { props } = renderList();
    fireEvent.click(screen.getByText("Lead b"));
    expect(props.onSelectConversation).toHaveBeenCalledWith(expect.objectContaining({ id: "b" }));
  });
});
