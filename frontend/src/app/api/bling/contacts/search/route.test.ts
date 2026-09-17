import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { GET } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GET /api/bling/contacts/search", () => {
  it("repassa o account para o backend", async () => {
    const chamadas: string[] = [];
    vi.stubGlobal("fetch", (url: string) => {
      chamadas.push(String(url));
      return Promise.resolve(new Response(JSON.stringify({ data: [] }), { status: 200 }));
    });

    await GET(new NextRequest("http://x/api/bling/contacts/search?q=empresa&account=secundaria"));

    expect(chamadas[0]).toContain("account=secundaria");
  });

  it("nao inventa account quando o chamador nao informa (backend usa o default)", async () => {
    const chamadas: string[] = [];
    vi.stubGlobal("fetch", (url: string) => {
      chamadas.push(String(url));
      return Promise.resolve(new Response(JSON.stringify({ data: [] }), { status: 200 }));
    });

    await GET(new NextRequest("http://x/api/bling/contacts/search?q=empresa"));

    expect(chamadas[0]).not.toContain("account=");
  });
});
