/**
 * Frente F1 (06/11/2026): os proxies do /trafego repassam o JWT do admin (adminProxy) e abrem
 * a visão do período quando o link não traz ?mode=.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const adminProxy = vi.fn();
vi.mock("@/app/api/valeria-flow/_shared", () => ({ adminProxy: (...a: unknown[]) => adminProxy(...a) }));

import { GET as report } from "./report/route";
import { GET as leads } from "./leads/route";
import { GET as campaign } from "./campaign/route";
import { POST as sync } from "./sync/route";
import { GET as syncStatus } from "./sync-status/route";

beforeEach(() => {
  adminProxy.mockReset();
  adminProxy.mockResolvedValue(Response.json({ ok: true }));
});

describe("proxies do /trafego", () => {
  it("report sem ?mode= pede a visão do período", async () => {
    await report(new Request("http://x/api/traffic/report"));
    expect(adminProxy).toHaveBeenCalledWith("/api/traffic/report?period=30d&mode=periodo");
  });

  it("report respeita mode=lead e as datas", async () => {
    await report(new Request("http://x/api/traffic/report?mode=lead&date_from=2026-10-15&date_to=2026-10-21"));
    expect(adminProxy).toHaveBeenCalledWith(
      "/api/traffic/report?period=30d&mode=lead&date_from=2026-10-15&date_to=2026-10-21",
    );
  });

  it("leads e campaign sem ?mode= pedem a visão do período", async () => {
    await leads(new Request("http://x/api/traffic/leads?channel=Meta%20Ads&campaign=Atacado"));
    expect(adminProxy).toHaveBeenLastCalledWith("/api/traffic/leads?channel=Meta+Ads&campaign=Atacado&period=30d&mode=periodo");
    await campaign(new Request("http://x/api/traffic/campaign?channel=Google%20Ads&campaign=PMAX&period=7d"));
    expect(adminProxy).toHaveBeenLastCalledWith("/api/traffic/campaign?channel=Google+Ads&campaign=PMAX&period=7d&mode=periodo");
  });

  it("sync e sync-status passam pelo adminProxy", async () => {
    await sync();
    expect(adminProxy).toHaveBeenLastCalledWith("/api/traffic/sync-ads", { method: "POST" });
    await syncStatus();
    expect(adminProxy).toHaveBeenLastCalledWith("/api/traffic/sync-status");
  });

  it("devolve o status do backend (401 sem login)", async () => {
    adminProxy.mockResolvedValue(Response.json({ error: "Não autenticado" }, { status: 401 }));
    const r = await leads(new Request("http://x/api/traffic/leads?channel=a&campaign=b"));
    expect(r.status).toBe(401);
  });
});
