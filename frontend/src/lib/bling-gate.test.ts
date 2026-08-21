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

  it("editar venda com Bling ligado entra em modo bling (Fase E)", () => {
    const g = blingGate({ loading: false, error: null, enabled: true, isEditing: true });
    expect(g.mode).toBe("bling");
  });

  // O teste que da nome a fase: falhar NAO pode virar venda avulsa silenciosa.
  it("falha ao consultar o status BLOQUEIA, nunca cai no legado", () => {
    const g = blingGate({ loading: false, error: "timeout", enabled: null, isEditing: false });
    expect(g.mode).toBe("error");
    expect(g.canSubmit).toBe(false);
    expect(g.message).toContain("Bling");
  });

  // Fase E: editar passou a tocar o ERP (PUT no pedido), entao falha durante
  // edicao agora bloqueia igual a criacao — confirmar a conexao importa tanto
  // quanto na criacao, porque editar sem saber se o Bling responde arriscaria
  // a mesma divergencia silenciosa que a fase anterior evitava so na criacao.
  it("falha durante edicao BLOQUEIA, igual a criacao (Fase E)", () => {
    const g = blingGate({ loading: false, error: "timeout", enabled: null, isEditing: true });
    expect(g.mode).toBe("error");
    expect(g.canSubmit).toBe(false);
  });
});
