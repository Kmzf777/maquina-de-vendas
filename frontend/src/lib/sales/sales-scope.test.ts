import { describe, it, expect } from "vitest";
import { salesScopeFilter, podeVerVenda, vendedorDaRecompra } from "@/lib/sales/sales-scope";

const admin = { userId: "u1", email: "comercial@cafecanastra.com", role: "admin" };
const vendedor = { userId: "u2", email: "joao@cafecanastra.com", role: "vendedor" };

describe("salesScopeFilter", () => {
  it("admin nao tem escopo", () => {
    expect(salesScopeFilter(admin, true)).toBeNull();
  });

  it("flag desligada devolve o comportamento global", () => {
    expect(salesScopeFilter(vendedor, false)).toBeNull();
  });

  it("vendedor ve as dele mais as do Bling", () => {
    expect(salesScopeFilter(vendedor, true)).toBe(
      "sold_by.ilike.joao@cafecanastra.com,origin.eq.bling"
    );
  });

  // ilike e o que torna a comparacao insensivel a maiusculas. O seed grava
  // "Comercial2@cafecanastra.com" com C maiusculo; se a comparacao fosse `eq`,
  // uma diferenca de grafia casaria zero linhas e o painel abriria vazio.
  it("usa ilike, nao eq", () => {
    expect(salesScopeFilter({ ...vendedor, email: "Joao@Cafecanastra.com" }, true)).toBe(
      "sold_by.ilike.Joao@Cafecanastra.com,origin.eq.bling"
    );
  });

  // Fail-closed: sem e-mail nao da para montar escopo, e devolver null (=sem
  // escopo) abriria tudo. O chamador precisa tratar isso como 401.
  it("vendedor sem e-mail e recusado, nao liberado", () => {
    expect(() => salesScopeFilter({ ...vendedor, email: "" }, true)).toThrow();
  });

  // Virgula quebraria a sintaxe do `or` do PostgREST e poderia injetar um termo
  // extra no filtro. E-mail valido nao tem virgula; se tiver, recusamos.
  it("e-mail com virgula e recusado", () => {
    expect(() => salesScopeFilter({ ...vendedor, email: "a,b@x.com" }, true)).toThrow();
  });

  // `*` e curinga de ilike e nao tem escape: sem esta recusa, um e-mail com `*`
  // viraria busca por prefixo e alargaria o escopo em vez de restringi-lo.
  it("e-mail com asterisco e recusado — alargaria o escopo", () => {
    expect(() => salesScopeFilter({ ...vendedor, email: "j*@x.com" }, true)).toThrow();
  });

  it("e-mail com parenteses e recusado", () => {
    expect(() => salesScopeFilter({ ...vendedor, email: "a(b)@x.com" }, true)).toThrow();
  });

  it("e-mail com porcento e recusado — e curinga de ILIKE", () => {
    expect(() => salesScopeFilter({ ...vendedor, email: "j%@x.com" }, true)).toThrow();
  });

  // `_` e curinga de um caractere, mas recusa-lo travaria usuarios reais.
  it("underscore no e-mail e aceito", () => {
    expect(salesScopeFilter({ ...vendedor, email: "joao_silva@x.com" }, true)).toContain(
      "joao_silva@x.com"
    );
  });

  // O ponto tem que passar: todo e-mail tem um no dominio, e o PostgREST o
  // aceita sem aspas (verificado contra o servidor real).
  it("ponto no dominio e aceito", () => {
    expect(salesScopeFilter(vendedor, true)).toContain("joao@cafecanastra.com");
  });
});

describe("podeVerVenda", () => {
  it("admin ve qualquer venda", () => {
    expect(podeVerVenda({ sold_by: "outro@x.com", origin: "manual" }, admin, true)).toBe(true);
  });

  it("vendedor ve a propria", () => {
    expect(podeVerVenda({ sold_by: "JOAO@cafecanastra.com", origin: "manual" }, vendedor, true)).toBe(true);
  });

  it("vendedor ve as do Bling", () => {
    expect(podeVerVenda({ sold_by: null, origin: "bling" }, vendedor, true)).toBe(true);
  });

  it("vendedor nao ve a de outro", () => {
    expect(podeVerVenda({ sold_by: "outro@x.com", origin: "manual" }, vendedor, true)).toBe(false);
  });

  it("vendedor nao ve venda do CRM sem dono", () => {
    expect(podeVerVenda({ sold_by: null, origin: "manual" }, vendedor, true)).toBe(false);
  });

  it("flag desligada libera tudo", () => {
    expect(podeVerVenda({ sold_by: "outro@x.com", origin: "manual" }, vendedor, false)).toBe(true);
  });
});

describe("vendedorDaRecompra", () => {
  it("admin le o que pediu", () => {
    expect(vendedorDaRecompra(admin, "outro@x.com")).toBe("outro@x.com");
  });

  it("admin sem filtro le a operacao toda", () => {
    expect(vendedorDaRecompra(admin, null)).toBeNull();
  });

  // O que a funcao existe para impedir: a RPC nao passa pelo filtro `or` do
  // escopo, entao aceitar o e-mail da URL deixaria um vendedor ler o ciclo de
  // recompra de outro — vazamento de agregado, com a lista ao lado correta.
  it("vendedor pedindo outro e-mail continua lendo o proprio", () => {
    expect(vendedorDaRecompra(vendedor, "outro@x.com")).toBe("joao@cafecanastra.com");
  });

  it("vendedor sem filtro le o proprio, nunca o global", () => {
    expect(vendedorDaRecompra(vendedor, null)).toBe("joao@cafecanastra.com");
  });

  it("escopo desligado devolve o filtro da URL", () => {
    expect(vendedorDaRecompra(null, "qualquer@x.com")).toBe("qualquer@x.com");
    expect(vendedorDaRecompra(null, null)).toBeNull();
  });

  it("vendedor sem e-mail e recusado, nao vira global", () => {
    expect(() => vendedorDaRecompra({ ...vendedor, email: "" }, null)).toThrow();
  });
});
