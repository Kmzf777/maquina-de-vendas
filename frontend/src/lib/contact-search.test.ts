import { describe, it, expect } from "vitest";
import { UNREAD_TAB_KEY } from "./constants";
import { conversationMatchesTab, mergeContactResults } from "./contact-search";
import type { Conversation } from "./types";

function conv(over: Partial<Conversation> & { id: string }): Conversation {
  return {
    lead_id: "l1",
    channel_id: "c1",
    stage: "secretaria",
    status: "active",
    last_msg_at: "2026-08-01T10:00:00Z",
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

describe("conversationMatchesTab", () => {
  it("accepts everything on the 'todos' tab", () => {
    expect(conversationMatchesTab(conv({ id: "a" }), "todos")).toBe(true);
  });

  it("keeps only unread conversations on the unread tab", () => {
    expect(conversationMatchesTab(conv({ id: "a", unread_count: 0 }), UNREAD_TAB_KEY)).toBe(false);
    expect(conversationMatchesTab(conv({ id: "b", unread_count: 3 }), UNREAD_TAB_KEY)).toBe(true);
  });

  it("keeps only lead-less conversations on the 'pessoal' tab", () => {
    expect(conversationMatchesTab(conv({ id: "a" }), "pessoal")).toBe(true);
    const withLead = conv({ id: "b", leads: { id: "l1", stage: "atacado" } as never });
    expect(conversationMatchesTab(withLead, "pessoal")).toBe(false);
  });

  it("filters by lead stage on a segment tab", () => {
    const atacado = conv({ id: "a", leads: { id: "l1", stage: "atacado" } as never });
    expect(conversationMatchesTab(atacado, "atacado")).toBe(true);
    expect(conversationMatchesTab(atacado, "private_label")).toBe(false);
  });
});

describe("mergeContactResults", () => {
  it("appends remote conversations the local list does not have", () => {
    const local = [conv({ id: "a", last_msg_at: "2026-08-10T00:00:00Z" })];
    const remote = [conv({ id: "z", last_msg_at: "2026-07-15T00:00:00Z" })];
    expect(mergeContactResults(local, remote).map((c) => c.id)).toEqual(["a", "z"]);
  });

  it("lets the local copy win on duplicates (it carries live state)", () => {
    const local = [conv({ id: "a", unread_count: 7 })];
    const remote = [conv({ id: "a", unread_count: 0 })];
    const merged = mergeContactResults(local, remote);
    expect(merged).toHaveLength(1);
    expect(merged[0].unread_count).toBe(7);
  });

  it("returns the merge sorted by last_msg_at desc", () => {
    const local = [conv({ id: "old", last_msg_at: "2026-07-01T00:00:00Z" })];
    const remote = [conv({ id: "new", last_msg_at: "2026-08-01T00:00:00Z" })];
    expect(mergeContactResults(local, remote).map((c) => c.id)).toEqual(["new", "old"]);
  });

  it("survives an empty side", () => {
    const only = [conv({ id: "a" })];
    expect(mergeContactResults(only, [])).toHaveLength(1);
    expect(mergeContactResults([], only)).toHaveLength(1);
    expect(mergeContactResults([], [])).toEqual([]);
  });
});
