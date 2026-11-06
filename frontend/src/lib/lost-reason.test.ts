import { describe, it, expect } from "vitest";
import {
  LOST_REASONS,
  buildLostReason,
  isLostReasonCode,
  isLostStage,
  lostReasonLabel,
  validateLostReason,
  validateLostReasonPatch,
} from "./lost-reason";

describe("lost-reason (F4)", () => {
  it("vocabulário fechado do cartão, na ordem", () => {
    expect(LOST_REASONS.map((r) => r.code)).toEqual([
      "preco_margem", "frete", "pedido_minimo", "condicao_bonificacao", "comprou_outro",
      "ainda_pesquisando", "consumidor_final", "sem_resposta", "outro",
    ]);
  });

  it("reconhece só códigos da lista", () => {
    expect(isLostReasonCode("frete")).toBe(true);
    expect(isLostReasonCode("Frete")).toBe(false);
    expect(isLostReasonCode("")).toBe(false);
    expect(isLostReasonCode(null)).toBe(false);
    expect(lostReasonLabel("sem_resposta")).toBe("Sem resposta");
    expect(lostReasonLabel("xyz")).toBeNull();
  });

  it("etapa de perda: perdido e fechado_perdido", () => {
    expect(isLostStage({ key: "fechado_perdido" })).toBe(true);
    expect(isLostStage({ key: "perdido" })).toBe(true);
    expect(isLostStage({ key: "fechado_ganho" })).toBe(false);
    expect(isLostStage({ key: null })).toBe(false);
    expect(isLostStage(undefined)).toBe(false);
  });

  it("motivo obrigatório; concorrente obrigatório em comprou_outro", () => {
    expect(validateLostReason("", "")).toMatch(/motivo/);
    expect(validateLostReason("comprou_outro", "  ")).toMatch(/comprou/);
    expect(validateLostReason("comprou_outro", "Orfeu")).toBeNull();
    expect(validateLostReason("frete", "")).toBeNull();
  });

  it("monta o valor: concorrente só com comprou_outro, observação vazia vira null", () => {
    expect(buildLostReason("comprou_outro", "  Orfeu   Cafés ", "  ")).toEqual({
      lost_reason_code: "comprou_outro", lost_competitor: "Orfeu Cafés", lost_reason: null,
    });
    expect(buildLostReason("frete", "Orfeu", " caro p/ MG ")).toEqual({
      lost_reason_code: "frete", lost_competitor: null, lost_reason: "caro p/ MG",
    });
  });

  it("PATCH: código ausente passa; inválido e comprou_outro sem nome não", () => {
    expect(validateLostReasonPatch({ stage_id: "s" })).toBeNull();
    expect(validateLostReasonPatch({ lost_reason_code: null })).toBeNull();
    expect(validateLostReasonPatch({ lost_reason_code: "caro" })).toMatch(/inválido/);
    expect(validateLostReasonPatch({ lost_reason_code: "comprou_outro" })).toMatch(/comprou/);
    expect(validateLostReasonPatch({ lost_reason_code: "comprou_outro", lost_competitor: "X" })).toBeNull();
  });
});
