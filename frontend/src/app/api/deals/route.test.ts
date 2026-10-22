import { afterEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";

// Supabase falso: só o necessário para o POST chegar ao insert.
const inserts: Record<string, unknown>[] = [];
let erroInsert: { code: string; message: string } | null = null;

function encadeavel(final: () => unknown) {
  const q: Record<string, unknown> = {};
  for (const m of ["select", "eq", "order", "limit", "in"]) q[m] = () => q;
  q.maybeSingle = async () => ({ data: { id: "stage-1" }, error: null });
  q.single = async () => final();
  q.insert = (row: Record<string, unknown>) => {
    inserts.push(row);
    return q;
  };
  return q;
}

vi.mock("@/lib/supabase/api", () => ({
  getServiceSupabase: async () => ({
    from: () => encadeavel(() => (erroInsert ? { data: null, error: erroInsert } : { data: { id: "deal-1" }, error: null })),
  }),
}));
vi.mock("@/lib/supabase/pipeline-access", () => ({
  assertCanWriteDealsInPipeline: async () => ({ ok: true }),
  getAllowedPipelineIds: async () => null,
}));

import { POST } from "./route";

const ID = "3f6c2b1a-9d4e-4c7a-8b2f-1a2b3c4d5e6f";
const req = (body: Record<string, unknown>) =>
  new Request("http://x/api/deals", { method: "POST", body: JSON.stringify(body) }) as unknown as NextRequest;
const base = { pipeline_id: "p-1", lead_id: "l-1", title: "Deal" };

afterEach(() => {
  inserts.length = 0;
  erroInsert = null;
});

describe("POST /api/deals — assigned_to é id de vendedor", () => {
  it("recusa nome digitado com 400 e não grava", async () => {
    const r = await POST(req({ ...base, assigned_to: "João Brás" }));
    expect(r.status).toBe(400);
    expect(inserts).toHaveLength(0);
  });

  it("grava o uuid escolhido na lista", async () => {
    const r = await POST(req({ ...base, assigned_to: ID }));
    expect(r.status).toBe(201);
    expect(inserts[0].assigned_to).toBe(ID);
  });

  it("vazio grava null", async () => {
    await POST(req({ ...base, assigned_to: "" }));
    expect(inserts[0].assigned_to).toBeNull();
  });

  it("uuid fora de vendedores (FK) vira 400 legível", async () => {
    erroInsert = { code: "23503", message: "violates foreign key constraint" };
    const r = await POST(req({ ...base, assigned_to: ID }));
    expect(r.status).toBe(400);
    expect((await r.json()).error).toBe("Vendedor não cadastrado.");
  });
});
