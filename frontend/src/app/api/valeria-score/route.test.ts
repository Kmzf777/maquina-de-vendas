import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/pipeline-access", () => ({
  getCurrentUser: vi.fn().mockRejectedValue(new Error("no session")),
}));
vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { GET } from "./route";
import { PUT } from "./[leadId]/feeling/route";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import { getServiceSupabase } from "@/lib/supabase/api";

type Chamada = { tabela: string; metodo: string; args: unknown[] };

/** Cliente Supabase falso: registra a cadeia de chamadas e devolve `respostas[tabela]`. */
function clienteFalso(respostas: Record<string, { data: unknown; error: unknown }>) {
  const chamadas: Chamada[] = [];
  const client = {
    from(tabela: string) {
      const resposta = respostas[tabela] ?? { data: null, error: null };
      const chain: Record<string, unknown> = {};
      for (const metodo of ["select", "eq", "upsert", "in", "order", "range"]) {
        chain[metodo] = (...args: unknown[]) => {
          chamadas.push({ tabela, metodo, args });
          return chain;
        };
      }
      chain.maybeSingle = async () => resposta;
      chain.single = async () => resposta;
      return chain;
    },
  };
  return { client, chamadas };
}

function putFeeling() {
  return PUT(
    new Request("http://localhost/api/valeria-score/lead-1/feeling", { method: "PUT", body: JSON.stringify({ feeling: "alto", justification: "Cotação solicitada" }) }) as never,
    { params: Promise.resolve({ leadId: "lead-1" }) },
  );
}

describe("Valeria Score routes", () => {
  it("rejects an unauthenticated score-directory request before using the service client", async () => {
    const response = await GET(new Request("http://localhost/api/valeria-score?page=2") as never);
    expect(response.status).toBe(401);
  });

  it("rejects an unauthenticated Feeling update", async () => {
    const response = await PUT(
      new Request("http://localhost/api/valeria-score/lead-1/feeling", { method: "PUT", body: JSON.stringify({ feeling: "alto", justification: "Cotação solicitada" }) }) as never,
      { params: Promise.resolve({ leadId: "lead-1" }) },
    );
    expect(response.status).toBe(401);
  });

  it("allows only vendedores to save Feeling", async () => {
    vi.mocked(getCurrentUser).mockResolvedValueOnce({ userId: "admin-1", role: "admin" });
    const response = await PUT(
      new Request("http://localhost/api/valeria-score/lead-1/feeling", { method: "PUT", body: JSON.stringify({ feeling: "alto", justification: "Cotação solicitada" }) }) as never,
      { params: Promise.resolve({ leadId: "lead-1" }) },
    );
    expect(response.status).toBe(403);
  });

  // b67f1c6b: o Feeling vale para todo lead com score, não só para stage='atacado'.
  it("accepts Feeling for a scored lead regardless of its stage", async () => {
    vi.mocked(getCurrentUser).mockResolvedValueOnce({ userId: "vend-1", role: "vendedor", email: "v@x" } as never);
    const salvo = { lead_id: "lead-1", user_id: "vend-1", feeling: "alto" };
    const { client, chamadas } = clienteFalso({
      lead_qualification_scores: { data: { lead_id: "lead-1" }, error: null },
      lead_seller_feelings: { data: salvo, error: null },
    });
    vi.mocked(getServiceSupabase).mockResolvedValueOnce(client as never);
    const response = await putFeeling();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(salvo);
    expect(chamadas.some((c) => c.metodo === "eq" && c.args[0] === "stage")).toBe(false);
    expect(chamadas).toContainEqual({ tabela: "lead_qualification_scores", metodo: "eq", args: ["lead_id", "lead-1"] });
  });

  it("returns 404 for a lead without score", async () => {
    vi.mocked(getCurrentUser).mockResolvedValueOnce({ userId: "vend-1", role: "vendedor" } as never);
    const { client, chamadas } = clienteFalso({ lead_qualification_scores: { data: null, error: null } });
    vi.mocked(getServiceSupabase).mockResolvedValueOnce(client as never);
    const response = await putFeeling();
    expect(response.status).toBe(404);
    expect(chamadas.some((c) => c.tabela === "lead_seller_feelings")).toBe(false);
  });
});
