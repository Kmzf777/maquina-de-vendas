import { describe, expect, it } from "vitest";
import {
  formatAddress,
  fromViaCep,
  hasAddressChange,
  isAddressComplete,
  mergeViaCep,
  type LeadAddress,
} from "@/lib/lead-address";

const completo: LeadAddress = {
  cep: "38400-100",
  logradouro: "Av. Rondon Pacheco",
  numero: "123",
  complemento: "Sala 2",
  bairro: "Centro",
  municipio: "Uberlândia",
  uf: "mg",
};

describe("isAddressComplete", () => {
  it("aceita endereço com CEP, rua, número, cidade e UF válidos", () => {
    expect(isAddressComplete(completo)).toBe(true);
  });

  it("não exige complemento nem bairro", () => {
    expect(isAddressComplete({ ...completo, complemento: null, bairro: "" })).toBe(true);
  });

  it.each(["logradouro", "numero", "municipio", "uf", "cep"] as const)(
    "recusa quando falta %s",
    (campo) => {
      expect(isAddressComplete({ ...completo, [campo]: "  " })).toBe(false);
      expect(isAddressComplete({ ...completo, [campo]: null })).toBe(false);
    },
  );

  it("recusa CEP com 7 dígitos", () => {
    expect(isAddressComplete({ ...completo, cep: "3840010" })).toBe(false);
  });

  it("recusa UF inexistente", () => {
    expect(isAddressComplete({ ...completo, uf: "XX" })).toBe(false);
  });
});

describe("hasAddressChange", () => {
  it("detecta qualquer campo de endereço no body", () => {
    expect(hasAddressChange({ complemento: "" })).toBe(true);
    expect(hasAddressChange({ uf: null })).toBe(true);
  });

  it("ignora body sem campo de endereço (inclusive o texto legado)", () => {
    expect(hasAddressChange({ name: "X", endereco: "Rua Y" })).toBe(false);
  });
});

describe("formatAddress", () => {
  it("formata o endereço completo", () => {
    expect(formatAddress(completo)).toBe(
      "Av. Rondon Pacheco, 123, Sala 2 - Centro - Uberlândia/MG 38400-100",
    );
  });

  it("omite complemento e bairro vazios", () => {
    expect(formatAddress({ ...completo, complemento: "", bairro: null })).toBe(
      "Av. Rondon Pacheco, 123 - Uberlândia/MG 38400-100",
    );
  });

  it("devolve null quando nada está preenchido", () => {
    expect(formatAddress({})).toBeNull();
    expect(formatAddress({ cep: " ", logradouro: null })).toBeNull();
  });
});

describe("fromViaCep", () => {
  it("devolve null quando o ViaCEP responde erro", () => {
    expect(fromViaCep({ erro: true })).toBeNull();
    expect(fromViaCep({ erro: "true" })).toBeNull();
    expect(fromViaCep(null)).toBeNull();
  });

  it("mapeia localidade para municipio", () => {
    expect(
      fromViaCep({
        cep: "38400-100",
        logradouro: "Avenida Rondon Pacheco",
        bairro: "Centro",
        localidade: "Uberlândia",
        uf: "MG",
      }),
    ).toEqual({
      logradouro: "Avenida Rondon Pacheco",
      bairro: "Centro",
      municipio: "Uberlândia",
      uf: "MG",
    });
  });
});

describe("mergeViaCep", () => {
  it("preenche só os campos vazios", () => {
    const atual: LeadAddress = { cep: "38400100", logradouro: "Rua Digitada", bairro: "" };
    const via: LeadAddress = { logradouro: "Avenida X", bairro: "Centro", municipio: "Uberlândia", uf: "MG" };
    expect(mergeViaCep(atual, via)).toEqual({
      cep: "38400100",
      logradouro: "Rua Digitada",
      bairro: "Centro",
      municipio: "Uberlândia",
      uf: "MG",
    });
  });

  it("não troca valor existente por vazio do ViaCEP", () => {
    expect(mergeViaCep({ bairro: "Meu bairro" }, { bairro: "" })).toEqual({ bairro: "Meu bairro" });
  });
});
