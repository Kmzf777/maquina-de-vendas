import { describe, expect, it } from "vitest";
import {
  formatAddress,
  fromViaCep,
  hasAddressChange,
  isAddressComplete,
  mensagemBlingEndereco,
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

describe("mensagemBlingEndereco", () => {
  it("updated", () => {
    expect(mensagemBlingEndereco({ status: "updated", contas: [] })).toEqual({
      texto: "Endereço atualizado no Bling",
      erro: false,
    });
  });

  it("partial lista as contas que falharam", () => {
    expect(
      mensagemBlingEndereco({
        status: "partial",
        contas: [
          { account: "default", contact_id: 1, status: "error", message: "CEP inválido" },
          { account: "secundaria", contact_id: 2, status: "updated" },
        ],
      }),
    ).toEqual({ texto: "Endereço atualizado em parte do Bling: default: CEP inválido", erro: true });
  });

  it("error usa a message ou as mensagens das contas", () => {
    expect(
      mensagemBlingEndereco({ status: "error", message: "Bling indisponível — tente salvar de novo" })?.texto,
    ).toBe("Falha ao atualizar no Bling: Bling indisponível — tente salvar de novo");
    expect(
      mensagemBlingEndereco({
        status: "error",
        contas: [{ account: "default", contact_id: 1, status: "error", message: "Timeout" }],
      }),
    ).toEqual({ texto: "Falha ao atualizar no Bling: default: Timeout", erro: true });
  });

  it("incomplete e not_linked", () => {
    expect(mensagemBlingEndereco({ status: "incomplete" })).toEqual({
      texto: "Endereço incompleto — não enviado ao Bling",
      erro: false,
    });
    expect(mensagemBlingEndereco({ status: "not_linked" })).toEqual({
      texto: "Lead sem contato no Bling — endereço salvo só no CRM",
      erro: false,
    });
  });

  it("sem resultado ou status desconhecido não mostra nada", () => {
    expect(mensagemBlingEndereco(undefined)).toBeNull();
    expect(mensagemBlingEndereco(null)).toBeNull();
    expect(mensagemBlingEndereco({ status: "???" })).toBeNull();
  });
});
