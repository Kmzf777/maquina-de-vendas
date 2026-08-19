import { describe, expect, it } from "vitest";
import {
  blankContactForm,
  buildContactPayload,
  phoneField,
} from "@/lib/bling-contact-form";

const CHEIO = blankContactForm({
  nome: "  Cafeteria Central  ",
  documento: "29.860.598/0001-70",
  email: "compras@cafeteria.com",
  telefone: "(51) 99269-6163",
  cep: "90000-000",
  logradouro: "Av. Ipiranga",
  numero: "1200",
  bairro: "Centro",
  municipio: "Porto Alegre",
  uf: "rs",
});

describe("blankContactForm", () => {
  it("comeca vazio", () => {
    expect(blankContactForm()).toMatchObject({ nome: "", documento: "", uf: "" });
  });
  it("aceita valores iniciais vindos do lead", () => {
    expect(blankContactForm({ nome: "Fulano" }).nome).toBe("Fulano");
  });
});

describe("phoneField", () => {
  it("11 digitos e celular", () => {
    expect(phoneField("(51) 99269-6163")).toBe("celular");
  });
  it("fixo vai como telefone", () => {
    expect(phoneField("(51) 3226-1234")).toBe("telefone");
  });
  it("vazio cai no telefone", () => {
    expect(phoneField("")).toBe("telefone");
  });
});

describe("buildContactPayload", () => {
  it("monta o corpo do POST /api/bling/contacts", () => {
    const out = buildContactPayload(CHEIO, "L1");
    expect(out.valid).toBe(true);
    expect(out.errors).toEqual({});
    expect(out.payload).toMatchObject({
      lead_id: "L1",
      nome: "Cafeteria Central",
      numeroDocumento: "29860598000170",
      tipo: "J",
      email: "compras@cafeteria.com",
      celular: "(51) 99269-6163",
    });
    expect(out.payload.endereco).toEqual({
      geral: {
        endereco: "Av. Ipiranga",
        numero: "1200",
        bairro: "Centro",
        cep: "90000-000",
        municipio: "Porto Alegre",
        uf: "RS",
      },
    });
  });

  it("CPF vira pessoa fisica", () => {
    const out = buildContactPayload(
      blankContactForm({ nome: "Fulano", documento: "123.456.789-09" }), "L1");
    expect(out.valid).toBe(true);
    expect(out.payload.tipo).toBe("F");
    expect(out.payload.numeroDocumento).toBe("12345678909");
  });

  it("sem endereco nenhum o bloco nao viaja", () => {
    const out = buildContactPayload(
      blankContactForm({ nome: "Fulano", documento: "12345678909" }), "L1");
    expect(out.payload.endereco).toBeUndefined();
    expect(out.payload.email).toBeUndefined();
    expect(out.payload.telefone).toBeUndefined();
  });

  it("sem nome e invalido", () => {
    const out = buildContactPayload(
      blankContactForm({ documento: "12345678909" }), "L1");
    expect(out.valid).toBe(false);
    expect(out.errors.nome).toBeTruthy();
  });

  it("documento e obrigatorio — sem ele o contato duplicaria no ERP", () => {
    const out = buildContactPayload(blankContactForm({ nome: "Fulano" }), "L1");
    expect(out.valid).toBe(false);
    expect(out.errors.documento).toBeTruthy();
  });

  it("documento com DV errado e recusado antes de sair do navegador", () => {
    const out = buildContactPayload(
      blankContactForm({ nome: "Fulano", documento: "11111111111" }), "L1");
    expect(out.valid).toBe(false);
    expect(out.errors.documento).toBe("CPF/CNPJ inválido");
  });
});
