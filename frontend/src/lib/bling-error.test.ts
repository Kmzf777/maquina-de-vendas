import { describe, expect, it } from "vitest";
import { blingErrorMessage, blingErrorReasons } from "./bling-error";

const GENERICA = {
  error: "validation",
  message: "Não foi possível salvar o contato.",
  detail: "O contato não pode ser salvo pois ocorreram problemas com sua validação.",
  type: "VALIDATION_ERROR",
};

describe("blingErrorReasons", () => {
  it("monta 'Campo: mensagem' a partir de fields", () => {
    expect(
      blingErrorReasons({
        ...GENERICA,
        fields: [
          { campo: "CPF/CNPJ", mensagem: "número inválido" },
          { campo: "CEP", mensagem: "O CEP informado é inválido" },
        ],
      }),
    ).toEqual(["CPF/CNPJ: número inválido", "CEP: O CEP informado é inválido"]);
  });

  it("campo vazio mostra só a mensagem", () => {
    expect(blingErrorReasons({ fields: [{ campo: "", mensagem: "Contato duplicado" }] })).toEqual([
      "Contato duplicado",
    ]);
  });

  it("ignora itens malformados e devolve [] sem fields", () => {
    expect(blingErrorReasons({ fields: [null, 3, { campo: "X" }, { mensagem: "  " }] })).toEqual(
      [],
    );
    expect(blingErrorReasons({ fields: "x" })).toEqual([]);
    expect(blingErrorReasons(GENERICA)).toEqual([]);
    expect(blingErrorReasons(null)).toEqual([]);
    expect(blingErrorReasons(undefined)).toEqual([]);
  });
});

describe("blingErrorMessage", () => {
  it("com fields, a lista de motivos substitui a frase genérica", () => {
    const texto = blingErrorMessage(
      { ...GENERICA, fields: [{ campo: "CEP", mensagem: "O CEP informado é inválido" }] },
      "fallback",
    );
    expect(texto).toBe("O Bling recusou:\n• CEP: O CEP informado é inválido");
    expect(texto).not.toContain("problemas com sua validação");
  });

  it("sem fields, mantém message + detail", () => {
    expect(blingErrorMessage(GENERICA, "fallback")).toBe(
      "Não foi possível salvar o contato. O contato não pode ser salvo pois ocorreram problemas com sua validação.",
    );
  });

  it("sem nada útil, usa o fallback", () => {
    expect(blingErrorMessage({}, "fallback")).toBe("fallback");
    expect(blingErrorMessage(null, "fallback")).toBe("fallback");
    expect(blingErrorMessage({ message: "  ", detail: 3 }, "fallback")).toBe("fallback");
  });
});
