import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));
vi.mock("@/lib/supabase/lead-blocked", () => ({
  isLeadBlocked: vi.fn(async () => false),
  MENSAGEM_LEAD_BLOQUEADO: "bloqueado",
}));

import { POST } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";

let CONV: { leads: Record<string, unknown> } & Record<string, unknown>;
const CONV_PADRAO = {
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

beforeEach(() => {
  CONV = { ...CONV_PADRAO };
});
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

// Carolaine/MVX (06/11/2026): número fixo, `phone` normalizado ganhou o 9º dígito, mas o
// endereço real na Meta (wa_id) não tem. Modelo é disparo FRIO: o wa_id só vale com
// procedência (wa_id_confirmed_at ou last_customer_message_at) — espelho do backend.
const CAROLAINE = {
  id: "lead-1",
  phone: "5537932140027",
  wa_id: "553732140027",
  wa_id_confirmed_at: "2026-09-23T14:29:31Z",
  last_customer_message_at: null,
  bsuid: null,
  opt_out: false,
};

function destinoMeta(): string {
  const chamadas = vi.mocked(global.fetch).mock.calls as unknown as [string, RequestInit][];
  const envio = chamadas.find(([url]) => String(url).endsWith("/messages"));
  expect(envio).toBeDefined();
  return JSON.parse(String(envio![1].body)).to;
}

describe("POST send-template — destino do envio", () => {
  it("wa_id com procedência: envia para o wa_id real", async () => {
    CONV = { ...CONV_PADRAO, leads: CAROLAINE };
    instalar();
    metaResponde({ messages: [{ id: "wamid.ABC" }] });
    const res = await chamar();
    expect(res.status).toBe(200);
    expect(destinoMeta()).toBe("553732140027");
  });

  it("wa_id sem procedência: ignora o wa_id e envia para o phone", async () => {
    CONV = { ...CONV_PADRAO, leads: { ...CAROLAINE, wa_id_confirmed_at: null, last_customer_message_at: null } };
    instalar();
    metaResponde({ messages: [{ id: "wamid.ABC" }] });
    const res = await chamar();
    expect(res.status).toBe(200);
    expect(destinoMeta()).toBe("5537932140027");
  });

  it("lead só com phone (legado): envia para o phone", async () => {
    instalar();
    metaResponde({ messages: [{ id: "wamid.ABC" }] });
    await chamar();
    expect(destinoMeta()).toBe("5534999999999");
  });
});
