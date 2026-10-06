import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));
vi.mock("@/lib/supabase/channel-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/supabase/channel-access")>()),
  getAllowedChannelIds: vi.fn(),
}));

import { GET } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";
import { ChannelAccessError, getAllowedChannelIds } from "@/lib/supabase/channel-access";

type Chamada = { metodo: string; args: unknown[] };

/** Cada `from()` é uma consulta; a contagem devolvida depende de ter `gt(unread_count)`. */
function instalar({ total = 0, unread = 0, erro = null as string | null } = {}) {
  const consultas: Chamada[][] = [];
  const from = () => {
    const chamadas: Chamada[] = [];
    consultas.push(chamadas);
    const builder: Record<string, unknown> = {};
    for (const metodo of ["select", "neq", "in", "gt"]) {
      builder[metodo] = (...args: unknown[]) => {
        chamadas.push({ metodo, args });
        return builder;
      };
    }
    builder.then = (ok: (r: unknown) => unknown) => {
      const ehUnread = chamadas.some((c) => c.metodo === "gt");
      return Promise.resolve({
        data: null,
        count: ehUnread ? unread : total,
        error: erro ? { message: erro } : null,
      }).then(ok);
    };
    return builder;
  };
  vi.mocked(getServiceSupabase).mockResolvedValue({ from } as never);
  vi.mocked(getAllowedChannelIds).mockResolvedValue(null);
  return { consultas };
}

const chamar = (qs = "") => GET(new NextRequest(`http://localhost/api/conversations/counts${qs}`));

afterEach(() => vi.clearAllMocks());

describe("GET /api/conversations/counts", () => {
  it("counts total and unread without fetching rows (no 1000-row cap)", async () => {
    const { consultas } = instalar({ total: 5568, unread: 1573 });
    const body = await (await chamar()).json();
    expect(body).toEqual({ total: 5568, unread: 1573 });
    expect(consultas).toHaveLength(2);
    for (const chamadas of consultas) {
      expect(chamadas[0]).toEqual({ metodo: "select", args: ["id", { count: "exact", head: true }] });
      expect(chamadas).toContainEqual({ metodo: "neq", args: ["status", "blocked"] });
    }
    expect(consultas.filter((c) => c.some((x) => x.metodo === "gt"))[0]).toContainEqual({
      metodo: "gt",
      args: ["unread_count", 0],
    });
  });

  it("restricts to the selected channel", async () => {
    const { consultas } = instalar();
    await chamar("?channel_id=c1");
    for (const chamadas of consultas) {
      expect(chamadas).toContainEqual({ metodo: "in", args: ["channel_id", ["c1"]] });
    }
  });

  it("restricts a seller to their own channels", async () => {
    const { consultas } = instalar();
    vi.mocked(getAllowedChannelIds).mockResolvedValue(["c1", "c2"]);
    await chamar();
    expect(consultas[0]).toContainEqual({ metodo: "in", args: ["channel_id", ["c1", "c2"]] });
  });

  it("answers zeros without querying when the channel is out of scope", async () => {
    const { consultas } = instalar({ total: 9 });
    vi.mocked(getAllowedChannelIds).mockResolvedValue(["c1"]);
    const body = await (await chamar("?channel_id=c9")).json();
    expect(body).toEqual({ total: 0, unread: 0 });
    expect(consultas).toHaveLength(0);
  });

  it("returns 401 on auth failure and 500 on query error", async () => {
    instalar();
    vi.mocked(getAllowedChannelIds).mockRejectedValue(new ChannelAccessError("x"));
    expect((await chamar()).status).toBe(401);
    instalar({ erro: "boom" });
    expect((await chamar()).status).toBe(500);
  });
});
