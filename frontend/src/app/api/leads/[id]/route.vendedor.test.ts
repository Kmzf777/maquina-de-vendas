/**
 * PATCH /api/leads/[id] com `assigned_to` (cartão b67f1c6b): só o uuid de um vendedor
 * (`public.vendedores`) ou vazio/null. Nome digitado vira 400 legível, sem update;
 * uuid que não está em `vendedores` (FK 23503) também vira 400.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { PATCH } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";

type Chamada = { from: number; metodo: string; args: unknown[] };
type Resposta = { data: unknown; error: { message: string; code?: string } | null };

function instalar(respostas: Resposta[]) {
  const chamadas: Chamada[] = [];
  let n = 0;
  vi.mocked(getServiceSupabase).mockResolvedValue({
    from: () => {
      const idx = n++;
      const resultado = respostas[idx] ?? { data: null, error: null };
      const builder: Record<string, unknown> = {};
      for (const metodo of ["select", "in", "neq", "eq", "order", "limit", "insert", "update"]) {
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

const patch = (body: unknown) =>
  PATCH(
    new NextRequest("http://localhost/api/leads/l1", {
      method: "PATCH",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),
    { params: Promise.resolve({ id: "l1" }) },
  );

const ATUAL: Resposta = { data: { stage: "triagem", phone: "5534999990000", segmento: null }, error: null };
const OK: Resposta = { data: { id: "l1" }, error: null };
const UUID = "0F8FAD5B-D9CB-469F-A165-70867728950E";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}")));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("PATCH /api/leads/[id] — assigned_to", () => {
  it("recusa nome digitado com 400, sem update", async () => {
    const chamadas = instalar([ATUAL]);
    const res = await patch({ assigned_to: "João Brás" });
    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/vendedor/);
    expect(chamadas.some((c) => c.metodo === "update")).toBe(false);
  });

  it("recusa tipo que não é texto", async () => {
    const chamadas = instalar([ATUAL]);
    const res = await patch({ assigned_to: 42 });
    expect(res.status).toBe(400);
    expect(chamadas.some((c) => c.metodo === "update")).toBe(false);
  });

  it("grava o uuid normalizado", async () => {
    const chamadas = instalar([ATUAL, OK]);
    const res = await patch({ assigned_to: UUID });
    expect(res.status).toBe(200);
    expect(chamadas.find((c) => c.metodo === "update")?.args[0]).toEqual({ assigned_to: UUID.toLowerCase() });
  });

  it("vazio ou null desatribui", async () => {
    for (const v of ["", null]) {
      const chamadas = instalar([ATUAL, OK]);
      const res = await patch({ assigned_to: v });
      expect(res.status).toBe(200);
      expect(chamadas.find((c) => c.metodo === "update")?.args[0]).toEqual({ assigned_to: null });
    }
  });

  it("uuid fora de vendedores (FK) vira 400", async () => {
    instalar([ATUAL, { data: null, error: { message: "fk", code: "23503" } }]);
    const res = await patch({ assigned_to: UUID });
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe("Vendedor não cadastrado.");
  });

  it("sem assigned_to no corpo não mexe no campo", async () => {
    const chamadas = instalar([ATUAL, OK]);
    await patch({ name: "Ana" });
    expect(chamadas.find((c) => c.metodo === "update")?.args[0]).toEqual({ name: "Ana" });
  });
});
