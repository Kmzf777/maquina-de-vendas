import { describe, it, expect } from "vitest";
import { blingGate } from "@/lib/bling-gate";

describe("blingGate", () => {
  it("enquanto carrega, nao decide nada e bloqueia o envio", () => {
    const g = blingGate({ loading: true, error: null, enabled: null, isEditing: false });
    expect(g.mode).toBe("loading");
    expect(g.canSubmit).toBe(false);
  });

  it("Bling ligado entra em modo bling", () => {
    const g = blingGate({ loading: false, error: null, enabled: true, isEditing: false });
    expect(g.mode).toBe("bling");
    expect(g.canSubmit).toBe(true);
  });

  it("Bling desligado cai no modo legado", () => {
    const g = blingGate({ loading: false, error: null, enabled: false, isEditing: false });
    expect(g.mode).toBe("legacy");
    expect(g.canSubmit).toBe(true);
  });

  it("editar venda continua legado mesmo com Bling ligado (Fase E muda isso)", () => {
    const g = blingGate({ loading: false, error: null, enabled: true, isEditing: true });
    expect(g.mode).toBe("legacy");
  });

  // O teste que da nome a fase: falhar NAO pode virar venda avulsa silenciosa.
  it("falha ao consultar o status BLOQUEIA, nunca cai no legado", () => {
    const g = blingGate({ loading: false, error: "timeout", enabled: null, isEditing: false });
    expect(g.mode).toBe("error");
    expect(g.canSubmit).toBe(false);
    expect(g.message).toContain("Bling");
  });

  it("falha durante edicao nao bloqueia: edicao nao toca no ERP nesta fase", () => {
    const g = blingGate({ loading: false, error: "timeout", enabled: null, isEditing: true });
    expect(g.mode).toBe("legacy");
    expect(g.canSubmit).toBe(true);
  });
});
