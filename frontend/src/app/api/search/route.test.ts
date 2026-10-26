import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

// D7 (1e6381fe): o filtro de data da busca e o dia de Brasilia, nao o dia UTC.
let chamadas: Array<{ fn: string; args: Record<string, unknown> }> = [];
let linhasVendas: Array<Record<string, unknown>> = [];

vi.mock("@/lib/supabase/api", () => ({
  getServiceSupabase: async () => ({
    rpc: async (fn: string, args: Record<string, unknown>) => {
      chamadas.push({ fn, args });
      return { data: fn === "search_sales" ? linhasVendas : [], error: null };
    },
  }),
}));
vi.mock("@/lib/supabase/channel-access", () => ({
  getAllowedChannelIds: async () => null,
  ChannelAccessError: class extends Error {},
}));
vi.mock("@/lib/supabase/pipeline-access", () => ({
  getAllowedPipelineIds: async () => null,
  PipelineAccessError: class extends Error {},
}));

import { GET } from "./route";

beforeEach(() => {
  chamadas = [];
  linhasVendas = [];
});

describe("GET /api/search", () => {
  it("limites do periodo no dia de Brasilia (-03:00), nao em UTC", async () => {
    await GET(new NextRequest("http://x/api/search?q=cafe&date_from=2026-10-01&date_to=2026-10-26"));
    const vendas = chamadas.find((c) => c.fn === "search_sales")!;
    expect(vendas.args.p_sold_after).toBe("2026-10-01T00:00:00.000-03:00");
    expect(vendas.args.p_sold_before).toBe("2026-10-26T23:59:59.999-03:00");
    const leads = chamadas.find((c) => c.fn === "search_leads")!;
    expect(leads.args.p_created_after).toBe("2026-10-01T00:00:00.000-03:00");
  });

  it("sem periodo, nao inventa limite", async () => {
    await GET(new NextRequest("http://x/api/search?q=cafe"));
    const vendas = chamadas.find((c) => c.fn === "search_sales")!;
    expect(vendas.args.p_sold_after).toBeNull();
    expect(vendas.args.p_sold_before).toBeNull();
  });

  it("repassa status e frete da venda quando a funcao SQL os devolve", async () => {
    linhasVendas = [{ id: "s1", value: 500, freight: 50, status: "cancelada", total_count: 1 }];
    const body = await (await GET(new NextRequest("http://x/api/search?q=cafe"))).json();
    expect(body.sales.data[0]).toMatchObject({ freight: 50, status: "cancelada" });
  });
});
