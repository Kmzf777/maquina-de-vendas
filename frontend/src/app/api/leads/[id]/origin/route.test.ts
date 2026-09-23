import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/pipeline-access", () => ({ getCurrentUser: vi.fn() }));
vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { GET } from "./route";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import { getServiceSupabase } from "@/lib/supabase/api";

type Result = { data: unknown; error: { message: string } | null };

/** Fake mínimo do query builder: cada tabela devolve um Result fixo. */
function fakeSupabase(tables: Record<string, Result>) {
  return {
    from(table: string) {
      const result = tables[table] ?? { data: null, error: null };
      const builder: Record<string, unknown> = {};
      for (const m of ["select", "eq", "in", "order", "limit", "lte"]) builder[m] = () => builder;
      builder.maybeSingle = async () => result;
      builder.then = (resolve: (r: Result) => unknown) => Promise.resolve(result).then(resolve);
      return builder;
    },
  };
}

const call = (id = "lead-1") =>
  GET(new Request(`http://localhost/api/leads/${id}/origin`) as never, { params: Promise.resolve({ id }) });

const leadRow = (p: Record<string, unknown>) => ({
  traffic_type: null, utm_source: null, utm_medium: null, utm_campaign: null, gclid: null,
  fbclid: null, ctwa_clid: null, meta_ad_id: null, channel: null, metadata: null, ...p,
});

describe("GET /api/leads/[id]/origin", () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockResolvedValue({ userId: "u1", role: "vendedor" } as never);
  });

  it("401 sem sessão", async () => {
    vi.mocked(getCurrentUser).mockRejectedValueOnce(new Error("no session"));
    expect((await call()).status).toBe(401);
  });

  it("404 lead inexistente", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(fakeSupabase({ leads: { data: null, error: null } }) as never);
    expect((await call()).status).toBe(404);
  });

  it("Meta: resolve nome da campanha pelo meta_ad_id", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(fakeSupabase({
      leads: { data: leadRow({ meta_ad_id: "ad-9", channel: "whatsapp" }), error: null },
      meta_ad_campaigns: { data: { campaign_name: "CTWA Atacado" }, error: null },
    }) as never);
    const res = await call();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ kind: "pago", channel: "Meta Ads", detail: "CTWA Atacado", page: null });
  });

  it("Meta: falha no lookup não derruba — Campanha não identificada", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(fakeSupabase({
      leads: { data: leadRow({ meta_ad_id: "ad-9" }), error: null },
      meta_ad_campaigns: { data: null, error: { message: "boom" } },
    }) as never);
    const res = await call();
    expect(res.status).toBe(200);
    expect((await res.json()).detail).toBe("Campanha não identificada");
  });

  it("Google: resolve pelo ad_spend", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(fakeSupabase({
      leads: { data: leadRow({ gclid: "g", utm_campaign: "marca_propria" }), error: null },
      ad_spend: { data: [{ campaign_name: "Search | Marca Própria" }, { campaign_name: "PMAX | Atacado" }], error: null },
    }) as never);
    expect((await (await call()).json()).detail).toBe("Search | Marca Própria");
  });

  it("500 se a leitura do lead falhar", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(fakeSupabase({ leads: { data: null, error: { message: "db" } } }) as never);
    expect((await call()).status).toBe(500);
  });
});
