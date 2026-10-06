import { beforeEach, describe, expect, it, vi } from "vitest";

const { maybeSingle, colunas } = vi.hoisted(() => ({
  maybeSingle: vi.fn(),
  colunas: [] as string[],
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({
      select: (cols: string) => {
        colunas.push(cols);
        return { eq: () => ({ maybeSingle }) };
      },
    }),
  }),
}));

import {
  buscarLeadCliente,
  corpoJaEraCliente,
  defaultsDoContato,
  precisaPerguntarJaEraCliente,
} from "./lead-cliente";

beforeEach(() => {
  maybeSingle.mockReset();
  colunas.length = 0;
});

describe("buscarLeadCliente", () => {
  it("busca por id com as colunas do 'já era cliente'", async () => {
    maybeSingle.mockResolvedValueOnce({
      data: { id: "l1", name: "Iago", ja_era_cliente: null, ja_era_cliente_fonte: null },
      error: null,
    });
    const lead = await buscarLeadCliente("l1");
    expect(colunas[0]).toContain("ja_era_cliente");
    expect(colunas[0]).toContain("razao_social");
    expect(lead?.ja_era_cliente).toBeNull();
  });

  it("sem a migração do P0, cai para o cadastro e não trava a venda", async () => {
    maybeSingle
      .mockResolvedValueOnce({ data: null, error: { message: "column leads.ja_era_cliente does not exist" } })
      .mockResolvedValueOnce({ data: { id: "l1", name: "Iago" }, error: null });
    const lead = await buscarLeadCliente("l1");
    expect(colunas[1]).not.toContain("ja_era_cliente");
    expect(lead?.name).toBe("Iago");
    expect(lead?.ja_era_cliente).toBeUndefined();
    expect(precisaPerguntarJaEraCliente(lead)).toBe(false);
  });

  it("erro nas duas leituras devolve null", async () => {
    maybeSingle.mockResolvedValue({ data: null, error: { message: "x" } });
    expect(await buscarLeadCliente("l1")).toBeNull();
  });
});

describe("defaultsDoContato", () => {
  it("caso Vida Natural: razão social, CNPJ só dígitos, e-mail e telefone", () => {
    expect(
      defaultsDoContato({
        name: "Iago",
        razao_social: "VIDA NATURAL LTDA",
        cnpj: "12.345.678/0001-90",
        email: " compras@vidanatural.com ",
        phone: "5531999998888",
      }),
    ).toEqual({
      nome: "VIDA NATURAL LTDA",
      documento: "12345678000190",
      email: "compras@vidanatural.com",
      telefone: "5531999998888",
    });
  });

  it("sem razão social usa o nome; telefone sintético do Bling não entra", () => {
    expect(defaultsDoContato({ name: "Serginho", phone: "bling-123", cnpj: null })).toEqual({
      nome: "Serginho",
      documento: "",
      email: "",
      telefone: "",
    });
  });

  it("lead ausente não pré-preenche nada", () => {
    expect(defaultsDoContato(null)).toEqual({});
  });
});

describe("corpoJaEraCliente", () => {
  it("grava fonte vendedor, quem e quando", () => {
    expect(corpoJaEraCliente(false, "joao@cafecanastra.com", new Date("2026-10-06T12:00:00Z"))).toEqual({
      ja_era_cliente: false,
      ja_era_cliente_fonte: "vendedor",
      ja_era_cliente_por: "joao@cafecanastra.com",
      ja_era_cliente_em: "2026-10-06T12:00:00.000Z",
    });
  });

  it("sem e-mail do vendedor grava por = null", () => {
    expect(corpoJaEraCliente(true, "").ja_era_cliente_por).toBeNull();
  });
});

describe("precisaPerguntarJaEraCliente", () => {
  it("só pergunta quando o banco diz que não sabe (null)", () => {
    expect(precisaPerguntarJaEraCliente({ id: "l", ja_era_cliente: null })).toBe(true);
    expect(precisaPerguntarJaEraCliente({ id: "l", ja_era_cliente: true })).toBe(false);
    expect(precisaPerguntarJaEraCliente({ id: "l", ja_era_cliente: false })).toBe(false);
    expect(precisaPerguntarJaEraCliente({ id: "l" })).toBe(false);
    expect(precisaPerguntarJaEraCliente(null)).toBe(false);
  });
});
