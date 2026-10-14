/**
 * POST /api/leads/resolve (disparo rápido): acha o lead do número em qualquer
 * formato antigo e só cria com o telefone canônico (cartão b747da43).
 * O `quick-send-modal` só lê `id` da resposta e trata `!ok` como erro.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { POST } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";

type Chamada = { from: number; metodo: string; args: unknown[] };
type Resultado = { data: unknown; error: unknown };

/** Builder encadeável por `from()`; resultados saem da fila na ordem dos `from()`. */
function instalar(respostas: Resultado[]) {
  const chamadas: Chamada[] = [];
  let n = 0;
  vi.mocked(getServiceSupabase).mockResolvedValue({
    from: () => {
      const idx = n++;
      const resultado = respostas[idx] ?? { data: null, error: null };
      const builder: Record<string, unknown> = {};
      for (const metodo of ["select", "in", "neq", "eq", "order", "limit", "insert"]) {
        builder[metodo] = (...args: unknown[]) => {
          chamadas.push({ from: idx, metodo, args });
          return builder;
        };
      }
      for (const metodo of ["single", "maybeSingle"]) {
        builder[metodo] = () => Promise.resolve(resultado);
      }
      builder.then = (ok: (r: unknown) => unknown) => Promise.resolve(resultado).then(ok);
      return builder;
    },
  } as never);
  return chamadas;
}

const ok = (data: unknown): Resultado => ({ data, error: null });
const resolver = (body: unknown) =>
  POST(new NextRequest("http://localhost/api/leads/resolve", { method: "POST", body: JSON.stringify(body) }));

afterEach(() => vi.clearAllMocks());

describe("POST /api/leads/resolve", () => {
  it("número gravado em formato antigo devolve o lead existente, sem criar", async () => {
    const chamadas = instalar([ok([{ id: "l1", name: "Douglas", phone: "4999170363" }])]);

    const res = await resolver({ phone: "5549999170363" });

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ id: "l1", created: false });
    expect(chamadas.find((c) => c.metodo === "in")?.args).toEqual([
      "phone",
      ["5549999170363", "554999170363", "49999170363", "4999170363"],
    ]);
    expect(chamadas.some((c) => c.metodo === "insert")).toBe(false);
  });

  it("número novo é criado com o telefone canônico", async () => {
    const chamadas = instalar([ok([]), ok({ id: "novo" })]);

    const res = await resolver({ phone: "(49) 9917-0363" });

    expect(res.status).toBe(201);
    expect(await res.json()).toEqual({ id: "novo", created: true });
    expect(chamadas.find((c) => c.metodo === "insert")?.args[0]).toMatchObject({
      phone: "5549999170363",
      status: "imported",
      stage: "pending",
    });
  });

  it("telefone que não normaliza devolve 422", async () => {
    const chamadas = instalar([]);
    const res = await resolver({ phone: "12345678" });
    expect(res.status).toBe(422);
    expect((await res.json()).error).toContain("Telefone inválido");
    expect(chamadas.length).toBe(0);
  });

  it("sem phone continua 400", async () => {
    instalar([]);
    expect((await resolver({})).status).toBe(400);
  });

  it("erro na busca devolve 500 sem criar", async () => {
    const chamadas = instalar([{ data: null, error: { message: "boom" } }]);
    const res = await resolver({ phone: "5549999170363" });
    expect(res.status).toBe(500);
    expect(chamadas.some((c) => c.metodo === "insert")).toBe(false);
  });
});
