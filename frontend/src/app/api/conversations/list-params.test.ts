import { describe, it, expect } from "vitest";
import {
  CONVERSATIONS_PAGE_SIZE,
  conversationsListUrl,
  cursorOrFilter,
  decodeCursor,
  encodeCursor,
  parseTabFilter,
  splitPage,
} from "./list-params";

const ID = "00000000-0000-0000-0000-000000000001";

describe("cursor", () => {
  it("round-trips timestamp and id", () => {
    const raw = encodeCursor({ t: "2026-10-06T12:00:00.123456+00:00", id: ID });
    expect(decodeCursor(raw)).toEqual({ t: "2026-10-06T12:00:00.123456+00:00", id: ID });
  });

  it("round-trips the null tail (conversations without last_msg_at)", () => {
    expect(decodeCursor(encodeCursor({ t: null, id: ID }))).toEqual({ t: null, id: ID });
  });

  it("rejects anything that could inject into the PostgREST filter", () => {
    expect(decodeCursor(null)).toBeNull();
    expect(decodeCursor("")).toBeNull();
    expect(decodeCursor("sem-separador")).toBeNull();
    expect(decodeCursor(`2026-10-06T12:00:00Z|${ID},status.eq.blocked`)).toBeNull();
    expect(decodeCursor(`2026-10-06),id.gt.0|${ID}`)).toBeNull();
    // `+` que virou espaço por falta de encode: inválido, não um timestamp truncado.
    expect(decodeCursor(`2026-10-06T12:00:00 00:00|${ID}`)).toBeNull();
  });
});

describe("cursorOrFilter", () => {
  it("selects rows strictly after the cursor in last_msg_at desc nulls last, id desc", () => {
    expect(cursorOrFilter("2026-10-06T12:00:00+00:00", ID)).toBe(
      `last_msg_at.lt."2026-10-06T12:00:00+00:00",and(last_msg_at.eq."2026-10-06T12:00:00+00:00",id.lt.${ID}),last_msg_at.is.null`,
    );
  });
});

describe("parseTabFilter", () => {
  it("maps every tab of the list to a server filter", () => {
    expect(parseTabFilter("todos")).toEqual({ kind: "all" });
    expect(parseTabFilter(null)).toEqual({ kind: "all" });
    expect(parseTabFilter("nao_lidas")).toEqual({ kind: "unread" });
    expect(parseTabFilter("pessoal")).toEqual({ kind: "no_lead" });
    for (const stage of ["atacado", "private_label", "exportacao", "consumo"]) {
      expect(parseTabFilter(stage)).toEqual({ kind: "stage", stage });
    }
  });

  it("ignores unknown tabs instead of filtering by an arbitrary stage", () => {
    expect(parseTabFilter("pending")).toEqual({ kind: "all" });
    expect(parseTabFilter("x,status.eq.blocked")).toEqual({ kind: "all" });
  });
});

describe("splitPage", () => {
  const rows = (n: number) =>
    Array.from({ length: n }, (_, i) => ({
      id: `00000000-0000-0000-0000-${String(i).padStart(12, "0")}`,
      last_msg_at: i === n - 1 ? null : `2026-10-06T12:00:${String(59 - (i % 60)).padStart(2, "0")}+00:00`,
    }));

  it("returns everything and no cursor when the page is not full", () => {
    const r = rows(3);
    expect(splitPage(r, 5)).toEqual({ rows: r, next_cursor: null });
  });

  it("cuts at pageSize and points the cursor at the last kept row", () => {
    const r = rows(6);
    const out = splitPage(r, 5);
    expect(out.rows).toHaveLength(5);
    expect(decodeCursor(out.next_cursor)).toEqual({ t: r[4].last_msg_at, id: r[4].id });
  });

  it("uses a 200-row page", () => {
    expect(CONVERSATIONS_PAGE_SIZE).toBe(200);
  });
});

describe("conversationsListUrl", () => {
  it("omits defaults", () => {
    expect(conversationsListUrl({})).toBe("/api/conversations");
    expect(conversationsListUrl({ tab: "todos" })).toBe("/api/conversations");
  });

  it("encodes the cursor so '+' survives the query string", () => {
    const cursor = encodeCursor({ t: "2026-10-06T12:00:00+00:00", id: ID });
    const url = conversationsListUrl({ channelId: "c1", tab: "atacado", cursor });
    const qs = new URL(url, "http://x").searchParams;
    expect(qs.get("channel_id")).toBe("c1");
    expect(qs.get("tab")).toBe("atacado");
    expect(qs.get("cursor")).toBe(cursor);
  });

  it("supports the lead filter used by deep-link and sibling conversations", () => {
    expect(conversationsListUrl({ leadId: "l1" })).toBe("/api/conversations?lead_id=l1");
  });
});
