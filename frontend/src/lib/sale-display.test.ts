import { describe, expect, it } from "vitest";
import { accountLabel, blingOrderUrl, foraDoBling, orderLabel, saleStatus } from "@/lib/sale-display";
import { CONTA_PADRAO, type ContaBling } from "@/lib/bling-accounts";
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
});

describe("accountLabel", () => {
  const CONTAS: ContaBling[] = [
    { account: CONTA_PADRAO, label: "Canastra CNPJ 1", configured: true, connected: true },
    { account: "secundaria", label: "Canastra CNPJ 2", configured: true, connected: true },
  ];

  it("devolve null quando so existe uma conta", () => {
    expect(accountLabel({ bling_account: CONTA_PADRAO }, [CONTAS[0]])).toBeNull();
  });

  it("devolve o rotulo da conta quando existem duas", () => {
    expect(accountLabel({ bling_account: "secundaria" }, CONTAS)).toBe("Canastra CNPJ 2");
  });

  it("devolve null para venda fora do Bling", () => {
    expect(accountLabel({ bling_account: null }, CONTAS)).toBeNull();
  });

  it("cai para o slug quando a conta nao esta mais configurada", () => {
    // Venda historica de uma conta que foi removida do BLING_ACCOUNTS: mostrar
    // o slug cru e melhor que esconder a informacao ou quebrar a tela.
    expect(accountLabel({ bling_account: "antiga" }, CONTAS)).toBe("antiga");
  });
});

describe("foraDoBling", () => {
  it("fora do Bling e definido pela ausencia de pedido, nao pelo origin", () => {
    const manualSemPedido: Sale = { ...base, origin: "manual", bling_order_id: null };
    const crmSemPedido: Sale = { ...base, origin: "crm", bling_order_id: null };
    const doBling: Sale = { ...base, origin: "bling", bling_order_id: 5991 };
    const crmComPedido: Sale = { ...base, origin: "crm", bling_order_id: 5991 };

    expect(foraDoBling(manualSemPedido)).toBe(true);
    expect(foraDoBling(crmSemPedido)).toBe(true);
    expect(foraDoBling(doBling)).toBe(false);
    expect(foraDoBling(crmComPedido)).toBe(false);
  });
});
