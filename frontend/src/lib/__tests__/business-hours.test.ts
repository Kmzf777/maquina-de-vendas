/**
 * Testes unitários para business-hours.ts
 *
 * Runner: Vitest (adicionar ao package.json quando necessário)
 * Todos os timestamps são construídos como UTC equivalente a uma hora local
 * em America/Sao_Paulo (UTC-3, offset fixo desde 2019).
 *
 * Helper: spDate(year, month, day, hour, minute) → Date UTC
 *   America/Sao_Paulo = UTC-3, portanto hora local + 3h = hora UTC.
 */

import { describe, expect, it } from "vitest";
import {
  businessMinutesBetween,
  businessMinutesElapsed,
  formatBusinessDuration,
  isInBusinessHours,
} from "../business-hours";

/**
 * Constrói um Date a partir de uma hora local em America/Sao_Paulo.
 * SP = UTC-3 (fixo): local 10h00 = UTC 13h00.
 */
function spDate(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number
): Date {
  return new Date(Date.UTC(year, month - 1, day, hour + 3, minute, 0));
}

describe("businessMinutesBetween", () => {
  // -----------------------------------------------------------------------
  // Caso 1 — Canônico: sexta 15h55 → segunda 10h10 = 15 min
  // -----------------------------------------------------------------------
  it("caso canônico: sexta 15h55 → segunda 10h10 = 15 min", () => {
    // Sexta-feira 2026-05-22 15:55 SP
    const from = spDate(2026, 5, 22, 15, 55);
    // Segunda-feira 2026-05-25 10:10 SP
    const to = spDate(2026, 5, 25, 10, 10);

    expect(businessMinutesBetween(from, to)).toBe(15);
  });

  // -----------------------------------------------------------------------
  // Caso 2 — Mesmo dia, dentro do horário: 10h30 → 11h00 = 30 min
  // -----------------------------------------------------------------------
  it("mesmo dia dentro do horário: 10h30 → 11h00 = 30 min", () => {
    const from = spDate(2026, 5, 25, 10, 30); // segunda
    const to = spDate(2026, 5, 25, 11, 0);
    expect(businessMinutesBetween(from, to)).toBe(30);
  });

  // -----------------------------------------------------------------------
  // Caso 3 — Mensagem às 16h01 (fora do horário) até mesmo momento = 0 min
  // -----------------------------------------------------------------------
  it("mensagem às 16h01 até 16h01 = 0 min (fora da janela)", () => {
    const from = spDate(2026, 5, 25, 16, 1); // 16:01 = fora
    const to = spDate(2026, 5, 25, 16, 1);
    expect(businessMinutesBetween(from, to)).toBe(0);
  });

  it("mensagem às 16h01 até 17h00 mesmo dia = 0 min (janela encerrou às 16h)", () => {
    const from = spDate(2026, 5, 25, 16, 1);
    const to = spDate(2026, 5, 25, 17, 0);
    expect(businessMinutesBetween(from, to)).toBe(0);
  });

  // -----------------------------------------------------------------------
  // Caso 4 — Mensagem às 9h → elapsed entre 9h e 10h30 = 30 min
  //   (os 90 min de 9h–10h30 têm apenas 30 min dentro da janela 10h–16h)
  // -----------------------------------------------------------------------
  it("from às 9h, to às 10h30 → 30 min comerciais", () => {
    const from = spDate(2026, 5, 25, 9, 0); // antes do expediente
    const to = spDate(2026, 5, 25, 10, 30);
    expect(businessMinutesBetween(from, to)).toBe(30);
  });

  // -----------------------------------------------------------------------
  // Caso 5 — Sábado e domingo inteiros = 0 min
  // -----------------------------------------------------------------------
  it("sábado inteiro = 0 min", () => {
    const from = spDate(2026, 5, 23, 0, 0); // sábado 00:00
    const to = spDate(2026, 5, 23, 23, 59); // sábado 23:59
    expect(businessMinutesBetween(from, to)).toBe(0);
  });

  it("domingo inteiro = 0 min", () => {
    const from = spDate(2026, 5, 24, 0, 0); // domingo 00:00
    const to = spDate(2026, 5, 24, 23, 59); // domingo 23:59
    expect(businessMinutesBetween(from, to)).toBe(0);
  });

  it("fim de semana completo (sáb 00h → seg 09h59) = 0 min", () => {
    const from = spDate(2026, 5, 23, 0, 0); // sáb
    const to = spDate(2026, 5, 25, 9, 59); // seg 09:59 (ainda fora)
    expect(businessMinutesBetween(from, to)).toBe(0);
  });

  // -----------------------------------------------------------------------
  // Casos extras de sanidade
  // -----------------------------------------------------------------------
  it("from === to retorna 0", () => {
    const d = spDate(2026, 5, 25, 11, 0);
    expect(businessMinutesBetween(d, d)).toBe(0);
  });

  it("from > to retorna 0", () => {
    const from = spDate(2026, 5, 25, 12, 0);
    const to = spDate(2026, 5, 25, 11, 0);
    expect(businessMinutesBetween(from, to)).toBe(0);
  });

  it("janela completa de um dia útil = 360 min", () => {
    const from = spDate(2026, 5, 25, 10, 0); // 10h00
    const to = spDate(2026, 5, 25, 16, 0); // 16h00
    expect(businessMinutesBetween(from, to)).toBe(360);
  });
});

describe("businessMinutesElapsed", () => {
  it("retorna valor >= 0", () => {
    const from = new Date(Date.now() - 60_000); // 1 minuto atrás
    expect(businessMinutesElapsed(from)).toBeGreaterThanOrEqual(0);
  });
});

describe("formatBusinessDuration", () => {
  // Caso 6 — 12 → "12min"
  it('12 min → "12min"', () => {
    expect(formatBusinessDuration(12)).toBe("12min");
  });

  // Caso 7 — 83 → "1h23m"
  it('83 min → "1h23m"', () => {
    expect(formatBusinessDuration(83)).toBe("1h23m");
  });

  it('0 min → "0min"', () => {
    expect(formatBusinessDuration(0)).toBe("0min");
  });

  it('60 min → "1h"', () => {
    expect(formatBusinessDuration(60)).toBe("1h");
  });

  it('120 min → "2h"', () => {
    expect(formatBusinessDuration(120)).toBe("2h");
  });

  it('125 min → "2h5m"', () => {
    expect(formatBusinessDuration(125)).toBe("2h5m");
  });
});

describe("isInBusinessHours", () => {
  // Caso 8 — sábado retorna false
  it("sábado retorna false", () => {
    const sabado = spDate(2026, 5, 23, 11, 0); // sáb 11h
    expect(isInBusinessHours(sabado)).toBe(false);
  });

  it("domingo retorna false", () => {
    const domingo = spDate(2026, 5, 24, 11, 0);
    expect(isInBusinessHours(domingo)).toBe(false);
  });

  it("segunda às 10h00 retorna true", () => {
    const seg = spDate(2026, 5, 25, 10, 0);
    expect(isInBusinessHours(seg)).toBe(true);
  });

  it("segunda às 15h59 retorna true", () => {
    const seg = spDate(2026, 5, 25, 15, 59);
    expect(isInBusinessHours(seg)).toBe(true);
  });

  it("segunda às 16h00 retorna false (exclusive)", () => {
    const seg = spDate(2026, 5, 25, 16, 0);
    expect(isInBusinessHours(seg)).toBe(false);
  });

  it("segunda às 09h59 retorna false", () => {
    const seg = spDate(2026, 5, 25, 9, 59);
    expect(isInBusinessHours(seg)).toBe(false);
  });

  it("sem argumento retorna boolean", () => {
    expect(typeof isInBusinessHours()).toBe("boolean");
  });
});
