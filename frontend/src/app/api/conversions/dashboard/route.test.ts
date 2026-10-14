import { beforeEach, describe, expect, it, vi } from "vitest";

const adminProxy = vi.fn();
vi.mock("@/app/api/valeria-flow/_shared", () => ({ adminProxy: (...a: unknown[]) => adminProxy(...a) }));

import { GET } from "./route";

describe("GET /api/conversions/dashboard", () => {
  beforeEach(() => {
    adminProxy.mockReset();
  });

  it("repassa pelo adminProxy (o backend exige o JWT de admin)", async () => {
    adminProxy.mockResolvedValue(Response.json({ kpis: {} }));
    const r = await GET();
    expect(adminProxy).toHaveBeenCalledWith("/api/conversions/dashboard");
    expect(await r.json()).toEqual({ kpis: {} });
  });

  it("devolve o status do proxy (sem admin → 401/403)", async () => {
    adminProxy.mockResolvedValue(Response.json({ error: "Não autenticado" }, { status: 401 }));
    expect((await GET()).status).toBe(401);
  });
});
