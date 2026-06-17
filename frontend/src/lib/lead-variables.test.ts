// frontend/src/lib/lead-variables.test.ts
import { describe, it, expect } from "vitest";
import { resolveLeadVariables } from "@/lib/lead-variables";

describe("resolveLeadVariables", () => {
  it("troca {{primeiro_nome}} pelo primeiro nome", () => {
    expect(resolveLeadVariables("Olá {{primeiro_nome}}!", { name: "João Silva" }))
      .toBe("Olá João!");
  });

  it("resolve telefone e empresa", () => {
    expect(resolveLeadVariables("Tel {{telefone}} / {{empresa}}", { phone: "11999", company: "ACME" }))
      .toBe("Tel 11999 / ACME");
  });

  it("mantém o placeholder quando o valor é vazio", () => {
    expect(resolveLeadVariables("Olá {{primeiro_nome}}!", { name: "" }))
      .toBe("Olá {{primeiro_nome}}!");
  });

  it("mantém tokens desconhecidos intactos", () => {
    expect(resolveLeadVariables("{{desconhecido}}", {})).toBe("{{desconhecido}}");
  });

  it("texto sem variáveis passa igual", () => {
    expect(resolveLeadVariables("sem variaveis", {})).toBe("sem variaveis");
  });
});
