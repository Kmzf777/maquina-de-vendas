import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));
vi.mock("@/lib/supabase/lead-blocked", () => ({
  isLeadBlocked: vi.fn(async () => false),
  MENSAGEM_LEAD_BLOQUEADO: "bloqueado",
}));

import { POST } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";

const CONV = {
  id: "conv-1",
  stage: "secretaria",
  leads: { id: "lead-1", phone: "5534999999999", opt_out: false },
  channels: {
    id: "ch-1",
    provider: "meta_cloud",
    provider_config: { phone_number_id: "pn", access_token: "tok", waba_id: "waba" },
  },
};

/** Supabase falso: devolve a conversa e guarda o que foi inserido em `messages`. */
function instalar() {
  const inseridos: Record<string, unknown>[] = [];
  const from = (tabela: string) => {
    const b: Record<string, unknown> = {};
    for (const m of ["select", "eq", "limit", "update"]) b[m] = () => b;
    b.single = async () => ({ data: CONV, error: null });
    b.maybeSingle = async () => ({ data: null, error: null });
    b.insert = (row: Record<string, unknown>) => {
      if (tabela === "messages") inseridos.push(row);
      return Promise.resolve({ data: null, error: null });
    };
    b.then = (ok: (r: unknown) => unknown) => Promise.resolve({ data: null, error: null }).then(ok);
    return b;
  };
  vi.mocked(getServiceSupabase).mockResolvedValue({ from } as never);
  return inseridos;
}

function metaResponde(corpo: unknown) {
  global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => corpo, text: async () => "" })) as never;
}

const chamar = () =>
  POST(
    new NextRequest("http://localhost/api/conversations/conv-1/send-template", {
      method: "POST",
      body: JSON.stringify({ template_name: "retomada", template_body: "Oi, tudo bem?" }),
    }),
    { params: Promise.resolve({ id: "conv-1" }) },
  );

afterEach(() => vi.clearAllMocks());

describe("POST send-template — mensagem gravada", () => {
  it("grava como envio do vendedor (seller), marcado como template, com wamid aceito", async () => {
    const inseridos = instalar();
    metaResponde({ messages: [{ id: "wamid.ABC" }] });
    const res = await chamar();
    expect(res.status).toBe(200);
    expect(inseridos).toHaveLength(1);
    expect(inseridos[0]).toMatchObject({
      lead_id: "lead-1",
      conversation_id: "conv-1",
      role: "assistant",
      content: "Oi, tudo bem?",
      sent_by: "seller",
      metadata: { template: true, template_name: "retomada" },
      wamid: "wamid.ABC",
      delivery_status: "accepted",
    });
  });

  it("sem wamid na resposta da Meta, não inventa wamid nem delivery_status", async () => {
    const inseridos = instalar();
    metaResponde({});
    await chamar();
    expect(inseridos[0].sent_by).toBe("seller");
    expect(inseridos[0]).not.toHaveProperty("wamid");
    expect(inseridos[0]).not.toHaveProperty("delivery_status");
  });
});
