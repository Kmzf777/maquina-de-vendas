import { describe, it, expect } from "vitest";
import { foldText, leadMatchesSearch, dealMatchesSearch } from "./search";

describe("foldText", () => {
  it("strips diacritics and lowercases", () => {
    expect(foldText("José Açaí")).toBe("jose acai");
    expect(foldText("CAÇAPAVA")).toBe("cacapava");
  });
});

describe("leadMatchesSearch", () => {
  const lead = {
    name: "José da Silva",
    phone: "5534999998888",
    company: "Café Canastra",
    razao_social: "Canastra Comércio LTDA",
    nome_fantasia: "Canastra Grãos",
  };

  it("returns true for empty query", () => {
    expect(leadMatchesSearch("", lead)).toBe(true);
    expect(leadMatchesSearch("   ", lead)).toBe(true);
  });

  it("matches name without accents", () => {
    expect(leadMatchesSearch("jose", lead)).toBe(true);
    expect(leadMatchesSearch("SILVA", lead)).toBe(true);
  });

  it("matches company and razao_social and nome_fantasia accent-insensitively", () => {
    expect(leadMatchesSearch("cafe", lead)).toBe(true);
    expect(leadMatchesSearch("comercio", lead)).toBe(true);
    expect(leadMatchesSearch("graos", lead)).toBe(true);
  });

  it("matches phone typed with formatting", () => {
    expect(leadMatchesSearch("(34) 99999-8888", lead)).toBe(true);
    expect(leadMatchesSearch("3499999", lead)).toBe(true);
  });

  it("returns false when nothing matches", () => {
    expect(leadMatchesSearch("zzz", lead)).toBe(false);
  });

  it("tolerates null fields", () => {
    expect(leadMatchesSearch("x", { name: null, phone: null })).toBe(false);
  });
});

describe("dealMatchesSearch", () => {
  const deal = {
    title: "Kit Canastra Atacado",
    leads: {
      name: "José da Silva",
      company: "Café Canastra",
      phone: "5534999998888",
      nome_fantasia: "Canastra Grãos",
    },
  };

  it("returns true for empty query", () => {
    expect(dealMatchesSearch("", deal)).toBe(true);
  });

  it("matches deal title accent-insensitively", () => {
    expect(dealMatchesSearch("atacado", deal)).toBe(true);
    expect(dealMatchesSearch("CANASTRA", deal)).toBe(true);
  });

  it("matches lead name, company and nome_fantasia accent-insensitively", () => {
    expect(dealMatchesSearch("jose", deal)).toBe(true);
    expect(dealMatchesSearch("cafe", deal)).toBe(true);
    expect(dealMatchesSearch("graos", deal)).toBe(true);
  });

  it("matches phone typed with formatting", () => {
    expect(dealMatchesSearch("(34) 99999-8888", deal)).toBe(true);
  });

  it("returns false when nothing matches", () => {
    expect(dealMatchesSearch("zzz", deal)).toBe(false);
  });

  it("tolerates missing leads join", () => {
    expect(dealMatchesSearch("x", { title: "Sem lead" })).toBe(false);
  });
});
