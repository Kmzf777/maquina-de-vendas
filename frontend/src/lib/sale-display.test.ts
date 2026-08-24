import { describe, expect, it } from "vitest";
import { blingOrderUrl, foraDoBling, orderLabel, saleStatus } from "@/lib/sale-display";
import type { Sale } from "@/lib/types";

const base: Sale = {
  id: "S1", lead_id: "L1", sold_at: "2026-08-18T12:00:00Z", value: 267,
  product: "Cafe 250g", sold_by: "v@e.com", deal_id: null,
  conversation_id: null, notes: null, created_at: "2026-08-18T12:00:00Z",
};

describe("saleStatus", () => {
  it("venda normal e Registrada", () => {
    expect(saleStatus({ ...base, bling_order_number: 1234 })).toMatchObject({
      label: "Registrada", tone: "neutral",
    });
  });

  it("cancelada tem tom de alerta", () => {
    expect(saleStatus({ ...base, status: "cancelada" })).toMatchObject({
      label: "Cancelada", tone: "danger",
    });
  });

  it("pendente_bling avisa que esta enviando", () => {
    expect(saleStatus({ ...base, status: "pendente_bling" })).toMatchObject({
      label: "Enviando…", tone: "warning",
    });
  });

  it("usa a situacao do Bling quando existir", () => {
    expect(saleStatus({
      ...base, bling_order_number: 1234, bling_situacao_nome: "Faturado",
    }).label).toBe("Faturado");
  });

  it("cancelada vence a situacao do Bling", () => {
    expect(saleStatus({
      ...base, status: "cancelada", bling_situacao_nome: "Faturado",
    }).label).toBe("Cancelada");
  });
});

describe("orderLabel", () => {
  it("prefixa o numero com #", () => {
    expect(orderLabel({ ...base, bling_order_number: 1234 })).toBe("#1234");
  });

  it("venda legada sem pedido no Bling nao mostra nada", () => {
    expect(orderLabel({ ...base, origin: "manual" })).toBe("");
  });
});

describe("blingOrderUrl", () => {
  it("monta a URL a partir do id", () => {
    expect(blingOrderUrl(34215992)).toContain("34215992");
  });

  it("sem id nao ha link", () => {
    expect(blingOrderUrl(null)).toBe("");
  });

  it("fora do Bling e definido pela ausencia de pedido, nao pelo origin", () => {
    // `as Sale`: foraDoBling recebe so Pick<Sale, "bling_order_id"> de proposito
    // (o discriminador nao e o origin), mas isso faz o TS aplicar excess property
    // check no literal com `origin` — o cast evita o falso positivo sem alargar
    // a assinatura da funcao.
    expect(foraDoBling({ ...base, origin: "manual", bling_order_id: null } as Sale)).toBe(true);
    expect(foraDoBling({ ...base, origin: "crm", bling_order_id: null } as Sale)).toBe(true);
    expect(foraDoBling({ ...base, origin: "bling", bling_order_id: 5991 } as Sale)).toBe(false);
    expect(foraDoBling({ ...base, origin: "crm", bling_order_id: 5991 } as Sale)).toBe(false);
  });
});
