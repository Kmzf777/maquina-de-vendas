/**
 * @vitest-environment jsdom
 *
 * Tempo real da lista de conversas (P5): QueryClient DE VERDADE (o mesmo da página),
 * `fetch` falso que pagina como a rota (keyset `last_msg_at desc, id desc`) e um canal
 * Realtime falso que entrega eventos quando o teste manda.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { Conversation } from "@/lib/types";
import { conversationMatchesTab } from "@/lib/contact-search";
import { decodeCursor, splitPage } from "@/app/api/conversations/list-params";
import { ChatList } from "@/components/conversas/chat-list";
import { createConversasQueryClient } from "./query-provider";
import { useConversationList } from "./use-conversation-list";

// ---------------------------------------------------------------------------
// Servidor falso
// ---------------------------------------------------------------------------

const PAGE_SIZE = 2;
/** Um pouco além do debounce de 3s do refetch integral. */
const REFETCH_WAIT = 3_100;

/** uuid legível: uid("a") → 00000000-0000-0000-0000-00000000000a */
function uid(tag: string): string {
  return `00000000-0000-0000-0000-${tag.padStart(12, "0")}`;
}

function conv(tag: string, hour: number | null, over: Partial<Conversation> = {}): Conversation {
  return {
    id: uid(tag),
    lead_id: `l-${tag}`,
    channel_id: "c1",
    stage: "secretaria",
    status: "active",
    last_msg_at: hour === null ? null : `2026-10-06T${String(hour).padStart(2, "0")}:00:00+00:00`,
    created_at: "2026-01-01T00:00:00Z",
    agent_profile_id: null,
    last_message_text: null,
    unread_count: 0,
    last_customer_message_at: null,
    whatsapp_window_expires_at: null,
    followup_enabled: true,
    first_seller_response_at: null,
    last_seller_response_at: null,
    leads: { id: `l-${tag}`, name: `Lead ${tag}`, phone: "5534999990000", stage: "atacado" } as never,
    ...over,
  } as Conversation;
}

/** Ordem da rota: last_msg_at desc nulls last, id desc. */
function compareRoute(a: Conversation, b: Conversation): number {
  if (a.last_msg_at !== b.last_msg_at) {
    if (!a.last_msg_at) return 1;
    if (!b.last_msg_at) return -1;
    return Date.parse(b.last_msg_at) - Date.parse(a.last_msg_at);
  }
  return a.id < b.id ? 1 : a.id > b.id ? -1 : 0;
}

type Json = unknown;
interface Held {
  url: string;
  release: () => void;
}

class FakeServer {
  db: Conversation[] = [];
  calls: string[] = [];
  /** Respostas com status forçado por predicado de URL. */
  failures: { match: (url: string) => boolean; status: number }[] = [];
  /** Requisições que ficam penduradas até o teste soltar. */
  holds: { match: (url: string) => boolean; once: boolean }[] = [];
  held: Held[] = [];

  fetch = vi.fn(async (input: string | URL, init?: { signal?: AbortSignal }) => {
    const url = String(input);
    this.calls.push(url);
    const holdIdx = this.holds.findIndex((h) => h.match(url));
    if (holdIdx >= 0) {
      const hold = this.holds[holdIdx];
      if (hold.once) this.holds.splice(holdIdx, 1);
      await new Promise<void>((resolve, reject) => {
        this.held.push({ url, release: resolve });
        init?.signal?.addEventListener("abort", () =>
          reject(Object.assign(new Error("aborted"), { name: "AbortError" })),
        );
      });
    }
    const failure = this.failures.find((f) => f.match(url));
    if (failure) return response(failure.status, { error: "boom" });
    return response(200, this.route(url));
  });

  private route(url: string): Json {
    const u = new URL(url, "http://localhost");
    if (u.pathname === "/api/conversations/counts") {
      return { total: this.db.length, unread: this.db.filter((c) => (c.unread_count ?? 0) > 0).length };
    }
    const byId = u.pathname.match(/^\/api\/conversations\/([^/]+)$/);
    if (byId) {
      const found = this.db.find((c) => c.id === byId[1]);
      return found ? structuredClone(found) : NOT_FOUND;
    }
    if (u.pathname === "/api/conversations") {
      const tab = u.searchParams.get("tab") ?? "todos";
      const cursor = decodeCursor(u.searchParams.get("cursor"));
      let rows = this.db.filter((c) => conversationMatchesTab(c, tab)).sort(compareRoute);
      if (cursor) {
        const boundary = { id: cursor.id, last_msg_at: cursor.t } as Conversation;
        rows = rows.filter((c) => compareRoute(c, boundary) > 0);
      }
      const { rows: page, next_cursor } = splitPage(rows, PAGE_SIZE);
      return { conversations: structuredClone(page), next_cursor };
    }
    return NOT_FOUND;
  }

  /** Quantas requisições casam com o predicado. */
  count(match: (url: string) => boolean): number {
    return this.calls.filter(match).length;
  }
}

const NOT_FOUND = Symbol("404");

function response(status: number, body: Json) {
  if (body === NOT_FOUND) status = 404;
  const ok = status >= 200 && status < 300;
  return { ok, status, json: async () => (body === NOT_FOUND ? { error: "not found" } : body) };
}

const isListUrl = (url: string) => url.startsWith("/api/conversations?") || url === "/api/conversations";
const isFirstPage = (url: string) => isListUrl(url) && !url.includes("cursor=");
const isNextPage = (url: string) => isListUrl(url) && url.includes("cursor=");
const isCounts = (url: string) => url.startsWith("/api/conversations/counts");

// ---------------------------------------------------------------------------
// Realtime falso
// ---------------------------------------------------------------------------

type Handler = (payload: Record<string, unknown>) => void;

function fakeSupabase() {
  const handlers: { table: string; event: string; cb: Handler }[] = [];
  const channel = {
    on(_type: string, filter: { event: string; table: string }, cb: Handler) {
      handlers.push({ table: filter.table, event: filter.event, cb });
      return channel;
    },
    subscribe(cb?: (status: string) => void) {
      cb?.("SUBSCRIBED");
      return channel;
    },
  };
  return {
    client: { channel: () => channel, removeChannel: vi.fn() } as never,
    emit(table: string, payload: Record<string, unknown>) {
      for (const h of handlers) {
        if (h.table === table && (h.event === "*" || h.event === payload.eventType)) h.cb(payload);
      }
    },
  };
}

// ---------------------------------------------------------------------------
// Montagem
// ---------------------------------------------------------------------------

let server: FakeServer;
let realtime: ReturnType<typeof fakeSupabase>;
let queryClient: QueryClient;

function setup(initialTab = "todos") {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(
    ({ tab }: { tab: string }) =>
      useConversationList({ supabase: realtime.client, channelId: "", activeTab: tab }),
    { wrapper, initialProps: { tab: initialTab } },
  );
}

/** Deixa promessas e timers do React Query andarem `ms` de relógio falso. */
async function tick(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

const ids = (list: Conversation[]) => list.map((c) => c.id);

function updateEvent(row: Partial<Conversation> & { id: string }) {
  realtime.emit("conversations", { eventType: "UPDATE", new: row, old: {} });
}

let ioCallback: ((entries: { isIntersecting: boolean }[]) => void) | null = null;
class FakeIntersectionObserver {
  constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
    ioCallback = cb;
  }
  observe() {}
  disconnect() {}
  unobserve() {}
}

/** Lista de verdade (ChatList) ligada ao hook, como a página faz. */
function ListHarness() {
  const list = useConversationList({ supabase: realtime.client, channelId: "", activeTab: "todos" });
  return (
    <ChatList
      conversations={list.conversations}
      channels={[]}
      activeTab="todos"
      selectedConversationId={null}
      selectedChannelId=""
      onSelectConversation={() => {}}
      onTabChange={() => {}}
      onChannelChange={() => {}}
      listError={list.listError}
      isRefreshing={list.isRefreshing}
      onRetry={() => list.refetchConversations()}
      hasMore={list.hasNextPage && !list.isRefreshing}
      loadingMore={list.isFetchingNextPage}
      onLoadMore={list.loadMore}
    />
  );
}

beforeEach(() => {
  ioCallback = null;
  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
  vi.useFakeTimers({ shouldAdvanceTime: true });
  server = new FakeServer();
  realtime = fakeSupabase();
  queryClient = createConversasQueryClient();
  vi.stubGlobal("fetch", server.fetch);
});

afterEach(() => {
  cleanup();
  queryClient.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Testes
// ---------------------------------------------------------------------------

describe("useConversationList — tempo real", () => {
  it("applies an UPDATE to a loaded conversation without refetching the list", async () => {
    server.db = [conv("a", 12), conv("b", 11), conv("c", 10)];
    const { result } = setup();
    await vi.waitFor(() => expect(result.current.conversations).toHaveLength(2));
    const listCalls = server.count(isListUrl);

    act(() => updateEvent({ id: uid("b"), last_msg_at: "2026-10-06T13:00:00+00:00", unread_count: 3 }));

    expect(ids(result.current.conversations)).toEqual([uid("b"), uid("a")]);
    expect(result.current.conversations[0].unread_count).toBe(3);
    expect(result.current.conversations[0].leads?.name).toBe("Lead b"); // joins preservados
    await tick(REFETCH_WAIT);
    expect(server.count(isListUrl)).toBe(listCalls);
  });

  it("shows a brand-new conversation (INSERT) at the top after the debounced refetch", async () => {
    server.db = [conv("a", 12), conv("b", 11)];
    const { result } = setup();
    await vi.waitFor(() => expect(result.current.conversations).toHaveLength(2));

    server.db.push(conv("n", 14));
    act(() => realtime.emit("conversations", { eventType: "INSERT", new: { id: uid("n"), channel_id: "c1" }, old: {} }));
    await tick(REFETCH_WAIT);

    await vi.waitFor(() => expect(result.current.conversations[0]?.id).toBe(uid("n")));
  });

  it("keeps the selected conversation (and its patches) when switching tabs", async () => {
    server.db = [conv("a", 12), conv("b", 11, { unread_count: 2 })];
    const { result, rerender } = setup();
    await vi.waitFor(() => expect(result.current.conversations).toHaveLength(2));

    act(() => result.current.setSelectedId(uid("a")));
    rerender({ tab: "nao_lidas" });
    await vi.waitFor(() => expect(server.count((u) => u.includes("tab=nao_lidas"))).toBe(1));
    await tick();

    expect(result.current.selectedConversation?.id).toBe(uid("a"));
    act(() => updateEvent({ id: uid("a"), followup_enabled: false }));
    expect(result.current.selectedConversation?.followup_enabled).toBe(false);
  });
});

describe("useConversationList — paginação concorrente com tempo real", () => {
  it("does not lose realtime patches that arrive while the next page is loading", async () => {
    server.db = [conv("a", 12), conv("b", 11), conv("c", 10), conv("d", 9)];
    const { result } = setup();
    await vi.waitFor(() => expect(result.current.hasNextPage).toBe(true));

    server.holds.push({ match: isNextPage, once: true });
    act(() => result.current.loadMore());
    await vi.waitFor(() => expect(server.held).toHaveLength(1));

    // Durante a busca da página 2: UPDATE, preview de mensagem e mark-read otimista.
    act(() => {
      updateEvent({ id: uid("a"), unread_count: 7 });
      realtime.emit("messages", {
        eventType: "INSERT",
        new: { conversation_id: uid("b"), role: "user", content: "chegou agora" },
      });
      result.current.patchConversation(uid("b"), { unread_count: 0 });
    });

    act(() => server.held[0].release());
    await vi.waitFor(() => expect(result.current.conversations).toHaveLength(4));

    const byId = new Map(result.current.conversations.map((c) => [c.id, c]));
    expect(byId.get(uid("a"))?.unread_count).toBe(7);
    expect(byId.get(uid("b"))?.last_message_text).toBe("chegou agora");
    expect(byId.get(uid("b"))?.unread_count).toBe(0);
  });

  it("does not let a scroll to the end cancel the refetch that brings a new conversation", async () => {
    server.db = [conv("a", 12), conv("b", 11), conv("c", 10)];
    const { result } = setup();
    await vi.waitFor(() => expect(result.current.hasNextPage).toBe(true));

    server.db.push(conv("n", 14));
    server.holds.push({ match: isFirstPage, once: true });
    act(() => realtime.emit("conversations", { eventType: "INSERT", new: { id: uid("n"), channel_id: "c1" }, old: {} }));
    await tick(REFETCH_WAIT);
    await vi.waitFor(() => expect(server.held).toHaveLength(1)); // refetch em voo

    act(() => result.current.loadMore()); // sentinela visível durante a invalidação
    await tick();
    expect(server.count(isNextPage)).toBe(0);

    act(() => server.held[0].release());
    await vi.waitFor(() => expect(result.current.conversations[0]?.id).toBe(uid("n")));
  });
});

describe("useConversationList + ChatList — erro de página", () => {
  it("does not retry a failing next page in a loop while the end of the list stays visible", async () => {
    server.db = [conv("a", 12), conv("b", 11), conv("c", 10)];
    server.failures.push({ match: isNextPage, status: 500 });
    render(
      <QueryClientProvider client={queryClient}>
        <ListHarness />
      </QueryClientProvider>,
    );
    await vi.waitFor(() => expect(screen.getByText("Carregar mais conversas")).toBeTruthy());

    act(() => ioCallback?.([{ isIntersecting: true }]));
    await tick(15_000);
    const attempts = server.count(isNextPage);
    expect(attempts).toBeGreaterThanOrEqual(1);
    expect(attempts).toBeLessThanOrEqual(2); // a tentativa + o retry do React Query
    await tick(15_000);
    expect(server.count(isNextPage)).toBe(attempts);

    // O botão manual continua pedindo de novo.
    fireEvent.click(screen.getByText("Carregar mais conversas"));
    await tick(5_000);
    expect(server.count(isNextPage)).toBeGreaterThan(attempts);
  });
});

describe("useConversationList — caches das outras abas", () => {
  async function visitUnreadTabAndBack(rerender: (p: { tab: string }) => void) {
    rerender({ tab: "nao_lidas" });
    await vi.waitFor(() => expect(server.count((u) => u.includes("tab=nao_lidas"))).toBe(1));
    await tick();
    rerender({ tab: "todos" });
    await tick();
  }

  it("refetches the 'Não lidas' cache on activation when a conversation became unread", async () => {
    server.db = [conv("a", 12), conv("b", 11)];
    const { result, rerender } = setup();
    await vi.waitFor(() => expect(result.current.conversations).toHaveLength(2));
    await visitUnreadTabAndBack(rerender);
    const listCalls = server.count(isListUrl);

    server.db[1] = { ...server.db[1], unread_count: 2 };
    act(() => updateEvent({ id: uid("b"), unread_count: 2 }));
    await tick();
    expect(server.count(isListUrl)).toBe(listCalls); // nada refeito em segundo plano

    rerender({ tab: "nao_lidas" }); // ainda dentro do staleTime de 30s
    await vi.waitFor(() => expect(ids(result.current.conversations)).toEqual([uid("b")]));
  });

  it("refetches other tabs on activation after an INSERT, even before the debounce fires", async () => {
    server.db = [conv("a", 12, { unread_count: 1 })];
    const { result, rerender } = setup();
    await vi.waitFor(() => expect(result.current.conversations).toHaveLength(1));
    await visitUnreadTabAndBack(rerender);

    server.db.push(conv("n", 14, { unread_count: 1 }));
    act(() => realtime.emit("conversations", { eventType: "INSERT", new: { id: uid("n"), channel_id: "c1" }, old: {} }));
    rerender({ tab: "nao_lidas" });
    await vi.waitFor(() => expect(ids(result.current.conversations)).toContain(uid("n")));
  });

  it("leaves other tabs alone when the update cannot change them", async () => {
    server.db = [conv("a", 12), conv("b", 11)];
    const { result, rerender } = setup();
    await vi.waitFor(() => expect(result.current.conversations).toHaveLength(2));
    await visitUnreadTabAndBack(rerender);

    act(() => updateEvent({ id: uid("b"), followup_enabled: false, unread_count: 0 }));
    rerender({ tab: "nao_lidas" });
    await tick();
    expect(server.count((u) => u.includes("tab=nao_lidas"))).toBe(1);
  });
});

describe("useConversationList — conversa aberta de fora da janela carregada", () => {
  it("keeps an old conversation out of the list but selected, patched, and in order once paged in", async () => {
    server.db = [conv("a", 12), conv("b", 11), conv("c", 10), conv("d", 9), conv("e", 8)];
    const { result } = setup();
    await vi.waitFor(() => expect(result.current.conversations).toHaveLength(2));

    const old = structuredClone(server.db[4]); // veio da busca de contatos
    act(() => {
      result.current.ensureInList(old);
      result.current.setSelectedId(old.id);
    });
    expect(ids(result.current.conversations)).toEqual([uid("a"), uid("b")]); // fora da lista
    expect(result.current.selectedConversation?.id).toBe(uid("e"));

    act(() => updateEvent({ id: uid("e"), followup_enabled: false }));
    expect(result.current.selectedConversation?.followup_enabled).toBe(false);

    act(() => result.current.loadMore());
    await vi.waitFor(() => expect(result.current.conversations).toHaveLength(4));
    act(() => result.current.loadMore());
    await vi.waitFor(() => expect(result.current.conversations).toHaveLength(5));
    expect(ids(result.current.conversations)).toEqual(["a", "b", "c", "d", "e"].map(uid));
    expect(result.current.selectedConversation?.id).toBe(uid("e"));
  });
});

describe("useConversationList — badge durante fluxo contínuo", () => {
  it("refreshes the counters during a continuous burst (throttle), not only after it stops", async () => {
    server.db = [conv("a", 12), conv("b", 11)];
    const { result } = setup();
    await vi.waitFor(() => expect(result.current.counts).toBeTruthy());
    const before = server.count(isCounts);

    act(() => updateEvent({ id: uid("a"), unread_count: 1 }));
    await tick();
    expect(server.count(isCounts)).toBe(before + 1); // borda de subida: na hora

    for (let i = 0; i < 9; i++) {
      act(() => updateEvent({ id: uid("a"), unread_count: i + 2 }));
      await tick(1_000);
    }
    // ~1 evento/s por 9s: ao menos uma atualização a cada 3s durante o fluxo.
    expect(server.count(isCounts)).toBeGreaterThanOrEqual(before + 3);
    expect(server.count(isCounts)).toBeLessThanOrEqual(before + 5);

    const duringBurst = server.count(isCounts);
    await tick(10_000);
    expect(server.count(isCounts)).toBeLessThanOrEqual(duringBurst + 1); // trailing único
  });
});
