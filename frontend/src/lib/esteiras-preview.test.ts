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

  it("o `relogio` do backend manda mais que o valor atual do gatilho", () => {
    // O caso que a inferência erra: alguém gravou `dias: 0` na esteira de proposta, então
    // stage_days ficou 0 e "stage_days > 0" passaria a dizer silêncio. O backend deriva
    // `relogio` do seed, não do valor — e é ele que vale.
    const zerada = { ...PROPOSTA, stage_days: 0 };
    const args = buildPreviewArgs(zerada, { dias: 7 }, "humano", "stage_days");
    expect(args.p_stage_days).toBe(7);
    expect(args.p_silence_days).toBe(0);
  });

  it("relogio explícito de silêncio não vira etapa mesmo com stage_days preenchido", () => {
    const args = buildPreviewArgs(PROPOSTA, { dias: 9 }, "humano", "silence_days");
    expect(args.p_silence_days).toBe(9);
    expect(args.p_stage_days).toBe(3);
  });

  it("relogio ausente ou desconhecido cai na inferência antiga", () => {
    expect(buildPreviewArgs(PROPOSTA, { dias: 4 }, "humano", null).p_stage_days).toBe(4);
    expect(buildPreviewArgs(PROPOSTA, { dias: 4 }, "humano", "banana").p_stage_days).toBe(4);
    expect(buildPreviewArgs(REPOSICAO, { dias: 4 }, "humano", "banana").p_silence_days).toBe(4);
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

  it("manda o p_campaign_id — sem ele a prévia SUPERESTIMA", () => {
    // A RPC usa `p_campaign_id` para excluir o card que já passou por ESTA campanha
    // dentro do cooldown (DEFAULT 90 dias, 20260904_esteiras_vendedor.sql). Omitir o
    // argumento não quebra nada — ele tem DEFAULT NULL — mas desliga a exclusão, e a
    // prévia passa a contar cards que o gatilho vai descartar na hora da verdade.
    // Esse número é o anteparo contra a avalanche do primeiro dia: inflado, ele mina a
    // confiança na tela exatamente no clique em que ela mais precisa dela.
    const args = buildPreviewArgs(
      REPOSICAO,
      { etapa_id: "s1", campaign_id: "camp-repo" },
      "humano"
    );
    expect(args.p_campaign_id).toBe("camp-repo");
  });

  it("campaign_id ausente ou vazio vira null (a RPC tem DEFAULT NULL)", () => {
    expect(buildPreviewArgs(REPOSICAO, { etapa_id: "s1" }, "humano").p_campaign_id).toBeNull();
    expect(
      buildPreviewArgs(REPOSICAO, { etapa_id: "s1", campaign_id: "" }, "humano").p_campaign_id
    ).toBeNull();
  });

  it("não manda p_cooldown_days — herda o mesmo DEFAULT que o gatilho usa", () => {
    // `triggers.py` também não passa o parâmetro. Fixar um número aqui faria a prévia
    // divergir do gatilho no dia em que o default do SQL mudar.
    expect("p_cooldown_days" in buildPreviewArgs(REPOSICAO, { etapa_id: "s1" }, "humano"))
      .toBe(false);
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
