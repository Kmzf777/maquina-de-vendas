import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("POST /api/bling/contacts", () => {
  it("repassa o account (dentro do corpo) para o backend sem filtrar", async () => {
    const corpos: string[] = [];
    vi.stubGlobal("fetch", (_url: string, init?: RequestInit) => {
      corpos.push(String(init?.body));
      return Promise.resolve(new Response(JSON.stringify({ bling_contact_id: 1 }), { status: 200 }));
    });

    await POST(
      new Request("http://x/api/bling/contacts", {
        method: "POST",
        body: JSON.stringify({
          lead_id: "L1",
          nome: "Cliente",
          numeroDocumento: "1",
          account: "secundaria",
        }),
      }),
    );

    expect(corpos[0]).toContain('"account":"secundaria"');
  });
});
