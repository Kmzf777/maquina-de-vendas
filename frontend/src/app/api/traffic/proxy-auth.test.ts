/**
 * Frente F1: o proxy do relatório repassa o access_token do admin no Authorization (o backend
 * exige `exigir_admin`) e responde 401/403 sem chamar o backend quando não há admin logado.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const requireAdmin = vi.fn();
const getSession = vi.fn();
vi.mock("@/lib/admin-auth", () => ({ requireAdmin: () => requireAdmin() }));
vi.mock("@/lib/supabase/server", () => ({
  createClient: async () => ({ auth: { getSession: () => getSession() } }),
}));

import { GET } from "./leads/route";

const fetchMock = vi.fn();

beforeEach(() => {
  requireAdmin.mockReset();
  getSession.mockReset();
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(Response.json({ leads: [] }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("proxy /api/traffic/leads", () => {
  it("repassa o JWT do admin no Authorization", async () => {
    requireAdmin.mockResolvedValue({ ok: true });
    getSession.mockResolvedValue({ data: { session: { access_token: "tok-admin" } } });
    const r = await GET(new Request("http://x/api/traffic/leads?channel=a&campaign=b"));
    expect(r.status).toBe(200);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/traffic/leads?channel=a&campaign=b&period=30d&mode=periodo");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-admin");
    expect(String(url)).not.toContain("tok-admin");
  });

  it("sem admin não chama o backend", async () => {
    requireAdmin.mockResolvedValue({ ok: false, status: 403, error: "forbidden" });
    const r = await GET(new Request("http://x/api/traffic/leads?channel=a&campaign=b"));
    expect(r.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sem sessão responde 401", async () => {
    requireAdmin.mockResolvedValue({ ok: true });
    getSession.mockResolvedValue({ data: { session: null } });
    const r = await GET(new Request("http://x/api/traffic/leads?channel=a&campaign=b"));
    expect(r.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
