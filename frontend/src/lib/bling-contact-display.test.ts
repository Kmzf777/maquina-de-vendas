import { describe, expect, it } from "vitest";
import { blingContactUrl, formatBlingAddress } from "@/lib/bling-contact-display";

describe("blingContactUrl", () => {
  it("monta a URL a partir do id", () => {
    expect(blingContactUrl(9159981132)).toContain("9159981132");
  });

  it("sem id nao ha link", () => {
    expect(blingContactUrl(null)).toBe("");
    expect(blingContactUrl(undefined)).toBe("");
  });
});

describe("formatBlingAddress", () => {
  it("sem endereco retorna vazio", () => {
    expect(formatBlingAddress(null)).toBe("");
    expect(formatBlingAddress(undefined)).toBe("");
  });

  it("string crua passa direto", () => {
    expect(formatBlingAddress("Centro, Porto Alegre/RS")).toBe("Centro, Porto Alegre/RS");
  });

  it("monta endereco completo a partir do objeto do espelho", () => {
    expect(
      formatBlingAddress({
        endereco: "Rua das Flores",
        numero: "123",
        bairro: "Centro",
        municipio: "Porto Alegre",
        uf: "RS",
        cep: "90000-000",
      })
    ).toBe("Rua das Flores, 123 - Centro - Porto Alegre/RS - 90000-000");
  });

  it("ignora partes ausentes sem deixar separadores soltos", () => {
    expect(formatBlingAddress({ municipio: "Porto Alegre" })).toBe("Porto Alegre");
    expect(formatBlingAddress({ uf: "RS" })).toBe("RS");
    expect(formatBlingAddress({})).toBe("");
  });
});
