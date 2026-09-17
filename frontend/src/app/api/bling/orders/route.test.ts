import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("POST /api/bling/orders", () => {
  it("repassa o account (dentro do corpo) para o backend sem filtrar", async () => {
    const corpos: string[] = [];
    vi.stubGlobal("fetch", (_url: string, init?: RequestInit) => {
      corpos.push(String(init?.body));
      return Promise.resolve(
        new Response(JSON.stringify({ status: "created" }), { status: 201 }),
      );
    });

    await POST(
      new Request("http://x/api/bling/orders", {
        method: "POST",
        body: JSON.stringify({ lead_id: "L1", account: "secundaria" }),
      }),
    );

    expect(corpos[0]).toContain('"account":"secundaria"');
  });
});
