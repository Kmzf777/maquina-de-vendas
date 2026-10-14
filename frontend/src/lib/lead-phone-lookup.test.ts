import { describe, expect, it } from "vitest";
import { findLeadByPhoneVariants, findLeadsByPhoneVariants } from "@/lib/lead-phone-lookup";

/** Client mínimo: a consulta encadeada resolve com `resultado`. */
function clientCom(resultado: { data: unknown; error: unknown }) {
  const builder: Record<string, unknown> = {};
  for (const m of ["select", "in", "neq", "order", "limit"]) builder[m] = () => builder;
  builder.then = (ok: (r: unknown) => unknown) => Promise.resolve(resultado).then(ok);
  return { from: () => builder } as never;
}

describe("findLeadByPhoneVariants", () => {
  it("devolve o primeiro lead achado", async () => {
    const lead = { id: "l1", name: "A", phone: "4999170363" };
    expect(await findLeadByPhoneVariants(clientCom({ data: [lead], error: null }), "5549999170363")).toEqual(lead);
  });

  it("nenhum lead devolve null", async () => {
    expect(await findLeadByPhoneVariants(clientCom({ data: [], error: null }), "5549999170363")).toBeNull();
  });

  it("erro na consulta lança (não vira 'não existe' e segue para o insert)", async () => {
    await expect(
      findLeadByPhoneVariants(clientCom({ data: null, error: { message: "boom" } }), "5549999170363"),
    ).rejects.toThrow(/boom/);
  });
});

/** Client que registra cada `.in()` e responde por lote com `porLote[i]`. */
function clientLotes(porLote: unknown[][]) {
  const ins: unknown[][] = [];
  return {
    ins,
    client: {
      from: () => {
        let lote = 0;
        const builder: Record<string, unknown> = {};
        for (const m of ["select", "order"]) builder[m] = () => builder;
        builder.in = (_c: string, valores: unknown[]) => {
          lote = ins.length;
          ins.push(valores);
          return builder;
        };
        builder.then = (ok: (r: unknown) => unknown) =>
          Promise.resolve({ data: porLote[lote] ?? [], error: null }).then(ok);
        return builder;
      },
    } as never,
  };
}

describe("findLeadsByPhoneVariants (lote)", () => {
  it("procura todas as formas e mapeia o lead de volta ao canônico", async () => {
    const antigo = { id: "l1", name: "Douglas", phone: "4999170363" };
    const { client, ins } = clientLotes([[antigo]]);

    const mapa = await findLeadsByPhoneVariants(client, ["5549999170363", "5531983016991"]);

    expect(ins[0]).toEqual([
      "5549999170363", "554999170363", "49999170363", "4999170363",
      "5531983016991", "553183016991", "31983016991", "3183016991",
    ]);
    expect(mapa.get("5549999170363")).toEqual(antigo);
    expect(mapa.has("5531983016991")).toBe(false);
  });

  it("dois leads no mesmo número: fica o primeiro (mais antigo)", async () => {
    const velho = { id: "v", name: null, phone: "554999170363" };
    const novo = { id: "n", name: null, phone: "5549999170363" };
    const { client } = clientLotes([[velho, novo]]);
    const mapa = await findLeadsByPhoneVariants(client, ["5549999170363"]);
    expect(mapa.get("5549999170363")?.id).toBe("v");
  });

  it("lista grande vai em lotes (URL do PostgREST tem limite)", async () => {
    const canonicos = Array.from({ length: 250 }, (_, i) => `55349${String(i).padStart(8, "0")}`);
    const { client, ins } = clientLotes([]);
    await findLeadsByPhoneVariants(client, canonicos);
    expect(ins.length).toBe(3);
    expect(ins.flat().length).toBe(1000);
  });

  it("lista vazia não consulta", async () => {
    const { client, ins } = clientLotes([]);
    expect((await findLeadsByPhoneVariants(client, [])).size).toBe(0);
    expect(ins.length).toBe(0);
  });
});
