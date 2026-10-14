/**
 * POST /api/leads/import: o lead já gravado em formato antigo do telefone (sem 9,
 * sem 55) conta como existente — atualiza (ou pula, com skipDuplicates) em vez de
 * criar outro, e o update mira o telefone gravado de fato (cartão b747da43).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { POST } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";

type Chamada = { from: number; tabela: string; metodo: string; args: unknown[] };
type Resultado = { data: unknown; error: unknown };

/** Builder encadeável por `from()`; resultados saem da fila na ordem dos `from()`. */
function instalar(respostas: Resultado[]) {
  const chamadas: Chamada[] = [];
  let n = 0;
  vi.mocked(getServiceSupabase).mockResolvedValue({
    from: (tabela: string) => {
      const idx = n++;
      const resultado = respostas[idx] ?? { data: null, error: null };
      const builder: Record<string, unknown> = {};
      for (const metodo of ["select", "in", "neq", "eq", "order", "limit", "insert", "update"]) {
        builder[metodo] = (...args: unknown[]) => {
          chamadas.push({ from: idx, tabela, metodo, args });
          return builder;
        };
      }
      for (const metodo of ["single", "maybeSingle"]) {
        builder[metodo] = () => Promise.resolve(resultado);
      }
      builder.then = (ok: (r: unknown) => unknown) => Promise.resolve(resultado).then(ok);
      return builder;
    },
  } as never);
  return chamadas;
}

const ok = (data: unknown = null): Resultado => ({ data, error: null });
const importar = (body: unknown) =>
  POST(new NextRequest("http://localhost/api/leads/import", { method: "POST", body: JSON.stringify(body) }));

const ANTIGO = { id: "l1", name: "Douglas", phone: "4999170363" };

afterEach(() => vi.clearAllMocks());

describe("POST /api/leads/import — telefone em formato antigo", () => {
  it("procura todas as formas e atualiza o existente pelo telefone gravado, sem inserir", async () => {
    const chamadas = instalar([ok([ANTIGO]), ok()]);

    const res = await importar({
      leads: [{ phone: "5549999170363", name: "Douglas Schutz" }],
      skipDuplicates: false,
    });

    expect(await res.json()).toMatchObject({ inserted: 0, updated: 1, skipped: 0 });
    expect(chamadas.find((c) => c.metodo === "in")?.args).toEqual([
      "phone",
      ["5549999170363", "554999170363", "49999170363", "4999170363"],
    ]);
    expect(chamadas.some((c) => c.metodo === "insert")).toBe(false);
    const update = chamadas.find((c) => c.metodo === "update");
    expect(update?.args[0]).toEqual({ name: "Douglas Schutz" });
    expect(chamadas.find((c) => c.from === update?.from && c.metodo === "eq")?.args).toEqual([
      "phone",
      "4999170363",
    ]);
  });

  it("com skipDuplicates o existente em formato antigo é pulado", async () => {
    const chamadas = instalar([ok([ANTIGO])]);

    const res = await importar({ leads: [{ phone: "49999170363" }], skipDuplicates: true });

    expect(await res.json()).toMatchObject({ inserted: 0, updated: 0, skipped: 1 });
    expect(chamadas.some((c) => c.metodo === "insert" || c.metodo === "update")).toBe(false);
  });

  it("número novo continua sendo inserido com o canônico", async () => {
    const chamadas = instalar([ok([]), ok()]);

    const res = await importar({ leads: [{ phone: "3183016991" }], skipDuplicates: false });

    expect(await res.json()).toMatchObject({ inserted: 1, updated: 0 });
    const insert = chamadas.find((c) => c.metodo === "insert");
    expect((insert?.args[0] as { phone: string }[]).map((r) => r.phone)).toEqual(["5531983016991"]);
  });

  it("com funil, o existente em formato antigo também ganha o card", async () => {
    const novo = { id: "l2", name: null, phone: "5531983016991" };
    const chamadas = instalar([
      ok([ANTIGO]), // busca de existentes
      ok(), // insert do novo
      ok({ id: "st1" }), // stage informado é válido
      ok({ name: "Funil" }), // nome do funil
      ok([ANTIGO, novo]), // leads importados (novos + existentes)
      ok([]), // deals já existentes no funil
      ok(), // insert dos deals
    ]);

    await importar({
      leads: [{ phone: "5549999170363" }, { phone: "3183016991" }],
      skipDuplicates: true,
      pipelineId: "p1",
      stageId: "st1",
    });

    const dealsInsert = chamadas.find((c) => c.tabela === "deals" && c.metodo === "insert");
    expect((dealsInsert?.args[0] as { lead_id: string }[]).map((d) => d.lead_id)).toEqual(["l1", "l2"]);
    const buscaImportados = chamadas.filter((c) => c.from === 4 && c.metodo === "in");
    expect(buscaImportados[0]?.args[1]).toContain("4999170363");
  });

  it("erro na busca de existentes devolve 500 sem inserir", async () => {
    const chamadas = instalar([{ data: null, error: { message: "boom" } }]);
    const res = await importar({ leads: [{ phone: "3183016991" }], skipDuplicates: false });
    expect(res.status).toBe(500);
    expect(chamadas.some((c) => c.metodo === "insert")).toBe(false);
  });
});
