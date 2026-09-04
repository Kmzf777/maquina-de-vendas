import { describe, it, expect } from "vitest";
import { buildPreviewArgs, faltaEtapa, PREVIEW_LIMIT } from "./esteiras-preview";

// Gatilhos como o seed os cria (backend/app/campaigns/esteiras.py).
const REPOSICAO = {
  stage_id: null, stage_key: null, pipeline_id: null,
  stage_days: 0, silence_days: 15, last_speaker: "qualquer",
};
const PROPOSTA = {
  stage_id: null, stage_key: "proposta_enviada", pipeline_id: null,
  stage_days: 3, silence_days: 0, last_speaker: "nos",
};

describe("buildPreviewArgs", () => {
  it("usa o relógio de SILÊNCIO quando o gatilho não conta dias de etapa", () => {
    const args = buildPreviewArgs(REPOSICAO, { dias: 20, etapa_id: "s1" }, "humano");
    expect(args.p_silence_days).toBe(20);
    expect(args.p_stage_days).toBe(0);
  });

  it("usa o relógio de ETAPA na esteira de proposta", () => {
    const args = buildPreviewArgs(PROPOSTA, { dias: 5 }, "humano");
    expect(args.p_stage_days).toBe(5);
    expect(args.p_silence_days).toBe(0);
  });

  it("o que está na tela vence o que está salvo", () => {
    const args = buildPreviewArgs(
      { ...REPOSICAO, stage_id: "salvo", pipeline_id: "funil-salvo" },
      { etapa_id: "na-tela", funil_id: "funil-na-tela", canal_id: "ch" },
      "humano"
    );
    expect(args.p_stage_id).toBe("na-tela");
    expect(args.p_pipeline_id).toBe("funil-na-tela");
    expect(args.p_channel_id).toBe("ch");
  });

  it("cai no valor salvo quando a tela não mudou nada", () => {
    const args = buildPreviewArgs({ ...REPOSICAO, stage_id: "salvo" }, {}, "humano");
    expect(args.p_stage_id).toBe("salvo");
    expect(args.p_silence_days).toBe(15);
  });

  it("preserva stage_key — é o que prende a esteira de proposta à etapa certa", () => {
    expect(buildPreviewArgs(PROPOSTA, {}, "humano").p_stage_key).toBe("proposta_enviada");
  });

  it("audience ausente ou vazio cai em 'ia', nunca em 'ambos'", () => {
    expect(buildPreviewArgs(REPOSICAO, {}, null).p_audience).toBe("ia");
    expect(buildPreviewArgs(REPOSICAO, {}, "").p_audience).toBe("ia");
    expect(buildPreviewArgs(REPOSICAO, {}, "humano").p_audience).toBe("humano");
  });

  it("last_speaker ausente cai em 'qualquer'", () => {
    expect(buildPreviewArgs({ ...REPOSICAO, last_speaker: null }, {}, "humano").p_last_speaker)
      .toBe("qualquer");
  });

  it("string vazia de etapa conta como ausente (é o value do <option> vazio)", () => {
    const args = buildPreviewArgs(REPOSICAO, { etapa_id: "", funil_id: "" }, "humano");
    expect(args.p_stage_id).toBeNull();
    expect(args.p_pipeline_id).toBeNull();
  });

  it("aplica o teto de contagem", () => {
    expect(buildPreviewArgs(REPOSICAO, {}, "humano").p_limit).toBe(PREVIEW_LIMIT);
  });
});

describe("faltaEtapa", () => {
  it("acusa quando não há nem id nem key — a RPC leria como 'qualquer etapa'", () => {
    expect(faltaEtapa(buildPreviewArgs(REPOSICAO, {}, "humano"))).toBe(true);
  });

  it("não acusa quando a esteira nasce presa a uma key", () => {
    expect(faltaEtapa(buildPreviewArgs(PROPOSTA, {}, "humano"))).toBe(false);
  });

  it("não acusa quando a tela escolheu uma etapa", () => {
    expect(faltaEtapa(buildPreviewArgs(REPOSICAO, { etapa_id: "s1" }, "humano"))).toBe(false);
  });
});
