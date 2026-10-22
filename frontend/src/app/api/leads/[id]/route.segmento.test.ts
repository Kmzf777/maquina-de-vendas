/**
 * PATCH /api/leads/[id] com `segmento`/`stage` (cartão b67f1c6b): `segmento` validado
 * contra o enum, `stage` só aceita FASE (segmento em `stage`, de tela antiga, vira
 * `segmento` + `qualificando`; "secretaria" vira `triagem`). `stage_enter` leva só o que mudou.
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
      const r = respostas[idx];
      const resultado =
        r instanceof Error ? { data: null, error: { message: r.message } } : { data: r ?? null, error: null };
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

const ATUAL = { stage: "triagem", phone: "5534999990000", segmento: null };

function corpoDoTrigger(): Record<string, unknown>[] {
  const f = vi.mocked(fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>);
  return f.mock.calls
    .filter(([u]) => String(u).endsWith("/api/automation/trigger"))
    .map(([, init]) => JSON.parse(String(init?.body)));
}

describe("PATCH /api/leads/[id] — segmento e fase", () => {
  it("grava segmento normalizado e dispara stage_enter com o segmento", async () => {
    const chamadas = instalar([ATUAL, { id: "l2" }]);
    const res = await patch("l2", { segmento: "Private Label" });
    expect(res.status).toBe(200);
    expect(chamadas.find((c) => c.metodo === "update")?.args[0]).toEqual({ segmento: "private_label" });
    expect(corpoDoTrigger()).toEqual([
      { event_type: "stage_enter", lead_id: "l2", data: { segmento: "private_label" } },
    ]);
  });

  it("recusa segmento fora do enum com 400, sem update", async () => {
    const chamadas = instalar([ATUAL]);
    const res = await patch("l2", { segmento: "secretaria" });
    expect(res.status).toBe(400);
    expect(chamadas.some((c) => c.metodo === "update")).toBe(false);
  });

  it("stage aceita só fase", async () => {
    const chamadas = instalar([ATUAL]);
    const res = await patch("l2", { stage: "Em conversa" });
    expect(res.status).toBe(400);
    expect(chamadas.some((c) => c.metodo === "update")).toBe(false);
  });

  it("fase válida grava stage e registra stage_change", async () => {
    const chamadas = instalar([ATUAL, { id: "l2" }, null]);
    await patch("l2", { stage: "perdido" });
    expect(chamadas.find((c) => c.metodo === "update")?.args[0]).toEqual({ stage: "perdido" });
    expect(chamadas.find((c) => c.metodo === "insert")?.args[0]).toEqual([
      { lead_id: "l2", event_type: "stage_change", old_value: "triagem", new_value: "perdido" },
    ]);
    expect(corpoDoTrigger()).toEqual([
      { event_type: "stage_enter", lead_id: "l2", data: { stage: "perdido" } },
    ]);
  });

  it("tela antiga mandando segmento em stage: vira segmento + qualificando", async () => {
    const chamadas = instalar([ATUAL, { id: "l2" }, null]);
    await patch("l2", { stage: "atacado" });
    expect(chamadas.find((c) => c.metodo === "update")?.args[0]).toEqual({
      stage: "qualificando",
      segmento: "atacado",
    });
    expect(corpoDoTrigger()).toEqual([
      { event_type: "stage_enter", lead_id: "l2", data: { stage: "qualificando" } },
      { event_type: "stage_enter", lead_id: "l2", data: { segmento: "atacado" } },
    ]);
  });

  it("segmento igual ao atual não dispara gatilho", async () => {
    instalar([{ ...ATUAL, segmento: "consumo" }, { id: "l2" }]);
    await patch("l2", { segmento: "consumo" });
    expect(corpoDoTrigger()).toEqual([]);
  });
});
