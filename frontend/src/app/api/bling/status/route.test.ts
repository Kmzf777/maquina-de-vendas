import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CONTA_PADRAO } from "@/lib/bling-accounts";

// getCurrentUser depende de cookies/Supabase (createServerClient em
// pipeline-access.ts) — mockar o modulo inteiro evita puxar essa cadeia so
// para controlar o role, e isola exatamente o que este teste quer provar: o
// corte de payload por role, nao a resolucao de identidade em si.
const getCurrentUserMock = vi.fn();
vi.mock("@/lib/supabase/pipeline-access", () => ({
  getCurrentUser: () => getCurrentUserMock(),
}));

import { GET } from "./route";

const STATUS_COMPLETO = {
  enabled: true,
  connected: true,
  configured: true,
  access_expires_at: "2026-09-20T00:00:00Z",
  refresh_expires_at: "2026-10-13T00:00:00Z",
  scope: "read write",
  accounts: [
    { account: CONTA_PADRAO, label: "Canastra CNPJ 1", configured: true, connected: true },
    { account: "secundaria", label: "Canastra CNPJ 2", configured: true, connected: false },
  ],
};

describe("GET /api/bling/status — corte de payload por role", () => {
  beforeEach(() => {
    getCurrentUserMock.mockReset();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(STATUS_COMPLETO), { status: 200 })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("vendedor recebe accounts (4 campos por conta) mas nao recebe expiracao nem escopo", async () => {
    getCurrentUserMock.mockResolvedValue({ role: "vendedor" });
    const resp = await GET();
    const body = await resp.json();

    // A metade que ele PRECISA: sem isso o seletor de conta nao tem o que
    // renderizar e toda venda cai na conta padrao em silencio (ver Requisito 1).
    expect(body.accounts).toEqual([
      { account: CONTA_PADRAO, label: "Canastra CNPJ 1", configured: true, connected: true },
      { account: "secundaria", label: "Canastra CNPJ 2", configured: true, connected: false },
    ]);
    expect(body.enabled).toBe(true);
    expect(body.connected).toBe(true);

    // A metade que continua restrita: informacao de administracao do OAuth.
    expect(body).not.toHaveProperty("access_expires_at");
    expect(body).not.toHaveProperty("refresh_expires_at");
    expect(body).not.toHaveProperty("scope");
    expect(body).not.toHaveProperty("configured");
  });

  it("vendedor sem accounts no backend (formato antigo) recebe lista vazia, nao undefined", async () => {
    getCurrentUserMock.mockResolvedValue({ role: "vendedor" });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ enabled: true, connected: true }), { status: 200 })),
    );
    const resp = await GET();
    const body = await resp.json();
    expect(body.accounts).toEqual([]);
  });

  it("admin continua recebendo o payload completo, sem corte", async () => {
    getCurrentUserMock.mockResolvedValue({ role: "admin" });
    const resp = await GET();
    const body = await resp.json();
    expect(body).toEqual(STATUS_COMPLETO);
  });

  it("sem usuario autenticado devolve 401 antes de tocar no backend", async () => {
    getCurrentUserMock.mockRejectedValue(new Error("no session"));
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const resp = await GET();
    expect(resp.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
