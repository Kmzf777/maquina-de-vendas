import { describe, expect, it } from "vitest";
import type { CatalogItem } from "@/lib/valeria-catalog";
import { calcularAlteracoes, textoInicial } from "./valeria-precos-diff";

const itens: CatalogItem[] = [
  { id: "a", sector: "Atacado", name: "A", preco: 28.7, price_formatted: "R$ 28,70" },
  { id: "b", sector: "Atacado", name: "B", preco: 1169.7, price_formatted: "R$ 1.169,70" },
  { id: "c", sector: "Private Label", name: "C", preco: null, price_formatted: null },
];

const inalterados = () => Object.fromEntries(itens.map((i) => [i.id, textoInicial(i)]));

describe("textoInicial", () => {
  it("mostra o preço sem o R$ e vazio quando não há preço", () => {
    expect(textoInicial(itens[0])).toBe("28,70");
    expect(textoInicial(itens[1])).toBe("1.169,70");
    expect(textoInicial(itens[2])).toBe("");
  });
});

describe("calcularAlteracoes", () => {
  it("nada mudou -> nada a salvar", () => {
    expect(calcularAlteracoes(itens, inalterados())).toEqual({ alteracoes: [], invalidos: [] });
  });

  it("só a linha editada vai para o PATCH", () => {
    const textos = { ...inalterados(), a: "29,70" };
    expect(calcularAlteracoes(itens, textos)).toEqual({
      alteracoes: [{ id: "a", preco: 29.7 }],
      invalidos: [],
    });
  });

  it("aceita ponto como decimal e reescrita equivalente não conta como mudança", () => {
    expect(calcularAlteracoes(itens, { ...inalterados(), a: "29.7" }).alteracoes).toEqual([
      { id: "a", preco: 29.7 },
    ]);
    expect(calcularAlteracoes(itens, { ...inalterados(), b: "1169,7" }).alteracoes).toEqual([]);
  });

  it("texto ilegível, zero ou vazio (em item que tinha preço) é inválido e não vai para o PATCH", () => {
    const r = calcularAlteracoes(itens, { ...inalterados(), a: "abc", b: "0" });
    expect(r.alteracoes).toEqual([]);
    expect(r.invalidos).toEqual(["a", "b"]);
    expect(calcularAlteracoes(itens, { ...inalterados(), a: "" }).invalidos).toEqual(["a"]);
  });

  it("item sem preço pode ganhar um", () => {
    expect(calcularAlteracoes(itens, { ...inalterados(), c: "25,70" }).alteracoes).toEqual([
      { id: "c", preco: 25.7 },
    ]);
  });
});
