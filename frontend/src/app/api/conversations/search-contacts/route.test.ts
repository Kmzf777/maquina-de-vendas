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
import { buildLeadSearchOrFilter } from "@/lib/search";

function instalar() {
  const chamadas: { metodo: string; args: unknown[] }[] = [];
  const builder: Record<string, unknown> = {};
  for (const metodo of ["select", "or", "order", "limit", "in"]) {
    builder[metodo] = (...args: unknown[]) => {
      chamadas.push({ metodo, args });
      return builder;
    };
  }
  builder.then = (ok: (r: unknown) => unknown) => Promise.resolve({ data: [], error: null }).then(ok);
  vi.mocked(getServiceSupabase).mockResolvedValue({ from: () => builder, rpc: vi.fn() } as never);
  vi.mocked(getAllowedChannelIds).mockResolvedValue(null);
  return chamadas;
}

const chamar = (q: string) =>
  GET(new NextRequest(`http://localhost/api/conversations/search-contacts?q=${encodeURIComponent(q)}`));

afterEach(() => vi.clearAllMocks());

describe("GET /api/conversations/search-contacts", () => {
  it("searches leads by every term, in any order", async () => {
    const chamadas = instalar();
    await chamar("angelucci hiago");
    const or = chamadas.find((c) => c.metodo === "or");
    expect(or?.args).toEqual([buildLeadSearchOrFilter("angelucci hiago"), { referencedTable: "leads" }]);
    expect(String(or?.args[0])).toContain("and(or(");
  });

  it("searches a masked CNPJ by its digits", async () => {
    const chamadas = instalar();
    await chamar("25.139.264/0001-51");
    const or = chamadas.find((c) => c.metodo === "or");
    expect(String(or?.args[0])).toContain("cnpj.imatch.2[^0-9]?[^0-9]?5");
  });

  it("uses an inner join so the filter drops non-matching conversations", async () => {
    const chamadas = instalar();
    await chamar("hiago");
    expect(String(chamadas.find((c) => c.metodo === "select")?.args[0])).toContain("leads!inner(");
  });
});
