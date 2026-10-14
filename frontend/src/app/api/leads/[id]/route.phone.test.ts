/**
 * PATCH /api/leads/[id] com `phone`: normaliza (`normalizePhoneBR`) e recusa
 * número que outro lead já usa em qualquer formato antigo (cartão b747da43).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { PATCH } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";

type Chamada = { from: number; metodo: string; args: unknown[] };

/** Builder encadeável por `from()`; resultados saem da fila na ordem dos `from()`. */
function instalar(respostas: unknown[]) {
  const chamadas: Chamada[] = [];
  let n = 0;
  vi.mocked(getServiceSupabase).mockResolvedValue({
    from: () => {
      const idx = n++;
      const resultado = { data: respostas[idx] ?? null, error: null };
      const builder: Record<string, unknown> = {};
      for (const metodo of ["select", "in", "neq", "eq", "order", "limit", "insert", "update"]) {
        builder[metodo] = (...args: unknown[]) => {
          chamadas.push({ from: idx, metodo, args });
          return builder;
        };
      }
      for (const metodo of ["single", "maybeSingle"]) {
        builder[metodo] = () => {
          chamadas.push({ from: idx, metodo, args: [] });
          return Promise.resolve(resultado);
        };
      }
      builder.then = (ok: (r: unknown) => unknown) => Promise.resolve(resultado).then(ok);
      return builder;
    },
  } as never);
  return chamadas;
}

const patch = (id: string, body: unknown) =>
  PATCH(
    new NextRequest(`http://localhost/api/leads/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),
    { params: Promise.resolve({ id }) },
  );

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}")));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("PATCH /api/leads/[id] — telefone", () => {
  it("número que outro lead já usa devolve 409 com esse lead, sem update", async () => {
    const outro = { id: "l9", name: "Fulano", phone: "553183016991" };
    const chamadas = instalar([[outro]]);

    const res = await patch("l2", { phone: "3183016991" });

    expect(res.status).toBe(409);
    const json = await res.json();
    expect(json.lead.id).toBe("l9");
    expect(json.error).toContain("Fulano");
    expect(chamadas.some((c) => c.metodo === "update")).toBe(false);
  });

  it("sem conflito grava o telefone canônico", async () => {
    const chamadas = instalar([[], { stage: "secretaria" }, { id: "l2" }]);

    const res = await patch("l2", { phone: "3183016991" });

    expect(res.status).toBe(200);
    expect(chamadas.find((c) => c.metodo === "update")?.args[0]).toMatchObject({
      phone: "5531983016991",
    });
  });

  it("a busca de conflito ignora o próprio lead e procura todas as formas", async () => {
    const chamadas = instalar([[], { stage: "secretaria" }, { id: "l2" }]);

    await patch("l2", { phone: "3183016991" });

    const busca = chamadas.filter((c) => c.from === 0);
    expect(busca.find((c) => c.metodo === "neq")?.args).toEqual(["id", "l2"]);
    expect(busca.find((c) => c.metodo === "in")?.args).toEqual([
      "phone",
      ["5531983016991", "553183016991", "31983016991", "3183016991"],
    ]);
  });

  it("telefone que não normaliza devolve 422", async () => {
    const chamadas = instalar([]);

    const res = await patch("l2", { phone: "12" });

    expect(res.status).toBe(422);
    expect((await res.json()).error).toContain("Telefone inválido");
    expect(chamadas.some((c) => c.metodo === "update")).toBe(false);
  });
});
