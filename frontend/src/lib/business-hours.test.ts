import { describe, it, expect } from "vitest";
import {
  businessMinutesBetween,
  spDateString,
  type BusinessWindow,
} from "@/lib/business-hours";

// Helper: janela custom
function win(p: Partial<BusinessWindow> = {}): BusinessWindow {
  return {
    startMin: 600,
    endMin: 960,
    weekdays: new Set([1, 2, 3, 4, 5]),
    excludedDates: new Set<string>(),
    ...p,
  };
}

describe("spDateString", () => {
  it("retorna a data SP em YYYY-MM-DD", () => {
    // 2026-06-11 12:00 UTC = 09:00 SP (mesmo dia)
    expect(spDateString(new Date("2026-06-11T12:00:00Z"))).toBe("2026-06-11");
    // 2026-06-12 02:00 UTC = 2026-06-11 23:00 SP (dia anterior em SP)
    expect(spDateString(new Date("2026-06-12T02:00:00Z"))).toBe("2026-06-11");
  });
});

describe("businessMinutesBetween com janela default", () => {
  it("caso canônico sex 15h55 -> seg 10h10 = 15 min", () => {
    // sexta 2026-06-12 15:55 SP = 18:55 UTC
    const from = new Date("2026-06-12T18:55:00Z");
    // segunda 2026-06-15 10:10 SP = 13:10 UTC
    const to = new Date("2026-06-15T13:10:00Z");
    expect(businessMinutesBetween(from, to, win())).toBe(15);
  });

  it("intervalo dentro do mesmo dia útil", () => {
    // quarta 2026-06-10 10:00 SP -> 11:00 SP = 60 min
    const from = new Date("2026-06-10T13:00:00Z");
    const to = new Date("2026-06-10T14:00:00Z");
    expect(businessMinutesBetween(from, to, win())).toBe(60);
  });
});

describe("businessMinutesBetween com janela custom", () => {
  it("respeita startMin/endMin diferentes (8h-18h)", () => {
    // quarta 2026-06-10 08:30 SP -> 09:30 SP = 60 min com janela 8h-18h
    const from = new Date("2026-06-10T11:30:00Z"); // 08:30 SP
    const to = new Date("2026-06-10T12:30:00Z");   // 09:30 SP
    expect(
      businessMinutesBetween(from, to, win({ startMin: 480, endMin: 1080 }))
    ).toBe(60);
  });

  it("respeita weekdays custom (inclui sábado)", () => {
    // sábado 2026-06-13 10:00 SP -> 11:00 SP
    const from = new Date("2026-06-13T13:00:00Z");
    const to = new Date("2026-06-13T14:00:00Z");
    // default (sem sábado) = 0
    expect(businessMinutesBetween(from, to, win())).toBe(0);
    // com sábado (6) = 60
    expect(
      businessMinutesBetween(from, to, win({ weekdays: new Set([1, 2, 3, 4, 5, 6]) }))
    ).toBe(60);
  });
});

describe("businessMinutesBetween com dias anulados", () => {
  it("zera um dia inteiro presente em excludedDates", () => {
    // quarta 2026-06-10 inteira anulada
    const from = new Date("2026-06-10T13:00:00Z"); // 10:00 SP qua
    const to = new Date("2026-06-10T16:00:00Z");   // 13:00 SP qua
    expect(
      businessMinutesBetween(from, to, win({ excludedDates: new Set(["2026-06-10"]) }))
    ).toBe(0);
  });

  it("par que atravessa um dia anulado conta só os dias válidos", () => {
    // ter 2026-06-09 15:00 SP -> qui 2026-06-11 11:00 SP, qua 10 anulada.
    // ter: 15:00->16:00 = 60; qua: 0 (anulada); qui: 10:00->11:00 = 60. Total 120.
    const from = new Date("2026-06-09T18:00:00Z"); // 15:00 SP ter
    const to = new Date("2026-06-11T14:00:00Z");   // 11:00 SP qui
    expect(
      businessMinutesBetween(from, to, win({ excludedDates: new Set(["2026-06-10"]) }))
    ).toBe(120);
  });
});
