import { describe, expect, it } from "vitest";
import { comKitsNoTopo, ehKitDegustacao, kitsPrimeiro } from "./kits";

const p = (id: number, nome: string) => ({ id, nome });

describe("ehKitDegustacao", () => {
  it("casa os nomes reais do catálogo, sem caixa nem acento", () => {
    for (const nome of ["Kit Degustação", "KIT DEGUSTAÇÃO", "KIT DEGUSTAÇÃO 1°", "Kit Degustação 2", "kit degustacao"]) {
      expect(ehKitDegustacao(nome)).toBe(true);
    }
  });
  it("outros kits e cafés não entram", () => {
    for (const nome of ["Kit Promo 1 - Cápsula Clássico", "Kit Amostra de Cafés", "Café Clássico Moído 250g", "", null, undefined]) {
      expect(ehKitDegustacao(nome)).toBe(false);
    }
  });
});

describe("kitsPrimeiro", () => {
  it("move os kits para o topo preservando a ordem relativa", () => {
    const lista = [p(1, "Café A"), p(2, "Kit Degustação 2"), p(3, "Café B"), p(4, "KIT DEGUSTAÇÃO 1°")];
    expect(kitsPrimeiro(lista).map((x) => x.id)).toEqual([2, 4, 1, 3]);
  });
  it("sem kits devolve a mesma lista", () => {
    const lista = [p(1, "Café A")];
    expect(kitsPrimeiro(lista)).toBe(lista);
  });
});

describe("comKitsNoTopo", () => {
  it("une os kits buscados à parte com a página, sem duplicar", () => {
    const kits = [p(9, "Kit Degustação"), p(2, "Kit Degustação 2")];
    const pagina = [p(1, "Café A"), p(2, "Kit Degustação 2")];
    expect(comKitsNoTopo(kits, pagina).map((x) => x.id)).toEqual([9, 2, 1]);
  });
  it("ignora o que a busca de kits trouxe e não é kit de degustação", () => {
    expect(comKitsNoTopo([p(5, "Kit Promo 1")], [p(1, "Café")]).map((x) => x.id)).toEqual([1]);
  });
});
