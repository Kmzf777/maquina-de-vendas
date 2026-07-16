import { describe, expect, it } from "vitest";
import type { Message } from "@/lib/types";
import {
  MESSAGE_PAGE_SIZE,
  mergeOlderPage,
  normalizeOrder,
  pageHasMore,
} from "./messages-window";

function msg(id: string, at: string, extra: Partial<Message> = {}): Message {
  return { id, created_at: at, content: id, role: "user", ...extra } as Message;
}

describe("pageHasMore", () => {
  it("página cheia indica mais histórico; parcial indica fim", () => {
    expect(pageHasMore(MESSAGE_PAGE_SIZE)).toBe(true);
    expect(pageHasMore(MESSAGE_PAGE_SIZE - 1)).toBe(false);
    expect(pageHasMore(0)).toBe(false);
  });
});

describe("mergeOlderPage", () => {
  it("prepend mantém ordem cronológica e deduplica por id", () => {
    const current = [msg("c1", "2026-07-10T10:00:00Z"), msg("c2", "2026-07-10T11:00:00Z")];
    const older = [msg("o1", "2026-07-10T08:00:00Z"), msg("c1", "2026-07-10T10:00:00Z")];
    const out = mergeOlderPage(current, older);
    expect(out.map((m) => m.id)).toEqual(["o1", "c1", "c2"]);
  });

  it("resolve citação cuja original está na página mais antiga", () => {
    const original = msg("orig", "2026-07-10T08:00:00Z", { wamid: "w-1" });
    const reply = msg("rep", "2026-07-10T10:00:00Z", { quoted_wamid: "w-1" });
    const out = mergeOlderPage([reply], [original]);
    const rep = out.find((m) => m.id === "rep")!;
    expect(rep.quoted_message?.id).toBe("orig");
  });
});

describe("normalizeOrder", () => {
  it("ordena por created_at e remove duplicatas mantendo a última", () => {
    const out = normalizeOrder([
      msg("b", "2026-07-10T11:00:00Z"),
      msg("a", "2026-07-10T10:00:00Z"),
      msg("b", "2026-07-10T11:00:00Z"),
    ]);
    expect(out.map((m) => m.id)).toEqual(["a", "b"]);
  });
});
