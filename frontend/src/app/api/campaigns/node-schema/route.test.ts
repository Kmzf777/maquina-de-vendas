/**
 * O proxy do contrato dos nós.
 *
 * Sem esta rota, `fetch("/api/campaigns/node-schema")` do builder cairia em
 * `campaigns/[id]/route.ts` com `id="node-schema"`, o Supabase recusaria o uuid e a
 * tela ficaria PARA SEMPRE no estado degradado — a única pista seria um 404 no
 * console. A rota estática existir É o teste que importa; o resto é garantir que ela
 * não inventa nada em cima da resposta do FastAPI.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

const resposta = (corpo: unknown, status = 200) =>
  ({ ok: status < 400, status, json: async () => corpo }) as Response;

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GET /api/campaigns/node-schema", () => {
  it("encaminha para o FastAPI e repassa o corpo intacto", async () => {
    const contrato = {
      tipos: [{ tipo: "trigger", subtipo: "stage_stagnation", campos: [] }],
      valores_fixos: { segmento_lead: [["atacado", "Atacado"]] },
    };
    const fetchMock = vi.fn().mockResolvedValue(resposta(contrato));
    vi.stubGlobal("fetch", fetchMock);

    const res = await GET();

    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/campaigns\/node-schema$/);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(contrato);
  });

  it("backend fora do ar vira 502 em JSON — a tela degrada, não quebra", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
    const res = await GET();
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "Backend indisponível" });
  });

  it("status de erro do upstream é repassado, não traduzido para 200", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resposta({ detail: "boom" }, 500)));
    const res = await GET();
    expect(res.status).toBe(500);
  });
});
