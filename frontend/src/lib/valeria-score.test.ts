import { describe, expect, it } from "vitest";
import { feelingValidationError, priorityLabel, scoreLabel, scoreStatusLabel } from "./valeria-score";

describe("Valeria Score presentation", () => {
  it("keeps an absent score distinct from a zero score", () => {
    expect(scoreLabel(null)).toBe("—");
    expect(scoreLabel(0)).toBe("0/8");
  });

  it("labels the exceptional score separately from the normal scale", () => {
    expect(scoreLabel(10)).toBe("10 — Prioridade Máxima");
  });

  it("describes provisional and consolidated snapshots", () => {
    expect(scoreStatusLabel(true)).toBe("Provisório");
    expect(scoreStatusLabel(false)).toBe("Consolidado");
  });
});

describe("Feeling validation", () => {
  it("rejects blank justifications", () => {
    expect(feelingValidationError({ feeling: "alto", justification: "   " })).toBe("A justificativa é obrigatória.");
  });

  it("accepts a valid seller feeling", () => {
    expect(feelingValidationError({ feeling: "medio", justification: "Pediu uma cotação." })).toBeNull();
  });

  it("rejects score data piggybacked on Feeling", () => {
    expect(feelingValidationError({ feeling: "alto", justification: "Cotação solicitada", final_score: 10 })).toBe("Dados de Feeling inválidos.");
  });
});

describe("Priority labels", () => {
  it("translates persisted priority values", () => {
    expect(priorityLabel("maximum")).toBe("Máxima");
    expect(priorityLabel("moderate")).toBe("Moderada");
  });
});
