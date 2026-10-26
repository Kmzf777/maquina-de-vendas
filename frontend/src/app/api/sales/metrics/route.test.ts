import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { createClient } from "@supabase/supabase-js";

// Cliente supabase-js de verdade, com fetch falso: assim o teste ve a URL que o
// PostgREST receberia (inclusive como dois `.or` sao serializados).
type Linha = { value: number | string | null; freight: number | string | null; status: string | null };
let linhas: Linha[] = [];
let urls: URL[] = [];
let escopo: string | null = null;

function fetchFalso(input: RequestInfo | URL): Promise<Response> {
  const url = new URL(String(input));
  urls.push(url);
  if (url.pathname.includes("/rpc/")) {
    return Promise.resolve(new Response("null", { status: 200, headers: { "content-type": "application/json" } }));
  }
  const offset = Number(url.searchParams.get("offset") ?? 0);
  const limit = Number(url.searchParams.get("limit") ?? linhas.length);
  const pagina = linhas.slice(offset, offset + limit);
  return Promise.resolve(
    new Response(JSON.stringify(pagina), { status: 200, headers: { "content-type": "application/json" } }),
  );
}

vi.mock("@/lib/supabase/api", () => ({
  getServiceSupabase: async () => createClient("http://supa.test", "chave", { global: { fetch: fetchFalso } }),
}));
vi.mock("@/lib/sales/sales-scope-route", () => ({
  resolverEscopoDeVendas: async () => ({ ok: true, escopo, user: null }),
}));
vi.mock("@/lib/sales/sales-scope", () => ({
  vendedorDaRecompra: () => null,
}));

import { GET } from "./route";

async function chamar(qs = "") {
  const res = await GET(new NextRequest(`http://x/api/sales/metrics${qs}`));
  return res.json();
}

function consultasDeVendas() {
  return urls.filter((u) => u.pathname.endsWith("/sales"));
}

beforeEach(() => {
  linhas = [];
  urls = [];
  escopo = null;
});

describe("GET /api/sales/metrics", () => {
  it("deixa a cancelada fora da receita, da contagem e do ticket", async () => {
    linhas = [
      { value: 100, freight: 0, status: "aprovada" },
      { value: 300, freight: 0, status: "Cancelada" },
    ];
    const r = await chamar();
    expect(r.total_value).toBe(100);
    expect(r.count).toBe(1);
    expect(r.avg_value).toBe(100);
  });

  it("pede ao banco so status nulo ou nao cancelado", async () => {
    await chamar();
    expect(consultasDeVendas()[0].searchParams.getAll("or")).toContain("(status.is.null,status.neq.cancelada)");
  });

  it("combina o filtro de status com o escopo em dois parametros `or` (AND no PostgREST)", async () => {
    escopo = "sold_by.eq.joao,created_by.eq.joao";
    await chamar();
    const ors = consultasDeVendas()[0].searchParams.getAll("or");
    expect(ors).toHaveLength(2);
    expect(ors).toContain("(status.is.null,status.neq.cancelada)");
    expect(ors).toContain("(sold_by.eq.joao,created_by.eq.joao)");
  });

  it("separa o frete da receita e o ticket sai sem frete", async () => {
    linhas = [
      { value: 120, freight: 20, status: null },
      { value: "230.50", freight: "30.50", status: "aprovada" },
    ];
    const r = await chamar();
    expect(r.total_value).toBe(300);
    expect(r.freight_value).toBe(50.5);
    expect(r.count).toBe(2);
    expect(r.avg_value).toBe(150);
  });

  it("usa os limites do dia em Brasilia", async () => {
    await chamar("?from=2026-10-01&to=2026-10-31");
    const soldAt = consultasDeVendas()[0].searchParams.getAll("sold_at");
    expect(soldAt).toContain("gte.2026-10-01T00:00:00.000-03:00");
    expect(soldAt).toContain("lte.2026-10-31T23:59:59.999-03:00");
  });

  it("filtra o vendedor com ilike, escapando % e _", async () => {
    await chamar("?sold_by=Jo%25ao_x");
    expect(consultasDeVendas()[0].searchParams.get("sold_by")).toBe("ilike.Jo\\%ao\\_x");
  });

  it("vendedor com asterisco (curinga do PostgREST) usa eq", async () => {
    await chamar("?sold_by=jo*");
    expect(consultasDeVendas()[0].searchParams.get("sold_by")).toBe("eq.jo*");
  });

  it("soma todas as linhas, paginando de 1.000 em 1.000 e ordenando por id", async () => {
    linhas = Array.from({ length: 1500 }, () => ({ value: 10, freight: 1, status: null }));
    const r = await chamar();
    const qs = consultasDeVendas();
    expect(qs).toHaveLength(2);
    expect(qs[0].searchParams.get("order")).toBe("id.asc");
    expect(qs[1].searchParams.get("offset")).toBe("1000");
    expect(r.count).toBe(1500);
    expect(r.total_value).toBe(13500);
    expect(r.freight_value).toBe(1500);
  });
});
