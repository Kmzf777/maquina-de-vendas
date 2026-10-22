import { describe, expect, it } from "vitest";
import {
  FASES,
  SEGMENTOS,
  agentStageKeyDoLead,
  faseValida,
  leadCasaAgentStage,
  normalizarSegmento,
  resolverSegmentoFase,
  rotuloDoLead,
  segmentoDoLead,
} from "./segmento";

describe("normalizarSegmento — espelho de app/leads/segmento.py", () => {
  it("canoniza grafias", () => {
    expect(normalizarSegmento("Private Label")).toBe("private_label");
    expect(normalizarSegmento("private-label")).toBe("private_label");
    expect(normalizarSegmento(" ATACADO ")).toBe("atacado");
    expect(normalizarSegmento("exportação")).toBe("exportacao");
  });
  it("fase, secretaria e lixo viram null", () => {
    for (const v of [null, undefined, "", "secretaria", "pending", "perdido", "novo", "xyz"]) {
      expect(normalizarSegmento(v)).toBeNull();
    }
  });
  it("listas do contrato", () => {
    expect(SEGMENTOS).toEqual(["atacado", "private_label", "consumo", "exportacao"]);
    expect(FASES).toEqual(["pending", "novo", "triagem", "qualificando", "perdido"]);
    expect(faseValida("triagem")).toBe(true);
    expect(faseValida("atacado")).toBe(false);
    expect(faseValida("secretaria")).toBe(false);
  });
});

describe("segmentoDoLead — lê segmento, com reserva no stage antigo", () => {
  it("prefere leads.segmento", () => {
    expect(segmentoDoLead({ segmento: "atacado", stage: "private_label" })).toBe("atacado");
  });
  it("cai no stage antigo enquanto o backfill não roda", () => {
    expect(segmentoDoLead({ segmento: null, stage: "private_label" })).toBe("private_label");
    expect(segmentoDoLead({ stage: "consumo" })).toBe("consumo");
  });
  it("sem segmento = null", () => {
    expect(segmentoDoLead({ stage: "triagem" })).toBeNull();
    expect(segmentoDoLead(null)).toBeNull();
  });
});

describe("agentStageKeyDoLead — chave de AGENT_STAGES", () => {
  it("segmento ganha da fase", () => {
    expect(agentStageKeyDoLead({ segmento: "exportacao", stage: "qualificando" })).toBe("exportacao");
  });
  it("triagem e o 'secretaria' antigo viram 'triagem'", () => {
    expect(agentStageKeyDoLead({ stage: "triagem" })).toBe("triagem");
    expect(agentStageKeyDoLead({ stage: "secretaria" })).toBe("triagem");
  });
  it("outras fases sem segmento ficam fora do kanban", () => {
    expect(agentStageKeyDoLead({ stage: "pending" })).toBeNull();
    expect(agentStageKeyDoLead({ stage: "qualificando", segmento: null })).toBeNull();
  });
  it("leadCasaAgentStage", () => {
    expect(leadCasaAgentStage({ stage: "secretaria" }, "triagem")).toBe(true);
    expect(leadCasaAgentStage({ stage: "qualificando", segmento: "atacado" }, "atacado")).toBe(true);
    expect(leadCasaAgentStage({ stage: "atacado" }, "atacado")).toBe(true);
    expect(leadCasaAgentStage({ stage: "qualificando", segmento: "consumo" }, "atacado")).toBe(false);
  });
});

describe("rotuloDoLead — 'Secretaria' aparece como 'Em triagem'", () => {
  it("segmento, fase e legado", () => {
    expect(rotuloDoLead({ segmento: "private_label", stage: "qualificando" })).toBe("Private Label");
    expect(rotuloDoLead({ stage: "secretaria" })).toBe("Em triagem");
    expect(rotuloDoLead({ stage: "pending" })).toBe("Pendente");
    expect(rotuloDoLead({ stage: "qualificando" })).toBe("Qualificando");
    expect(rotuloDoLead({ stage: null })).toBe("—");
  });
});

describe("resolverSegmentoFase — PATCH de lead", () => {
  it("sem stage nem segmento: nada muda", () => {
    expect(resolverSegmentoFase({ name: "x" })).toEqual({ ok: true, campos: {} });
  });
  it("aceita segmento normalizado e null", () => {
    expect(resolverSegmentoFase({ segmento: "Private Label" })).toEqual({ ok: true, campos: { segmento: "private_label" } });
    expect(resolverSegmentoFase({ segmento: null })).toEqual({ ok: true, campos: { segmento: null } });
    expect(resolverSegmentoFase({ segmento: "" })).toEqual({ ok: true, campos: { segmento: null } });
  });
  it("recusa segmento fora do enum", () => {
    expect(resolverSegmentoFase({ segmento: "secretaria" }).ok).toBe(false);
  });
  it("aceita fase", () => {
    expect(resolverSegmentoFase({ stage: "perdido" })).toEqual({ ok: true, campos: { stage: "perdido" } });
  });
  it("tela antiga: segmento em stage vira segmento + qualificando", () => {
    expect(resolverSegmentoFase({ stage: "atacado" })).toEqual({
      ok: true, campos: { segmento: "atacado", stage: "qualificando" },
    });
  });
  it("tela antiga: secretaria vira triagem sem segmento", () => {
    expect(resolverSegmentoFase({ stage: "secretaria" })).toEqual({
      ok: true, campos: { segmento: null, stage: "triagem" },
    });
  });
  it("segmento explícito vence o derivado do stage", () => {
    expect(resolverSegmentoFase({ stage: "triagem", segmento: "consumo" })).toEqual({
      ok: true, campos: { segmento: "consumo", stage: "triagem" },
    });
  });
  it("recusa stage desconhecido", () => {
    const r = resolverSegmentoFase({ stage: "Em conversa" });
    expect(r.ok).toBe(false);
  });
});
