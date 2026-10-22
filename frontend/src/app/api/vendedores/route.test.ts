import { afterEach, describe, expect, it, vi } from "vitest";

const chamadas: { metodo: string; args: unknown[] }[] = [];
let resultado: { data: unknown; error: { message: string } | null } = { data: [], error: null };

vi.mock("@/lib/supabase/api", () => ({
  getServiceSupabase: async () => {
    // Builder "thenable" (como o do supabase-js); o cliente em si não pode ser
    // thenable, senão o `await getServiceSupabase()` o resolveria.
    const q: Record<string, unknown> = {};
    for (const m of ["select", "eq", "order"]) {
      q[m] = (...args: unknown[]) => {
        chamadas.push({ metodo: m, args });
        return q;
      };
    }
    q.then = (ok: (v: unknown) => unknown) => Promise.resolve(resultado).then(ok);
    return {
      from: (...args: unknown[]) => {
        chamadas.push({ metodo: "from", args });
        return q;
      },
    };
  },
}));

import { GET } from "./route";

afterEach(() => {
  chamadas.length = 0;
  resultado = { data: [], error: null };
});

describe("GET /api/vendedores", () => {
  it("lista {id,nome,email,ativo} ordenado por nome", async () => {
    resultado = { data: [{ id: "u1", nome: "Arthur", email: "a@x.com", ativo: true }], error: null };
    const r = await GET(new Request("http://x/api/vendedores"));
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual([{ id: "u1", nome: "Arthur", email: "a@x.com", ativo: true }]);
    expect(chamadas.find((c) => c.metodo === "from")?.args).toEqual(["vendedores"]);
    expect(chamadas.find((c) => c.metodo === "order")?.args[0]).toBe("nome");
    expect(chamadas.some((c) => c.metodo === "eq")).toBe(false);
  });

  it("?ativos=1 filtra os ativos", async () => {
    await GET(new Request("http://x/api/vendedores?ativos=1"));
    expect(chamadas.find((c) => c.metodo === "eq")?.args).toEqual(["ativo", true]);
  });

  it("erro do banco vira 500", async () => {
    resultado = { data: null, error: { message: "boom" } };
    const r = await GET(new Request("http://x/api/vendedores"));
    expect(r.status).toBe(500);
  });
});
