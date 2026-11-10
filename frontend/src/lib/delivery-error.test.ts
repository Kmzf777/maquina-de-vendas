import { describe, expect, it } from "vitest";
import { deliveryErrorText } from "./delivery-error";

const md = (code: number, title = "X") => ({ delivery_error: { code, title } });

describe("deliveryErrorText", () => {
  it("131026", () => {
    expect(deliveryErrorText("failed", md(131026))).toBe(
      "Não entregue: número sem WhatsApp, número errado ou o cliente bloqueou.",
    );
  });
  it("131047", () => {
    expect(deliveryErrorText("failed", md(131047))).toBe(
      "Não entregue: passou a janela de 24h. Só dá para enviar modelo aprovado.",
    );
  });
  it("131042", () => {
    expect(deliveryErrorText("failed", md(131042))).toBe("Não entregue: problema de pagamento na conta da Meta.");
  });
  it("131049", () => {
    expect(deliveryErrorText("failed", md(131049))).toBe(
      "Não entregue: a Meta limitou mensagens de marketing para este cliente.",
    );
  });
  it("código desconhecido usa o título da Meta", () => {
    expect(deliveryErrorText("failed", md(130472, "User's number is part of an experiment"))).toBe(
      "Não entregue: User's number is part of an experiment (código 130472).",
    );
  });
  it("failed sem erro gravado", () => {
    expect(deliveryErrorText("failed", null)).toBe("Não entregue (motivo não registrado).");
    expect(deliveryErrorText("failed", { interativo: {} })).toBe("Não entregue (motivo não registrado).");
  });
  it("undelivered", () => {
    expect(deliveryErrorText("undelivered", null)).toBe("Entrega não confirmada pela Meta.");
  });
  it("demais status não têm texto", () => {
    for (const s of ["accepted", "sent", "delivered", "read", null, undefined] as const) {
      expect(deliveryErrorText(s, md(131026))).toBeNull();
    }
  });
});
