import { describe, expect, it } from "vitest";
import {
  docDigits,
  documentKind,
  formatDocument,
  isValidDocument,
} from "@/lib/documento";

describe("docDigits", () => {
  it("descarta a mascara", () => {
    expect(docDigits("29.860.598/0001-70")).toBe("29860598000170");
    expect(docDigits("123.456.789-09")).toBe("12345678909");
  });
  it("sem digito nenhum vira null", () => {
    expect(docDigits("")).toBeNull();
    expect(docDigits(null)).toBeNull();
    expect(docDigits("abc")).toBeNull();
  });
});

describe("isValidDocument", () => {
  // Os MESMOS casos de `backend/tests` para `_cpf_ok`/`_cnpj_ok`. Divergir do
  // backend faria o modal aceitar o que o POST /contacts recusa com 422.
  it("CNPJ valido", () => {
    expect(isValidDocument("29860598000170")).toBe(true);
    expect(isValidDocument("29.860.598/0001-70")).toBe(true);
  });
  it("CPF valido", () => {
    expect(isValidDocument("12345678909")).toBe(true);
    expect(isValidDocument("123.456.789-09")).toBe(true);
  });
  it("digito repetido e invalido mesmo com DV coerente", () => {
    expect(isValidDocument("11111111111")).toBe(false);
    expect(isValidDocument("00000000000000")).toBe(false);
  });
  it("tamanho errado e invalido", () => {
    expect(isValidDocument("123")).toBe(false);
    expect(isValidDocument("")).toBe(false);
    expect(isValidDocument(null)).toBe(false);
  });
  it("DV errado e invalido", () => {
    // Os mesmos numeros de `backend/tests/test_bling_contacts.py`.
    expect(isValidDocument("12345678919")).toBe(false); // DV1 errado (0 -> 1)
    expect(isValidDocument("12345678900")).toBe(false); // DV2 errado (9 -> 0)
    expect(isValidDocument("12345678901234")).toBe(false); // CNPJ com DV errado
    expect(isValidDocument("29860598000160")).toBe(false);
  });
});

describe("documentKind", () => {
  it("14 digitos e pessoa juridica", () => {
    expect(documentKind("29860598000170")).toBe("J");
  });
  it("o resto e pessoa fisica", () => {
    expect(documentKind("12345678909")).toBe("F");
    expect(documentKind("")).toBe("F");
  });
});

describe("formatDocument", () => {
  it("aplica a mascara", () => {
    expect(formatDocument("29860598000170")).toBe("29.860.598/0001-70");
    expect(formatDocument("12345678909")).toBe("123.456.789-09");
  });
  it("tamanho desconhecido volta como veio", () => {
    expect(formatDocument("123")).toBe("123");
  });
});
