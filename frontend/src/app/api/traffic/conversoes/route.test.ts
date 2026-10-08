import { beforeEach, describe, expect, it, vi } from "vitest";

const adminProxy = vi.fn();
vi.mock("@/app/api/valeria-flow/_shared", () => ({ adminProxy: (...a: unknown[]) => adminProxy(...a) }));

import { GET } from "./route";

describe("GET /api/traffic/conversoes", () => {
  beforeEach(() => {
    adminProxy.mockReset();
    adminProxy.mockResolvedValue(Response.json({ rows: [], counts: [], truncated: false }));
  });

  it("repassa pelo adminProxy (JWT de admin) só os filtros conhecidos", async () => {
    await GET(new Request("http://x/api/traffic/conversoes?period=7d&platform=meta&stage=&evil=1"));
    expect(adminProxy).toHaveBeenCalledWith("/api/conversions/ads?period=7d&platform=meta");
  });

  it("sem filtros chama o endpoint sem querystring e devolve a resposta do proxy", async () => {
    adminProxy.mockResolvedValue(Response.json({ error: "Não autenticado" }, { status: 401 }));
    const r = await GET(new Request("http://x/api/traffic/conversoes"));
    expect(adminProxy).toHaveBeenCalledWith("/api/conversions/ads");
    expect(r.status).toBe(401);
  });

  it("codifica as datas", async () => {
    await GET(new Request("http://x/api/traffic/conversoes?date_from=2026-10-01&date_to=2026-10-07"));
    expect(adminProxy).toHaveBeenCalledWith("/api/conversions/ads?date_from=2026-10-01&date_to=2026-10-07");
  });
});
