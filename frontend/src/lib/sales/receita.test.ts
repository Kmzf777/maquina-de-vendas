import { describe, it, expect } from "vitest";
import { vendaCancelada, receitaDaVenda, freteDaVenda, limitesDoDiaBRT, padraoVendedor } from "@/lib/sales/receita";

describe("receita da venda (D7)", () => {
  it("tira o frete", () => {
    expect(receitaDaVenda({ value: 500, freight: 50, status: "registrada" })).toBe(450);
    expect(receitaDaVenda({ value: "100.10", freight: null })).toBe(100.1);
    expect(receitaDaVenda({ value: 80 })).toBe(80);
  });

  it("cancelada nao conta", () => {
    const v = { value: 300, freight: 20, status: "Cancelada" };
    expect(vendaCancelada(v)).toBe(true);
    expect(receitaDaVenda(v)).toBe(0);
    expect(freteDaVenda(v)).toBe(0);
    expect(vendaCancelada({ status: null })).toBe(false);
  });

  it("frete a parte", () => {
    expect(freteDaVenda({ value: 500, freight: 50 })).toBe(50);
    expect(freteDaVenda({ value: 500 })).toBe(0);
  });
});

describe("limitesDoDiaBRT", () => {
  it("usa meia-noite e fim do dia de Brasilia", () => {
    expect(limitesDoDiaBRT("2026-10-01", "2026-10-31")).toEqual({
      gte: "2026-10-01T00:00:00.000-03:00",
      lte: "2026-10-31T23:59:59.999-03:00",
    });
  });

  it("deixa passar instante completo e ausente", () => {
    expect(limitesDoDiaBRT("2026-10-01T10:00:00Z", null)).toEqual({
      gte: "2026-10-01T10:00:00Z",
      lte: null,
    });
  });
});

describe("padraoVendedor", () => {
  it("escapa curingas do ilike", () => {
    expect(padraoVendedor("jo%a_o\\x@c.com")).toBe("jo\\%a\\_o\\\\x@c.com");
  });

  it("asterisco (curinga do PostgREST) nao vira padrao: devolve null para usar eq", () => {
    expect(padraoVendedor("jo*@c.com")).toBeNull();
  });
});
