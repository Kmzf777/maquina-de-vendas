import { describe, expect, it } from "vitest";
import {
  displayInstant,
  formatBRT,
  isCancellable,
  offsetLabel,
  touchTypeLabel,
} from "./followup-board";

describe("touchTypeLabel", () => {
  it("toque de cadência (job_type='standard' como o motor grava) vira T<seq>", () => {
    expect(touchTypeLabel({ job_type: "standard", sequence: 2 })).toBe("T2");
  });
  it("job_type null (linhas antigas) também é toque de cadência", () => {
    expect(touchTypeLabel({ job_type: null, sequence: 1 })).toBe("T1");
  });
  it("tipos especializados ganham rótulo PT", () => {
    expect(touchTypeLabel({ job_type: "handoff_rescue", sequence: 1 })).toBe("Resgate de handoff");
    expect(touchTypeLabel({ job_type: "ai_scheduled_return", sequence: 1 })).toBe("Retorno agendado");
  });
  it("tipo desconhecido cai no próprio slug (nunca esconde)", () => {
    expect(touchTypeLabel({ job_type: "novo_tipo", sequence: 1 })).toBe("novo_tipo");
  });
});

describe("isCancellable", () => {
  it("pending e awaiting_reopen são canceláveis", () => {
    expect(isCancellable({ status: "pending" })).toBe(true);
    expect(isCancellable({ status: "awaiting_reopen" })).toBe(true);
  });
  it("sent/processing/cancelled nunca são canceláveis pela UI", () => {
    expect(isCancellable({ status: "sent" })).toBe(false);
    expect(isCancellable({ status: "processing" })).toBe(false);
    expect(isCancellable({ status: "cancelled" })).toBe(false);
  });
});

describe("displayInstant", () => {
  it("enviado usa sent_at", () => {
    expect(
      displayInstant({ status: "sent", fire_at: "2026-07-10T10:00:00Z", sent_at: "2026-07-10T11:00:00Z" }),
    ).toBe("2026-07-10T11:00:00Z");
  });
  it("pendente usa fire_at", () => {
    expect(
      displayInstant({ status: "pending", fire_at: "2026-07-13T12:00:00Z", sent_at: null }),
    ).toBe("2026-07-13T12:00:00Z");
  });
});

describe("formatBRT", () => {
  it("converte UTC para BRT (dd/mm HH:MM)", () => {
    // 12:00 UTC = 09:00 BRT
    expect(formatBRT("2026-07-13T12:00:00+00:00")).toMatch(/13\/07,? 09:00/);
  });
  it("null e lixo viram travessão", () => {
    expect(formatBRT(null)).toBe("—");
    expect(formatBRT("not-a-date")).toBe("—");
  });
});

describe("offsetLabel", () => {
  it("T1: mesmo dia com faixa de jitter", () => {
    expect(offsetLabel(0, [90, 210])).toBe("mesmo dia (+1h30–3h30)");
  });
  it("nudge outbound: +18h", () => {
    expect(offsetLabel(18, null)).toBe("+18h");
  });
  it("D+1 e D+3 exatos", () => {
    expect(offsetLabel(24, null)).toBe("D+1");
    expect(offsetLabel(72, null)).toBe("D+3");
  });
  it("D+6 com resto de horas (T4 = 6d20h)", () => {
    expect(offsetLabel(164, null)).toBe("D+6 (+20h)");
  });
});
