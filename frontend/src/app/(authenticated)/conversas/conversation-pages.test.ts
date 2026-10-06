import { describe, it, expect } from "vitest";
import type { Conversation } from "@/lib/types";
import { encodeCursor } from "@/app/api/conversations/list-params";
import {
  conversationBelongsToKey,
  conversationsQueryKey,
  flattenPages,
  insertIntoPages,
  isWithinLoadedWindow,
  patchPages,
  shouldFetchUnknownRow,
  type ConversationPages,
} from "./conversation-pages";

function conv(id: string, last: string | null, over: Partial<Conversation> = {}): Conversation {
  return {
    id,
    lead_id: "l1",
    channel_id: "c1",
    stage: "secretaria",
    status: "active",
    last_msg_at: last,
    created_at: "2026-01-01T00:00:00Z",
    agent_profile_id: null,
    last_message_text: null,
    unread_count: 0,
    last_customer_message_at: null,
    whatsapp_window_expires_at: null,
    followup_enabled: true,
    first_seller_response_at: null,
    last_seller_response_at: null,
    ...over,
  } as Conversation;
}

const ID_B = "00000000-0000-0000-0000-00000000000b";

function pages(): ConversationPages {
  return {
    pages: [
      {
        conversations: [conv("a", "2026-10-06T12:00:00+00:00"), conv("b", "2026-10-06T11:00:00+00:00")],
        next_cursor: encodeCursor({ t: "2026-10-06T11:00:00+00:00", id: ID_B }),
      },
      {
        conversations: [conv("c", "2026-10-06T10:00:00+00:00"), conv("d", "2026-10-06T09:00:00+00:00")],
        next_cursor: encodeCursor({ t: "2026-10-06T09:00:00+00:00", id: ID_B }),
      },
    ],
    pageParams: [null, "x"],
  };
}

describe("flattenPages", () => {
  it("concatenates pages and drops duplicates (first wins)", () => {
    const data = pages();
    data.pages[1].conversations.push(conv("a", "2026-10-06T08:00:00+00:00"));
    expect(flattenPages(data).map((c) => c.id)).toEqual(["a", "b", "c", "d"]);
    expect(flattenPages(undefined)).toEqual([]);
  });
});

describe("patchPages", () => {
  it("applies a whole-list updater and keeps page sizes, cursors and params", () => {
    const data = pages();
    const out = patchPages(data, (list) => [list[3], ...list.slice(0, 3)]);
    expect(out.pages.map((p) => p.conversations.map((c) => c.id))).toEqual([["d", "a"], ["b", "c"]]);
    expect(out.pages.map((p) => p.next_cursor)).toEqual(data.pages.map((p) => p.next_cursor));
    expect(out.pageParams).toBe(data.pageParams);
  });

  it("lets the last page absorb growth and shrinkage", () => {
    const grown = patchPages(pages(), (list) => [conv("n", null), ...list]);
    expect(grown.pages.map((p) => p.conversations.length)).toEqual([2, 3]);
    const shrunk = patchPages(pages(), (list) => list.slice(1));
    expect(shrunk.pages.map((p) => p.conversations.length)).toEqual([2, 1]);
  });
});

describe("insertIntoPages", () => {
  it("inserts in last_msg_at order", () => {
    const out = insertIntoPages(pages(), conv("x", "2026-10-06T10:30:00+00:00"));
    expect(flattenPages(out).map((c) => c.id)).toEqual(["a", "b", "x", "c", "d"]);
  });

  it("keeps the cached copy when the conversation is already there (it carries live state)", () => {
    const data = pages();
    const out = insertIntoPages(data, conv("a", "2026-10-06T12:00:00+00:00", { unread_count: 9 }));
    expect(out).toBe(data);
  });

  it("skips a conversation older than the loaded window (the next page brings it)", () => {
    const data = pages();
    expect(insertIntoPages(data, conv("old", "2026-10-01T00:00:00+00:00"))).toBe(data);
    expect(insertIntoPages(data, conv("nul", null))).toBe(data);
    const inside = insertIntoPages(data, conv("new", "2026-10-06T13:00:00+00:00"));
    expect(flattenPages(inside)[0].id).toBe("new");
  });

  it("compares instants, not strings (Z vs +00:00, fractions)", () => {
    const out = insertIntoPages(pages(), conv("x", "2026-10-06T11:30:00.5Z"));
    expect(flattenPages(out).map((c) => c.id)).toEqual(["a", "x", "b", "c", "d"]);
    // 09:00-03:00 = 12:00Z, empatada com "a": desempata por id desc ("y" > "a").
    const later = insertIntoPages(pages(), conv("y", "2026-10-06T09:00:00-03:00"));
    expect(flattenPages(later).map((c) => c.id).slice(0, 2)).toEqual(["y", "a"]);
  });

  it("breaks timestamp ties by id desc, like the route", () => {
    const data = pages();
    data.pages[0].conversations[1] = conv(ID_B, "2026-10-06T11:00:00+00:00");
    const tie = "2026-10-06T11:00:00+00:00";
    const higher = insertIntoPages(data, conv("00000000-0000-0000-0000-00000000000c", tie));
    expect(flattenPages(higher).map((c) => c.id).slice(0, 3)).toEqual([
      "a",
      "00000000-0000-0000-0000-00000000000c",
      ID_B,
    ]);
    const lower = insertIntoPages(data, conv("00000000-0000-0000-0000-00000000000a", tie));
    expect(flattenPages(lower).map((c) => c.id).slice(0, 3)).toEqual([
      "a",
      ID_B,
      "00000000-0000-0000-0000-00000000000a",
    ]);
  });

  it("does not reorder the rest of the list", () => {
    const data = pages();
    // Fora de ordem de propósito (patch local ainda não reordenado).
    data.pages[1].conversations.reverse();
    const out = insertIntoPages(data, conv("x", "2026-10-06T11:30:00+00:00"));
    expect(flattenPages(out).map((c) => c.id)).toEqual(["a", "x", "b", "d", "c"]);
  });
});

describe("isWithinLoadedWindow — empate no cursor", () => {
  it("uses the id to place a row tied with the boundary timestamp", () => {
    const at = "2026-10-06T09:00:00+00:00"; // fronteira: t=09:00, id=ID_B
    expect(isWithinLoadedWindow(pages(), at, "00000000-0000-0000-0000-00000000000c")).toBe(true);
    expect(isWithinLoadedWindow(pages(), at, ID_B)).toBe(true);
    expect(isWithinLoadedWindow(pages(), at, "00000000-0000-0000-0000-00000000000a")).toBe(false);
  });
});

describe("isWithinLoadedWindow", () => {
  it("is true for anything at or after the boundary of the last loaded page", () => {
    expect(isWithinLoadedWindow(pages(), "2026-10-06T09:00:00+00:00")).toBe(true);
    expect(isWithinLoadedWindow(pages(), "2026-10-06T13:00:00.5+00:00")).toBe(true);
  });

  it("is false for older rows and for the null tail while more pages exist", () => {
    expect(isWithinLoadedWindow(pages(), "2026-10-05T00:00:00+00:00")).toBe(false);
    expect(isWithinLoadedWindow(pages(), null)).toBe(false);
  });

  it("is true when everything is loaded or nothing is cached yet", () => {
    const data = pages();
    data.pages[1].next_cursor = null;
    expect(isWithinLoadedWindow(data, "2020-01-01T00:00:00+00:00")).toBe(true);
    expect(isWithinLoadedWindow(undefined, null)).toBe(true);
  });
});

describe("shouldFetchUnknownRow", () => {
  it("skips rows that cannot belong to the unread or personal tabs", () => {
    expect(shouldFetchUnknownRow({ id: "x", unread_count: 0 }, "nao_lidas")).toBe(false);
    expect(shouldFetchUnknownRow({ id: "x", unread_count: 2 }, "nao_lidas")).toBe(true);
    expect(shouldFetchUnknownRow({ id: "x", lead_id: "l1" }, "pessoal")).toBe(false);
  });

  it("fetches for 'todos' and segment tabs (the row has no lead stage)", () => {
    expect(shouldFetchUnknownRow({ id: "x" }, "todos")).toBe(true);
    expect(shouldFetchUnknownRow({ id: "x" }, "atacado")).toBe(true);
  });
});

describe("conversationBelongsToKey", () => {
  it("checks channel and tab of the cache key", () => {
    const atacado = conv("x", null, { leads: { id: "l1", stage: "atacado" } as never });
    expect(conversationBelongsToKey(atacado, conversationsQueryKey("", "atacado"))).toBe(true);
    expect(conversationBelongsToKey(atacado, conversationsQueryKey("", "consumo"))).toBe(false);
    expect(conversationBelongsToKey(atacado, conversationsQueryKey("c2", "todos"))).toBe(false);
    expect(conversationBelongsToKey(atacado, conversationsQueryKey("c1", "todos"))).toBe(true);
  });
});
