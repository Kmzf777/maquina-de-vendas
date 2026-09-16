import { describe, expect, it } from "vitest";
import { accountLabel, blingContactUrl, formatBlingAddress } from "@/lib/bling-contact-display";
import { CONTA_PADRAO, type ContaBling } from "@/lib/bling-accounts";

describe("blingContactUrl", () => {
  it("monta a URL a partir do id", () => {
    expect(blingContactUrl(9159981132)).toContain("9159981132");
  });

  it("sem id nao ha link", () => {
    expect(blingContactUrl(null)).toBe("");
    expect(blingContactUrl(undefined)).toBe("");
  });
});

describe("accountLabel", () => {
  const CONTAS: ContaBling[] = [
    { account: CONTA_PADRAO, label: "Canastra CNPJ 1", configured: true, connected: true },
    { account: "secundaria", label: "Canastra CNPJ 2", configured: true, connected: true },
  ];

  it("devolve null quando so existe uma conta", () => {
    expect(accountLabel(CONTA_PADRAO, [CONTAS[0]])).toBeNull();
  });

  it("devolve o rotulo da conta quando existem duas", () => {
    expect(accountLabel("secundaria", CONTAS)).toBe("Canastra CNPJ 2");
  });

  it("devolve null sem conta conhecida", () => {
    expect(accountLabel(null, CONTAS)).toBeNull();
    expect(accountLabel(undefined, CONTAS)).toBeNull();
  });

  it("cai para o slug quando a conta nao esta mais configurada", () => {
    expect(accountLabel("antiga", CONTAS)).toBe("antiga");
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
