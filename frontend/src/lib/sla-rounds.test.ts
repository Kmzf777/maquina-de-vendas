import { describe, it, expect } from "vitest";
import { collectRounds, summarizeRounds, collectOpenRounds, type SlaConversation } from "@/lib/sla-rounds";
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

describe("collectOpenRounds — rodadas abertas com identidade", () => {
  it("rodada aberta retorna conversationId + elapsedMinutes", () => {
    const c: SlaConversation = {
      id: "conv-1",
      last_seller_response_at: null,
      messages: [{ sent_by: "user", created_at: U("13:00:00") }],
    };
    const now = new Date("2026-06-10T13:25:00Z"); // 10:25 SP
    const open = collectOpenRounds([c], DEFAULT_WINDOW, now);
    expect(open).toEqual([{ conversationId: "conv-1", elapsedMinutes: 25 }]);
  });

  it("rodada fechada por resposta do vendedor não entra", () => {
    const c: SlaConversation = {
      id: "conv-2",
      last_seller_response_at: null,
      messages: [
        { sent_by: "user", created_at: U("13:00:00") },
        { sent_by: "seller", created_at: U("13:05:00") },
      ],
    };
    const open = collectOpenRounds([c], DEFAULT_WINDOW, new Date("2026-06-10T20:00:00Z"));
    expect(open).toEqual([]);
  });

  it("rodada fechada via Finalizar (last_seller_response_at) não entra", () => {
    const c: SlaConversation = {
      id: "conv-3",
      last_seller_response_at: U("13:15:00"),
      messages: [{ sent_by: "user", created_at: U("13:00:00") }],
    };
    const open = collectOpenRounds([c], DEFAULT_WINDOW, new Date("2026-06-10T20:00:00Z"));
    expect(open).toEqual([]);
  });

  it("dois leads abertos → dois itens com os conversationIds certos", () => {
    const a: SlaConversation = {
      id: "conv-a",
      last_seller_response_at: null,
      messages: [{ sent_by: "user", created_at: U("13:00:00") }],
    };
    const b: SlaConversation = {
      id: "conv-b",
      last_seller_response_at: null,
      messages: [{ sent_by: "user", created_at: U("13:10:00") }],
    };
    const now = new Date("2026-06-10T13:30:00Z"); // 10:30 SP
    const open = collectOpenRounds([a, b], DEFAULT_WINDOW, now);
    expect(open).toEqual([
      { conversationId: "conv-a", elapsedMinutes: 30 },
      { conversationId: "conv-b", elapsedMinutes: 20 },
    ]);
  });
});

describe("em atraso só se o CLIENTE foi o último a falar; resposta real = vendedor/IA", () => {
  const LATE = new Date("2026-06-10T20:00:00Z"); // 17:00 SP, fora da janela → nada aberto

  it("resposta da IA (agent) fecha a rodada e conta no tempo de resposta", () => {
    // user 10:00 SP, agent 10:08 SP → rodada fechada de 8 min
    const c = conv([
      { sent_by: "user", t: "13:00:00" },
      { sent_by: "agent", t: "13:08:00" },
    ]);
    const r = collectRounds([c], DEFAULT_WINDOW, LATE);
    expect(r.closed).toEqual([8]);
    expect(r.openElapsed).toEqual([]);
  });

  it("IA (agent) por último → não em atraso", () => {
    const c: SlaConversation = {
      id: "conv-agent",
      last_seller_response_at: null,
      messages: [
        { sent_by: "user", created_at: U("13:00:00") },
        { sent_by: "agent", created_at: U("13:05:00") },
      ],
    };
    expect(collectOpenRounds([c], DEFAULT_WINDOW, LATE)).toEqual([]);
  });

  it("vendedor (seller) por último → não em atraso", () => {
    const c: SlaConversation = {
      id: "conv-seller",
      last_seller_response_at: null,
      messages: [
        { sent_by: "user", created_at: U("13:00:00") },
        { sent_by: "seller", created_at: U("13:05:00") },
      ],
    };
    expect(collectOpenRounds([c], DEFAULT_WINDOW, LATE)).toEqual([]);
  });

  it("disparo (broadcast) por último → NÃO em atraso (nós falamos por último)", () => {
    const c: SlaConversation = {
      id: "conv-bc",
      last_seller_response_at: null,
      messages: [
        { sent_by: "user", created_at: U("13:00:00") },
        { sent_by: "broadcast", created_at: U("13:30:00") },
      ],
    };
    const now = new Date("2026-06-10T13:45:00Z"); // 10:45 SP
    expect(collectOpenRounds([c], DEFAULT_WINDOW, now)).toEqual([]);
  });

  it("disparo não é resposta real: não cria rodada fechada nem aberta", () => {
    // cliente perguntou, só recebeu disparo → não conta em nenhuma métrica
    const c = conv([
      { sent_by: "user", t: "13:00:00" },
      { sent_by: "broadcast", t: "13:30:00" },
    ]);
    const r = collectRounds([c], DEFAULT_WINDOW, LATE);
    expect(r.closed).toEqual([]);
    expect(r.openElapsed).toEqual([]);
  });

  it("follow-up por último → NÃO em atraso", () => {
    const c: SlaConversation = {
      id: "conv-fu",
      last_seller_response_at: null,
      messages: [
        { sent_by: "user", created_at: U("13:00:00") },
        { sent_by: "followup", created_at: U("13:30:00") },
      ],
    };
    const now = new Date("2026-06-10T13:50:00Z"); // 10:50 SP
    expect(collectOpenRounds([c], DEFAULT_WINDOW, now)).toEqual([]);
  });

  it("disparo no meio mas CLIENTE volta a falar → em atraso, ancorado na 1ª msg do cliente", () => {
    // user 10:00 (abre) → broadcast 10:30 (ignora) → user 11:00 (cliente por último)
    // now 11:30 SP → atraso desde 10:00 = 90 min comerciais
    const c: SlaConversation = {
      id: "conv-mix",
      last_seller_response_at: null,
      messages: [
        { sent_by: "user", created_at: U("13:00:00") },
        { sent_by: "broadcast", created_at: U("13:30:00") },
        { sent_by: "user", created_at: U("14:00:00") },
      ],
    };
    const now = new Date("2026-06-10T14:30:00Z"); // 11:30 SP
    expect(collectOpenRounds([c], DEFAULT_WINDOW, now)).toEqual([
      { conversationId: "conv-mix", elapsedMinutes: 90 },
    ]);
  });

  it("cliente por último sem nenhuma resposta → em atraso", () => {
    const c: SlaConversation = {
      id: "conv-wait",
      last_seller_response_at: null,
      messages: [{ sent_by: "user", created_at: U("13:00:00") }],
    };
    const now = new Date("2026-06-10T13:45:00Z"); // 10:45 SP
    expect(collectOpenRounds([c], DEFAULT_WINDOW, now)).toEqual([
      { conversationId: "conv-wait", elapsedMinutes: 45 },
    ]);
  });

  it("broadcast proativo (sem espera aberta) é ignorado; IA fecha a seguir", () => {
    const c = conv([
      { sent_by: "broadcast", t: "13:00:00" },
      { sent_by: "user", t: "13:10:00" },
      { sent_by: "agent", t: "13:20:00" },
    ]);
    const r = collectRounds([c], DEFAULT_WINDOW, LATE);
    expect(r.closed).toEqual([10]);
    expect(r.openElapsed).toEqual([]);
  });
});
