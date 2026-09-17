import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("POST /api/bling/contacts/unlink", () => {
  it("repassa o account (do corpo) como query string para o backend", async () => {
    const chamadas: string[] = [];
    vi.stubGlobal("fetch", (url: string) => {
      chamadas.push(String(url));
      return Promise.resolve(new Response(JSON.stringify({ unlinked: true }), { status: 200 }));
    });

    await POST(
      new Request("http://x/api/bling/contacts/unlink", {
        method: "POST",
        body: JSON.stringify({ lead_id: "lead-1", account: "secundaria" }),
      }),
    );

    expect(chamadas[0]).toContain("account=secundaria");
    expect(chamadas[0]).toContain("lead_id=lead-1");
  });

  it("nao inventa account quando o chamador nao informa (backend usa o default)", async () => {
    const chamadas: string[] = [];
    vi.stubGlobal("fetch", (url: string) => {
      chamadas.push(String(url));
      return Promise.resolve(new Response(JSON.stringify({ unlinked: true }), { status: 200 }));
    });

    await POST(
      new Request("http://x/api/bling/contacts/unlink", {
        method: "POST",
        body: JSON.stringify({ lead_id: "lead-1" }),
      }),
    );

    expect(chamadas[0]).not.toContain("account=");
  });
});
