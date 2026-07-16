import { describe, it, expect } from "vitest";
import {
  fmtBRL,
  fmtUSD,
  usdToBrl,
  brlToUsd,
  dualFromUsd,
  dualFromBrl,
  type FxRate,
} from "./currency";

// O Intl usa NBSP (U+00A0) entre símbolo e número em pt-BR. Normalizamos para
// espaço comum nas asserções — o que importa é símbolo + pontuação, não o byte.
const nb = (s: string | undefined) => s?.replace(/ /g, " ");

const FX: FxRate = { rate: 5.5, date: "2026-07-13", stale: false, source: "awesomeapi" };
const FX_STALE: FxRate = { ...FX, stale: true, source: "fallback" };

describe("formatação por locale", () => {
  it("USD usa símbolo e pontuação en-US", () => {
    expect(nb(fmtUSD(1234.56))).toBe("$1,234.56");
  });

  it("BRL usa símbolo e pontuação pt-BR (vírgula decimal, ponto de milhar)", () => {
    expect(nb(fmtBRL(1234.56))).toBe("R$ 1.234,56");
  });

  it("custo micro de IA não colapsa em $0.00", () => {
    // Custo por atendimento é tipicamente < 1 centavo. Arredondar para 2 casas
    // apagaria o número inteiro e o card viraria "$0.00" — inútil.
    expect(nb(fmtUSD(0.0042))).toBe("$0.0042");
  });

  it("null vira travessão, nunca NaN nem zero", () => {
    expect(fmtUSD(null)).toBe("—");
    expect(fmtBRL(null)).toBe("—");
    expect(fmtUSD(Number.NaN)).toBe("—");
    expect(fmtBRL(Number.POSITIVE_INFINITY)).toBe("—");
  });
});

describe("conversão", () => {
  it("converte USD → BRL", () => {
    expect(usdToBrl(10, 5.5)).toBeCloseTo(55, 10);
  });

  it("converte BRL → USD", () => {
    expect(brlToUsd(55, 5.5)).toBeCloseTo(10, 10);
  });

  it("round-trip fecha dentro de 1 centavo", () => {
    const brl = usdToBrl(123.45, 5.4321);
    expect(brl).not.toBeNull();
    expect(brlToUsd(brl as number, 5.4321)).toBeCloseTo(123.45, 2);
  });

  it("taxa inválida (0 ou negativa) não gera Infinity", () => {
    expect(usdToBrl(10, 0)).toBeNull();
    expect(brlToUsd(10, -1)).toBeNull();
  });
});

describe("exibição dupla — BRL em destaque, nativo na linha de baixo", () => {
  it("valor nativo em USD: real em destaque, dólar + câmbio embaixo", () => {
    const d = dualFromUsd(0.42, FX);
    expect(nb(d.primary)).toBe("R$ 2,31");
    expect(nb(d.secondary)).toBe("$0.42 · câmbio 5,50");
  });

  it("valor nativo em BRL: real em destaque, dólar convertido embaixo", () => {
    const d = dualFromBrl(1100, FX);
    expect(nb(d.primary)).toBe("R$ 1.100,00");
    expect(nb(d.secondary)).toBe("$200.00 · câmbio 5,50");
  });

  it("câmbio stale é declarado como aproximado", () => {
    expect(nb(dualFromUsd(0.42, FX_STALE).secondary)).toBe("$0.42 · câmbio 5,50 (aprox.)");
  });

  it("sem câmbio ainda carregado, mostra só a moeda nativa — não bloqueia o card", () => {
    const dUsd = dualFromUsd(0.42, null);
    expect(nb(dUsd.primary)).toBe("$0.42");
    expect(dUsd.secondary).toBeUndefined();

    const dBrl = dualFromBrl(1100, null);
    expect(nb(dBrl.primary)).toBe("R$ 1.100,00");
    expect(dBrl.secondary).toBeUndefined();
  });

  it("valor nulo vira travessão nas duas moedas", () => {
    const d = dualFromUsd(null, FX);
    expect(d.primary).toBe("—");
    expect(d.secondary).toBeUndefined();
  });
});
