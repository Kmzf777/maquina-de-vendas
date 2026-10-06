/**
 * GET /api/leads?q= — busca de leads no servidor para o seletor de lead dos
 * painéis de venda/orçamento (revisão do P4). O seletor buscava em
 * `search-contacts`, que só acha lead COM conversa: `bling-*`, importados e
 * lista fria sumiram do "Registrar venda" da tela de vendas.
 *
 * Escopo: o mesmo do GET sem `q` — qualquer usuário autenticado (o `proxy.ts`
 * barra o resto) vê a base de leads inteira pelo service role. A busca não
 * amplia nem estreita isso; só filtra e limita.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { GET } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";
import { buildLeadSearchOrFilter } from "@/lib/search";

type Chamada = { metodo: string; args: unknown[] };

function instalar(linhas: unknown[] = []) {
  const chamadas: Chamada[] = [];
  const tabelas: string[] = [];
  const builder: Record<string, unknown> = {};
  for (const metodo of ["select", "or", "order", "limit", "in", "not", "eq", "gte", "lte"]) {
    builder[metodo] = (...args: unknown[]) => {
      chamadas.push({ metodo, args });
      return builder;
    };
  }
  builder.then = (ok: (r: unknown) => unknown) =>
    Promise.resolve({ data: linhas, error: null }).then(ok);
  vi.mocked(getServiceSupabase).mockResolvedValue({
    from: (t: string) => {
      tabelas.push(t);
      return builder;
    },
  } as never);
  return { chamadas, tabelas };
}

const chamar = (qs: string) => GET(new NextRequest(`http://localhost/api/leads?${qs}`));

afterEach(() => vi.clearAllMocks());

describe("GET /api/leads?q=", () => {
  it("busca na tabela de leads (não em conversas) com o filtro de busca do CRM", async () => {
    const lead = { id: "l1", name: "Serginho", phone: "bling-123" };
    const { chamadas, tabelas } = instalar([lead]);
    const res = await chamar("q=serginho&limit=30");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual([lead]);
    expect(tabelas).toEqual(["leads"]);
    expect(chamadas.find((c) => c.metodo === "or")?.args).toEqual([
      buildLeadSearchOrFilter("serginho"),
    ]);
    expect(chamadas.find((c) => c.metodo === "limit")?.args).toEqual([30]);
    // Só o que o seletor precisa — nada de lead_tags/tags embutidos.
    const colunas = String(chamadas.find((c) => c.metodo === "select")?.args[0]);
    for (const c of ["id", "name", "phone", "email", "cnpj", "razao_social"]) {
      expect(colunas).toContain(c);
    }
    expect(colunas).not.toContain("lead_tags");
  });

  it("escopo preservado: nenhum recorte por canal ou conversa", async () => {
    const { chamadas } = instalar();
    await chamar("q=vida");
    expect(chamadas.some((c) => c.metodo === "in" || c.metodo === "eq" || c.metodo === "not")).toBe(false);
  });

  it("limite: padrão 30 e nunca acima de 30", async () => {
    let r = instalar();
    await chamar("q=vida");
    expect(r.chamadas.find((c) => c.metodo === "limit")?.args).toEqual([30]);

    r = instalar();
    await chamar("q=vida&limit=5000");
    expect(r.chamadas.find((c) => c.metodo === "limit")?.args).toEqual([30]);

    r = instalar();
    await chamar("q=vida&limit=10");
    expect(r.chamadas.find((c) => c.metodo === "limit")?.args).toEqual([10]);

    r = instalar();
    await chamar("q=vida&limit=abc");
    expect(r.chamadas.find((c) => c.metodo === "limit")?.args).toEqual([30]);
  });

  it("termo curto ou só pontuação devolve vazio sem ir ao banco", async () => {
    const { tabelas } = instalar([{ id: "x" }]);
    expect(await (await chamar("q=v")).json()).toEqual([]);
    expect(await (await chamar("q=%20%20")).json()).toEqual([]);
    expect(await (await chamar("q=..")).json()).toEqual([]);
    expect(tabelas).toEqual([]);
  });

  it("sem q, o GET continua o de antes (lista completa com tags, sem limite)", async () => {
    const { chamadas } = instalar();
    await chamar("");
    expect(String(chamadas.find((c) => c.metodo === "select")?.args[0])).toContain("lead_tags");
    expect(chamadas.some((c) => c.metodo === "limit" || c.metodo === "or")).toBe(false);
  });

  it("erro do banco vira 500, não lista vazia", async () => {
    const builder: Record<string, unknown> = {};
    for (const m of ["select", "or", "order", "limit"]) builder[m] = () => builder;
    builder.then = (ok: (r: unknown) => unknown) =>
      Promise.resolve({ data: null, error: { message: "boom" } }).then(ok);
    vi.mocked(getServiceSupabase).mockResolvedValue({ from: () => builder } as never);
    const res = await chamar("q=vida");
    expect(res.status).toBe(500);
  });
});
