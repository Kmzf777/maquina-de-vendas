/**
 * Task 8 fecha a "porta dos fundos" que a validação de ativação (12 regras — campos
 * obrigatórios do registro de nós, integridade de grafo, canal, template aprovado com o
 * status real da Meta — agora concentradas em `backend/app/campaigns/router.py`) ganharia
 * se algum outro caminho no Next continuasse escrevendo `status` sem passar por ela.
 *
 * Não havia precedente de teste para `route.ts` no repositório (nenhum arquivo sob
 * `frontend/src/app/api` tinha teste até aqui) — este arquivo segue o estilo dos testes
 * de componente existentes que já mockam `fetch` (ex.: `esteiras-tab.test.tsx`):
 * `global.fetch = vi.fn(...)`, um helper `resposta()`, comentários em português
 * explicando o porquê de cada caso.
 *
 * Dois contratos, um arquivo só (é o único arquivo de teste que esta task pode criar):
 *
 * 1. POST /api/campaigns/[id]/activate — virou proxy puro para
 *    `POST /api/campaigns/{id}/activate` no FastAPI (mesma resolução de FASTAPI_URL e
 *    mesmo tratamento de falha de rede de `automation/esteiras/route.ts`). Repassa status
 *    e corpo do upstream sem tradução — em especial o 400 com `detail.problemas[]`
 *    (cada item com `no_id`/`codigo`/`mensagem`), que a tela usa pra destacar o nó
 *    culpado no canvas.
 *
 * 2. PATCH /api/campaigns/[id] — fazia `.update({ ...body })` (spread cego). Um
 *    `{ status: "active" }` nesse PATCH contornava toda a validação que o /activate
 *    acima acabou de ganhar — a porta dos fundos. `status` no corpo agora é 400 antes
 *    de qualquer escrita no Supabase.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as activatePOST } from "../[id]/activate/route";
import { PATCH } from "../[id]/route";
import { getServiceSupabase } from "@/lib/supabase/api";

vi.mock("@/lib/supabase/api", () => ({
  getServiceSupabase: vi.fn(),
}));

type Corpo = Record<string, unknown>;

const resposta = (corpo: Corpo, status = 200) =>
  ({ ok: status < 400, status, json: async () => corpo }) as Response;

afterEach(() => {
  vi.restoreAllMocks();
});

describe("POST /api/campaigns/[id]/activate (proxy para o FastAPI)", () => {
  function chamar(id: string) {
    const req = new NextRequest(`http://localhost/api/campaigns/${id}/activate`, {
      method: "POST",
    });
    return activatePOST(req, { params: Promise.resolve({ id }) });
  }

  it("encaminha para o FastAPI com método POST e o id na URL", async () => {
    global.fetch = vi.fn(async () => resposta({ status: "active" })) as unknown as typeof fetch;

    await chamar("camp-1");

    const chamada = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(chamada[0])).toContain("/api/campaigns/camp-1/activate");
    expect((chamada[1] as RequestInit | undefined)?.method).toBe("POST");
  });

  it("repassa o status 400 do upstream — um proxy que devolve 200 destrói a trava", async () => {
    global.fetch = vi.fn(async () =>
      resposta(
        { detail: { problemas: [{ no_id: "n1", codigo: "sem_template", mensagem: "Nó sem template" }] } },
        400,
      ),
    ) as unknown as typeof fetch;

    const res = await chamar("camp-1");

    expect(res.status).toBe(400);
  });

  it("repassa o corpo intacto, incluindo detail.problemas[] com no_id/codigo/mensagem", async () => {
    const corpo = {
      detail: {
        problemas: [
          { no_id: "no-42", codigo: "canal_ausente", mensagem: "Nó sem canal configurado" },
          { no_id: "no-43", codigo: "template_nao_aprovado", mensagem: "Template ainda em análise na Meta" },
        ],
      },
    };
    global.fetch = vi.fn(async () => resposta(corpo, 400)) as unknown as typeof fetch;

    const res = await chamar("camp-1");

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual(corpo);
  });

  it("repassa sucesso (200) sem alterar o corpo", async () => {
    global.fetch = vi.fn(async () => resposta({ status: "active" }, 200)) as unknown as typeof fetch;

    const res = await chamar("camp-1");

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "active" });
  });

  it("falha de rede com o FastAPI devolve JSON que a tela sabe mostrar, não a página de erro do Next", async () => {
    global.fetch = vi.fn(async () => {
      throw new Error("fetch failed");
    }) as unknown as typeof fetch;

    const res = await chamar("camp-1");
    const json = await res.json().catch(() => null);

    expect(res.status).toBeGreaterThanOrEqual(500);
    expect(json).not.toBeNull();
    expect(typeof (json as Corpo).error).toBe("string");
  });
});

describe("PATCH /api/campaigns/[id] — rejeita status antes de qualquer escrita (porta dos fundos)", () => {
  function chamar(id: string, body: Corpo) {
    const req = new NextRequest(`http://localhost/api/campaigns/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    });
    return PATCH(req, { params: Promise.resolve({ id }) });
  }

  it("corpo com status → 400, sem tocar o Supabase", async () => {
    const res = await chamar("camp-1", { status: "active" });

    expect(res.status).toBe(400);
    const json = await res.json();
    expect(json.error).toMatch(/activate/);
    expect(json.error).toMatch(/pause/);
    expect(getServiceSupabase).not.toHaveBeenCalled();
  });

  it("status misturado com campos válidos → 400 do mesmo jeito (não é só payload puro-status)", async () => {
    const res = await chamar("camp-1", { status: "paused", audience: "ia" });

    expect(res.status).toBe(400);
    expect(getServiceSupabase).not.toHaveBeenCalled();
  });

  it("sem status → validações antigas continuam valendo (audience inválido ainda é 400)", async () => {
    const res = await chamar("camp-1", { audience: "invalido" });

    expect(res.status).toBe(400);
  });

  it("sem status → grava normalmente no Supabase (comportamento atual preservado)", async () => {
    const single = vi.fn(async () => ({ data: { id: "camp-1", audience: "ia" }, error: null }));
    const select = vi.fn(() => ({ single }));
    const eq = vi.fn(() => ({ select }));
    const update = vi.fn(() => ({ eq }));
    const from = vi.fn(() => ({ update }));
    vi.mocked(getServiceSupabase).mockResolvedValue({ from } as unknown as Awaited<
      ReturnType<typeof getServiceSupabase>
    >);

    const res = await chamar("camp-1", { audience: "ia" });

    expect(from).toHaveBeenCalledWith("campaigns");
    expect(update).toHaveBeenCalledWith(expect.objectContaining({ audience: "ia" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ id: "camp-1", audience: "ia" });
  });
});
