import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GET /api/bling/products", () => {
  it("repassa o account para o backend", async () => {
    const chamadas: string[] = [];
    vi.stubGlobal("fetch", (url: string) => {
      chamadas.push(String(url));
      return Promise.resolve(new Response(JSON.stringify({ data: [] }), { status: 200 }));
    });

    await GET(new Request("http://x/api/bling/products?account=secundaria"));

    expect(chamadas[0]).toContain("account=secundaria");
  });

  it("nao inventa account quando o chamador nao informa (backend usa o default)", async () => {
    const chamadas: string[] = [];
    vi.stubGlobal("fetch", (url: string) => {
      chamadas.push(String(url));
      return Promise.resolve(new Response(JSON.stringify({ data: [] }), { status: 200 }));
    });

    await GET(new Request("http://x/api/bling/products"));

    expect(chamadas[0]).not.toContain("account=");
  });
});
