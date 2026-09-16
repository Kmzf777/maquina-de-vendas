import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { GET } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GET /api/bling/catalog", () => {
  it("repassa o account para o backend", async () => {
    const chamadas: string[] = [];
    vi.stubGlobal("fetch", (url: string) => {
      chamadas.push(String(url));
      return Promise.resolve(new Response(JSON.stringify({ data: [], total: 0 }), { status: 200 }));
    });

    await GET(new NextRequest("http://x/api/bling/catalog?account=secundaria"));

    expect(chamadas[0]).toContain("account=secundaria");
  });

  it("nao inventa account quando o chamador nao informa (backend usa o default)", async () => {
    const chamadas: string[] = [];
    vi.stubGlobal("fetch", (url: string) => {
      chamadas.push(String(url));
      return Promise.resolve(new Response(JSON.stringify({ data: [], total: 0 }), { status: 200 }));
    });

    await GET(new NextRequest("http://x/api/bling/catalog"));

    expect(chamadas[0]).not.toContain("account=");
  });
});
