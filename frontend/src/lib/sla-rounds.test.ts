import { describe, it, expect } from "vitest";
import { collectRounds, summarizeRounds, type SlaConversation } from "@/lib/sla-rounds";
import { DEFAULT_WINDOW } from "@/lib/business-hours";

// Datas em horário comercial SP. 13:00 UTC = 10:00 SP (qua 2026-06-10).
const U = (sp: string) => new Date(`2026-06-10T${sp}Z`).toISOString();

function conv(messages: { sent_by: string; t: string }[], last_seller_response_at: string | null = null): SlaConversation {
  return {
    id: Math.random().toString(36).slice(2),
    last_seller_response_at,
    messages: messages.map((m) => ({ sent_by: m.sent_by, created_at: U(m.t) })),
  };
}

describe("collectRounds — rodada de espera", () => {
  it("rajada do cliente ancora na PRIMEIRA mensagem sem resposta", () => {
    // 10:00 user, 10:10 user, 10:30 seller -> espera = 30 min (de 10:00)
    const c = conv([
      { sent_by: "user", t: "13:00:00" },
      { sent_by: "user", t: "13:10:00" },
      { sent_by: "seller", t: "13:30:00" },
    ]);
    const r = collectRounds([c], DEFAULT_WINDOW);
    expect(r.closed).toEqual([30]);
    expect(r.openElapsed).toEqual([]);
  });

  it("só a PRIMEIRA resposta do vendedor fecha a rodada", () => {
    const c = conv([
      { sent_by: "user", t: "13:00:00" },
      { sent_by: "seller", t: "13:05:00" },
      { sent_by: "seller", t: "13:06:00" },
    ]);
    const r = collectRounds([c], DEFAULT_WINDOW);
    expect(r.closed).toEqual([5]);
  });

  it("mensagem proativa do vendedor (sem espera aberta) é ignorada", () => {
    const c = conv([
      { sent_by: "seller", t: "13:00:00" },
      { sent_by: "user", t: "13:10:00" },
      { sent_by: "seller", t: "13:20:00" },
    ]);
    const r = collectRounds([c], DEFAULT_WINDOW);
    expect(r.closed).toEqual([10]);
  });

  it("rodada aberta vira openElapsed (sem fechar)", () => {
    // cliente às 10:00 SP, sem resposta; now fixo às 10:25 SP
    const c = conv([{ sent_by: "user", t: "13:00:00" }]);
    const now = new Date("2026-06-10T13:25:00Z");
    const r = collectRounds([c], DEFAULT_WINDOW, now);
    expect(r.closed).toEqual([]);
    expect(r.openElapsed).toEqual([25]);
  });

  it("fallback Finalizar fecha a rodada via last_seller_response_at", () => {
    // cliente 10:00, sem msg de seller, mas Finalizar às 10:15
    const c = conv([{ sent_by: "user", t: "13:00:00" }], U("13:15:00"));
    const r = collectRounds([c], DEFAULT_WINDOW, new Date("2026-06-10T20:00:00Z"));
    expect(r.closed).toEqual([15]);
    expect(r.openElapsed).toEqual([]);
  });
});

describe("summarizeRounds", () => {
  it("média, pior (inclui abertas) e atraso por alvo", () => {
    const rounds = { closed: [10, 20], openElapsed: [40] };
    const s = summarizeRounds(rounds, 30);
    expect(s.avgMinutes).toBe(15);        // média só das fechadas
    expect(s.worstMinutes).toBe(40);      // pior inclui aberta
    expect(s.overdueCount).toBe(1);       // 40 > 30
  });

  it("sem rodadas -> nulos e zero", () => {
    const s = summarizeRounds({ closed: [], openElapsed: [] }, 20);
    expect(s.avgMinutes).toBeNull();
    expect(s.worstMinutes).toBeNull();
    expect(s.overdueCount).toBe(0);
  });
});
