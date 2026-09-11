// frontend/src/lib/constants.test.ts
import { describe, it, expect } from "vitest";
import { DEAL_STAGES, OFFERABLE_DEAL_STAGES } from "./constants";

const keys = (xs: readonly { key: string }[]) => xs.map((s) => s.key);

describe("DEAL_STAGES", () => {
  it("mantém as keys abolidas, porque ainda traduz deal histórico", () => {
    expect(keys(DEAL_STAGES)).toEqual(
      expect.arrayContaining(["contato", "proposta", "negociacao"])
    );
  });

  it("conhece o vocabulário novo da reunião de 10/09", () => {
    expect(keys(DEAL_STAGES)).toEqual(
      expect.arrayContaining(["respondeu", "em_atencao", "chamado_reposicao"])
    );
  });

  it("toda entrada declara legacy explicitamente", () => {
    for (const s of DEAL_STAGES) {
      expect(typeof s.legacy, `etapa ${s.key} sem legacy`).toBe("boolean");
    }
  });

  it("toda entrada tem rótulo e cor, que lead-detail-modal usa no badge", () => {
    for (const s of DEAL_STAGES) {
      expect(s.dotColor, `etapa ${s.key} sem dotColor`).toBeTruthy();
      expect(s.label, `etapa ${s.key} sem label`).toBeTruthy();
    }
  });
});

describe("OFFERABLE_DEAL_STAGES", () => {
  it("não oferece nenhuma etapa abolida — é o bug que esta task existe para fechar", () => {
    const oferecidas = keys(OFFERABLE_DEAL_STAGES);
    expect(oferecidas).not.toContain("contato");
    expect(oferecidas).not.toContain("proposta");
    expect(oferecidas).not.toContain("negociacao");
  });

  it("oferece o vocabulário novo", () => {
    const oferecidas = keys(OFFERABLE_DEAL_STAGES);
    expect(oferecidas).toContain("respondeu");
    expect(oferecidas).toContain("em_atencao");
    expect(oferecidas).toContain("chamado_reposicao");
  });

  it("é exatamente DEAL_STAGES sem as legacy", () => {
    expect(OFFERABLE_DEAL_STAGES).toHaveLength(
      DEAL_STAGES.filter((s) => !s.legacy).length
    );
  });
});
