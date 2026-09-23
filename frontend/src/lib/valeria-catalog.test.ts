import { describe, expect, it } from "vitest";
import { formatPrecoCatalogo, parsePrecoCatalogo, precoValido } from "./valeria-catalog";

describe("formatPrecoCatalogo", () => {
  it("usa o formato canônico do banco, com espaço ASCII", () => {
    expect(formatPrecoCatalogo(28.7)).toBe("R$ 28,70");
    expect(formatPrecoCatalogo(1169.7)).toBe("R$ 1.169,70");
    expect(formatPrecoCatalogo(12345.5)).toBe("R$ 12.345,50");
    expect(formatPrecoCatalogo(599)).toBe("R$ 599,00");
    expect(formatPrecoCatalogo(28.7)).not.toContain(" ");
  });
});

describe("parsePrecoCatalogo", () => {
  it.each([
    ["R$ 28,70", 28.7],
    ["R$ 1.169,70", 1169.7],
    ["28,70", 28.7],
    ["28,7", 28.7],
    ["28.70", 28.7],
    ["1.169,70", 1169.7],
    ["1169,70", 1169.7],
    ["1.169", 1169],
    ["599", 599],
    [" R$ 32,70 ", 32.7],
  ])("%s -> %s", (entrada, esperado) => {
    expect(parsePrecoCatalogo(entrada)).toBe(esperado);
  });

  it.each([[""], ["abc"], ["28,705"], ["1,2,3"], ["12.34.5"], ["-5"], [null], [undefined]])(
    "rejeita %s",
    (entrada) => {
      expect(parsePrecoCatalogo(entrada as string | null | undefined)).toBeNull();
    },
  );

  it("ida e volta com o formatador", () => {
    for (const v of [0.5, 22.9, 97.7, 169.7, 949, 1234.56]) {
      expect(parsePrecoCatalogo(formatPrecoCatalogo(v))).toBe(v);
    }
  });
});

describe("precoValido", () => {
  it("aceita positivo com até 2 casas e até 99.999", () => {
    expect(precoValido(28.7)).toBe(true);
    expect(precoValido(99999)).toBe(true);
  });
  it.each([[0], [-1], [28.705], [100000], [Number.NaN], [Infinity], ["28,70"], [null]])(
    "rejeita %s",
    (v) => {
      expect(precoValido(v)).toBe(false);
    },
  );
});
