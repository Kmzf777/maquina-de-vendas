import { afterEach, describe, expect, it, vi } from "vitest";

import { PUT } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PUT /api/bling/orders/[order_id]", () => {
  it("repassa o account (dentro do corpo) para o backend sem filtrar", async () => {
    const corpos: string[] = [];
    vi.stubGlobal("fetch", (_url: string, init?: RequestInit) => {
      corpos.push(String(init?.body));
      return Promise.resolve(
        new Response(JSON.stringify({ status: "updated" }), { status: 200 }),
      );
    });

    const req = new Request("http://x/api/bling/orders/123", {
      method: "PUT",
      body: JSON.stringify({ lead_id: "L1", account: "secundaria" }),
    });

    // O handler so chama req.json() e (await params) -- nao usa nextUrl --
    // entao um Request comum basta; o cast evita reescrever o tipo da rota
    // so para o teste.
    await PUT(req as never, { params: Promise.resolve({ order_id: "123" }) });

    expect(corpos[0]).toContain('"account":"secundaria"');
  });
});
