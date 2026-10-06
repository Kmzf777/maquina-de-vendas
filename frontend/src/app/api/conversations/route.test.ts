import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));
vi.mock("@/lib/supabase/channel-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/supabase/channel-access")>()),
  getAllowedChannelIds: vi.fn(),
}));

import { GET } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds } from "@/lib/supabase/channel-access";
import { cursorOrFilter, decodeCursor, encodeCursor } from "./list-params";

type Chamada = { tabela: string; metodo: string; args: unknown[] };

const uuid = (i: number) => `00000000-0000-0000-0000-${String(i).padStart(12, "0")}`;
const linha = (i: number) => ({
  id: uuid(i),
  channel_id: "c1",
  last_msg_at: new Date(Date.UTC(2026, 9, 6, 12) - i * 60_000).toISOString(),
  leads: { id: `l${i}`, phone: `55349${i}` },
  channels: { provider: "meta_cloud" },
});

/** supabase-js falso: todo método encadeia; `await` devolve as linhas da tabela. */
function instalar(linhasConversas: unknown[]) {
  const chamadas: Chamada[] = [];
  const tabelas: string[] = [];
  const from = (tabela: string) => {
    tabelas.push(tabela);
    const builder: Record<string, unknown> = {};
    for (const metodo of ["select", "eq", "neq", "in", "is", "gt", "lt", "or", "order", "limit"]) {
      builder[metodo] = (...args: unknown[]) => {
        chamadas.push({ tabela, metodo, args });
        return builder;
      };
    }
    builder.then = (ok: (r: unknown) => unknown) =>
      Promise.resolve({ data: tabela === "conversations" ? linhasConversas : [], error: null }).then(ok);
    return builder;
  };
  const rpc = vi.fn().mockResolvedValue({ data: [], error: null });
  vi.mocked(getServiceSupabase).mockResolvedValue({ from, rpc } as never);
  vi.mocked(getAllowedChannelIds).mockResolvedValue(null);
  const de = (metodo: string) =>
    chamadas.filter((c) => c.tabela === "conversations" && c.metodo === metodo).map((c) => c.args);
  return { chamadas, tabelas, de };
}

const chamar = (qs = "") => GET(new NextRequest(`http://localhost/api/conversations${qs}`));

afterEach(() => vi.clearAllMocks());

describe("GET /api/conversations — paginação", () => {
  it("asks for one row more than the page, in keyset order", async () => {
    const { de } = instalar([linha(1)]);
    await chamar();
    expect(de("limit")).toEqual([[201]]);
    expect(de("order")).toEqual([
      ["last_msg_at", { ascending: false, nullsFirst: false }],
      ["id", { ascending: false }],
    ]);
    expect(de("neq")).toContainEqual(["status", "blocked"]);
  });

  it("returns the page and no cursor when everything fits", async () => {
    instalar([linha(1), linha(2)]);
    const body = await (await chamar()).json();
    expect(body.conversations.map((c: { id: string }) => c.id)).toEqual([uuid(1), uuid(2)]);
    expect(body.next_cursor).toBeNull();
  });

  it("cuts at 200 and points next_cursor at the 200th row", async () => {
    const rows = Array.from({ length: 201 }, (_, i) => linha(i + 1));
    instalar(rows);
    const body = await (await chamar()).json();
    expect(body.conversations).toHaveLength(200);
    expect(decodeCursor(body.next_cursor)).toEqual({ t: rows[199].last_msg_at, id: rows[199].id });
  });

  it("applies the keyset filter for a cursor and skips the legacy Evolution merge", async () => {
    const { de, tabelas } = instalar([]);
    const t = "2026-10-06T12:00:00.123456+00:00";
    await chamar(`?cursor=${encodeURIComponent(encodeCursor({ t, id: uuid(9) }))}`);
    expect(de("or")).toEqual([[cursorOrFilter(t, uuid(9))]]);
    expect(tabelas).not.toContain("channels");
  });

  it("walks the null tail by id when the cursor is already there", async () => {
    const { de } = instalar([]);
    await chamar(`?cursor=${encodeURIComponent(encodeCursor({ t: null, id: uuid(9) }))}`);
    expect(de("is")).toContainEqual(["last_msg_at", null]);
    expect(de("lt")).toContainEqual(["id", uuid(9)]);
    expect(de("or")).toEqual([]);
  });

  it("rejects a malformed cursor with 400 instead of ignoring it", async () => {
    instalar([]);
    const res = await chamar("?cursor=lixo");
    expect(res.status).toBe(400);
  });
});

describe("GET /api/conversations — abas como filtro de servidor", () => {
  it("filters a segment tab by the lead stage with an inner join", async () => {
    const { de } = instalar([]);
    await chamar("?tab=atacado");
    expect(String(de("select")[0][0])).toContain("leads!inner(");
    expect(de("eq")).toContainEqual(["leads.stage", "atacado"]);
  });

  it("filters the unread tab by unread_count", async () => {
    const { de } = instalar([]);
    await chamar("?tab=nao_lidas");
    expect(de("gt")).toContainEqual(["unread_count", 0]);
    expect(String(de("select")[0][0])).not.toContain("leads!inner(");
  });

  it("filters the personal tab by missing lead", async () => {
    const { de } = instalar([]);
    await chamar("?tab=pessoal");
    expect(de("is")).toContainEqual(["lead_id", null]);
  });

  it("keeps channel and lead filters", async () => {
    const { de } = instalar([]);
    await chamar("?channel_id=c9&lead_id=l9");
    expect(de("eq")).toContainEqual(["channel_id", "c9"]);
    expect(de("eq")).toContainEqual(["lead_id", "l9"]);
  });

  it("answers an empty page for a user without channels", async () => {
    instalar([linha(1)]);
    vi.mocked(getAllowedChannelIds).mockResolvedValue([]);
    const body = await (await chamar()).json();
    expect(body).toEqual({ conversations: [], next_cursor: null });
  });
});
