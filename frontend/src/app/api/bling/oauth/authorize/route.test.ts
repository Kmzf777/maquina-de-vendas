import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/pipeline-access", () => ({
  getCurrentUser: vi.fn().mockResolvedValue({ role: "admin" }),
}));

import { GET } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GET /api/bling/oauth/authorize", () => {
  it("repassa o account para o backend", async () => {
    const chamadas: string[] = [];
    vi.stubGlobal("fetch", (url: string) => {
      chamadas.push(String(url));
      return Promise.resolve(
        new Response(JSON.stringify({ url: "https://bling.com.br/x" }), { status: 200 }),
      );
    });

    await GET(new Request("http://x/api/bling/oauth/authorize?account=secundaria"));

    expect(chamadas[0]).toContain("account=secundaria");
  });

  it("nao inventa account quando o chamador nao informa (backend usa o default)", async () => {
    const chamadas: string[] = [];
    vi.stubGlobal("fetch", (url: string) => {
      chamadas.push(String(url));
      return Promise.resolve(
        new Response(JSON.stringify({ url: "https://bling.com.br/x" }), { status: 200 }),
      );
    });

    await GET(new Request("http://x/api/bling/oauth/authorize"));

    expect(chamadas[0]).not.toContain("account=");
  });
});
