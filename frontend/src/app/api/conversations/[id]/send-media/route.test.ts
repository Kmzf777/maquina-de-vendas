import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));
vi.mock("@/lib/supabase/lead-blocked", () => ({
  isLeadBlocked: vi.fn(async () => false),
  MENSAGEM_LEAD_BLOQUEADO: "bloqueado",
}));

import { POST } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";

// Carolaine/MVX (06/11/2026): número fixo, `phone` normalizado ganhou o 9º dígito,
// mas o endereço real na Meta (wa_id) não tem. Enviar ao phone → 131026.
const CAROLAINE = {
  id: "lead-1",
  phone: "5537932140027",
  wa_id: "553732140027",
  wa_id_confirmed_at: "2026-09-23T14:29:31Z",
  last_customer_message_at: null,
  bsuid: null,
  opt_out: false,
};

function instalar(lead: Record<string, unknown>) {
  const conv = {
    id: "conv-1",
    stage: "secretaria",
    leads: lead,
    channels: {
      id: "ch-1",
      provider: "meta_cloud",
      provider_config: { phone_number_id: "pn", access_token: "tok" },
    },
  };
  const from = () => {
    const b: Record<string, unknown> = {};
    for (const m of ["select", "eq", "limit", "update", "order"]) b[m] = () => b;
    b.single = async () => ({ data: conv, error: null });
    b.maybeSingle = async () => ({ data: null, error: null });
    b.insert = () => Promise.resolve({ data: null, error: null });
    b.then = (ok: (r: unknown) => unknown) => Promise.resolve({ data: null, error: null }).then(ok);
    return b;
  };
  const storage = {
    from: () => ({
      upload: async () => ({ error: null }),
      getPublicUrl: () => ({ data: { publicUrl: "https://storage/x.png" } }),
    }),
  };
  vi.mocked(getServiceSupabase).mockResolvedValue({ from, storage } as never);
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ id: "media-1", messages: [{ id: "wamid.X" }] }),
    text: async () => "",
  })) as never;
}

/** Destinatário (`to`) do POST para a Graph API. */
function destinoMeta(): string {
  const chamadas = vi.mocked(global.fetch).mock.calls as unknown as [string, RequestInit][];
  const meta = chamadas.find(([url]) => String(url).includes("graph.facebook.com") && String(url).endsWith("/messages"));
  expect(meta).toBeDefined();
  return JSON.parse(String(meta![1].body)).to;
}

const chamar = () => {
  const form = new FormData();
  form.append("file", new File([new Uint8Array([1, 2, 3])], "foto.png", { type: "image/png" }));
  return POST(
    new NextRequest("http://localhost/api/conversations/conv-1/send-media", {
      method: "POST",
      body: form,
    }),
    { params: Promise.resolve({ id: "conv-1" }) },
  );
};

afterEach(() => vi.clearAllMocks());

describe("POST send-media — destino do envio Meta", () => {
  it("envia para o wa_id real, não para o phone com o 9 a mais", async () => {
    instalar(CAROLAINE);
    const res = await chamar();
    expect(res.status).toBe(200);
    expect(destinoMeta()).toBe("553732140027");
  });

  it("sem wa_id, envia para o phone", async () => {
    instalar({ ...CAROLAINE, wa_id: null });
    const res = await chamar();
    expect(res.status).toBe(200);
    expect(destinoMeta()).toBe("5537932140027");
  });
});
