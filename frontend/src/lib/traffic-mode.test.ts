import { describe, expect, it } from "vitest";
import { FRASE_MODO, linhaSync, modoDaUrl } from "./traffic-mode";

describe("traffic-mode", () => {
  it("sem modo na URL é a visão do período", () => {
    expect(modoDaUrl(null)).toBe("periodo");
    expect(modoDaUrl("xpto")).toBe("periodo");
    expect(modoDaUrl("lead")).toBe("lead");
    expect(modoDaUrl("sale")).toBe("sale");
  });

  it("frases dos modos", () => {
    expect(FRASE_MODO.periodo).toContain("toda venda do período");
    expect(FRASE_MODO.periodo).toContain("quem entrou no período");
    expect(FRASE_MODO.lead).toContain("90 no B2B");
  });

  it("linha do sync em horário de Brasília", () => {
    expect(linhaSync("google", { status: "ok", em: "2026-11-06T17:30:00+00:00" }))
      .toBe("Google: sincronizado em 06/11 14:30");
    expect(linhaSync("google", { status: "falha", motivo: "HTTP 404 em v22", em: "2026-11-06T17:30:00Z" }))
      .toBe("Google: falhou em 06/11 14:30: HTTP 404 em v22");
    expect(linhaSync("meta", { status: "aviso", motivo: "API respondeu 0 linhas", em: "2026-11-06T17:30:00Z" }))
      .toBe("Meta: zerado em 06/11 14:30: API respondeu 0 linhas");
  });
});
