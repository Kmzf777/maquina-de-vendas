import { describe, it, expect } from "vitest";
import { DEFAULT_STAGES, stageIsProtectedByKey } from "./pipeline-stages";

describe("DEFAULT_STAGES", () => {
  it("segue o vocabulário decidido em 10/09: sem Contato, Proposta ou Negociação", () => {
    const labels = DEFAULT_STAGES.map((s) => s.label);
    expect(labels).toEqual([
      "Novo",
      "Em conversa",
      "Em atenção",
      "Proposta Enviada",
      "Fechado Ganho",
      "Perdido",
    ]);
  });

  it("dá key a TODA etapa — foi a ausência de key que quebrou os funis do João", () => {
    for (const s of DEFAULT_STAGES) {
      expect(s.key, `etapa ${s.label} sem key`).toBeTruthy();
    }
  });

  it("usa 'respondeu' em Em conversa, que é a key que advance_deal_on_reply procura", () => {
    expect(DEFAULT_STAGES.find((s) => s.label === "Em conversa")?.key).toBe("respondeu");
  });

  it("ordena Em conversa antes de Em atenção antes de Proposta Enviada", () => {
    const idx = (k: string) => DEFAULT_STAGES.findIndex((s) => s.key === k);
    expect(idx("respondeu")).toBeLessThan(idx("em_atencao"));
    expect(idx("em_atencao")).toBeLessThan(idx("proposta_enviada"));
  });

  it("order_index é 0..n sem buracos", () => {
    expect(DEFAULT_STAGES.map((s) => s.order_index)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("protege Fechado Ganho e Perdido, e só eles", () => {
    const prot = DEFAULT_STAGES.filter((s) => s.is_protected).map((s) => s.key);
    expect(prot).toEqual(["fechado_ganho", "fechado_perdido"]);
  });

  it("nunca preenche conversion_event — isso despacharia o card para Meta CAPI", () => {
    for (const s of DEFAULT_STAGES) {
      expect(s).not.toHaveProperty("conversion_event");
    }
  });
});

describe("stageIsProtectedByKey", () => {
  it("recusa apagar etapa que carrega key — foi assim que proposta_enviada sumiu", () => {
    expect(stageIsProtectedByKey("proposta_enviada")).toBe(true);
    expect(stageIsProtectedByKey("em_atencao")).toBe(true);
  });

  it("libera etapa sem key", () => {
    expect(stageIsProtectedByKey(null)).toBe(false);
    expect(stageIsProtectedByKey("")).toBe(false);
    expect(stageIsProtectedByKey(undefined)).toBe(false);
  });
});
