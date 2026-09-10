import { describe, expect, it } from "vitest";
import {
  buildDealRows,
  distinctPipelineIds,
  isDealClosed,
  reopenPatch,
  type LeadDeal,
  type StageOption,
} from "@/lib/deal-rows";

const ATACADO: StageOption[] = [
  { id: "a-entrada", label: "Entrada", dot_color: "#aaaaaa", order_index: 0, is_protected: false },
  { id: "a-qualif", label: "Qualificação", dot_color: "#bbbbbb", order_index: 1, is_protected: false },
  { id: "a-ganho", label: "Fechado/Ganho", dot_color: "#00aa00", order_index: 2, is_protected: true },
  { id: "a-perdido", label: "Fechado/Perdido", dot_color: "#aa0000", order_index: 3, is_protected: true },
];

const REPOSICAO: StageOption[] = [
  { id: "r-contato", label: "Contato", dot_color: "#cccccc", order_index: 0, is_protected: false },
  { id: "r-negoc", label: "Negociação", dot_color: "#dddddd", order_index: 1, is_protected: false },
  { id: "r-ganho", label: "Fechado/Ganho", dot_color: "#00aa00", order_index: 2, is_protected: true },
];

const STAGES = { "p-atacado": ATACADO, "p-reposicao": REPOSICAO };

function deal(over: Partial<LeadDeal> = {}): LeadDeal {
  return {
    id: "d1",
    title: "Atacado 60kg",
    value: 4200,
    category: null,
    stage_id: "a-qualif",
    pipeline_id: "p-atacado",
    updated_at: "2026-09-10T12:00:00Z",
    lost_reason: null,
    pipeline_stages: {
      id: "a-qualif",
      label: "Qualificação",
      dot_color: "#bbbbbb",
      key: null,
      is_protected: false,
    },
    pipelines: { id: "p-atacado", name: "Valeria - Atacado" },
    ...over,
  };
}

const CLOSED_STAGE = {
  id: "a-perdido",
  label: "Fechado/Perdido",
  dot_color: "#aa0000",
  key: "fechado_perdido",
  is_protected: true,
};

describe("isDealClosed", () => {
  it("é falso para deal em stage ativo", () => {
    expect(isDealClosed(deal())).toBe(false);
  });

  it("é verdadeiro pela key de fechamento", () => {
    expect(isDealClosed(deal({ pipeline_stages: { ...CLOSED_STAGE, is_protected: false } }))).toBe(true);
  });

  it("é verdadeiro por is_protected, mesmo sem key", () => {
    expect(isDealClosed(deal({ pipeline_stages: { ...CLOSED_STAGE, key: null } }))).toBe(true);
  });

  it("é falso quando o deal não tem stage carregado", () => {
    expect(isDealClosed(deal({ pipeline_stages: null }))).toBe(false);
  });
});

describe("distinctPipelineIds", () => {
  it("deduplica e descarta nulos", () => {
    const deals = [
      deal({ id: "d1", pipeline_id: "p-atacado" }),
      deal({ id: "d2", pipeline_id: "p-atacado" }),
      deal({ id: "d3", pipeline_id: "p-reposicao" }),
      deal({ id: "d4", pipeline_id: null }),
    ];
    expect(distinctPipelineIds(deals).sort()).toEqual(["p-atacado", "p-reposicao"]);
  });

  it("devolve lista vazia sem deals", () => {
    expect(distinctPipelineIds([])).toEqual([]);
  });
});

describe("buildDealRows", () => {
  it("gera uma linha editável por deal aberto no MESMO funil", () => {
    // Este é o bug original: dealForSelectedPipeline casava por pipeline_id,
    // então o segundo deal do mesmo funil era inalcançável.
    const deals = [
      deal({ id: "d1", title: "Atacado 60kg", stage_id: "a-qualif" }),
      deal({ id: "d2", title: "Atacado 20kg", stage_id: "a-entrada" }),
    ];
    const rows = buildDealRows(deals, STAGES);

    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.deal.id)).toEqual(["d1", "d2"]);
    expect(rows.every((r) => r.canEditStage)).toBe(true);
    expect(rows[0].deal.stage_id).toBe("a-qualif");
    expect(rows[1].deal.stage_id).toBe("a-entrada");
  });

  it("dá a cada linha os stages não-protegidos do SEU funil", () => {
    const deals = [
      deal({ id: "d1", pipeline_id: "p-atacado" }),
      deal({
        id: "d2",
        pipeline_id: "p-reposicao",
        stage_id: "r-negoc",
        pipelines: { id: "p-reposicao", name: "João - Reposição" },
        pipeline_stages: { id: "r-negoc", label: "Negociação", dot_color: "#dddddd", key: null, is_protected: false },
      }),
    ];
    const rows = buildDealRows(deals, STAGES);

    expect(rows[0].stageOptions.map((s) => s.id)).toEqual(["a-entrada", "a-qualif"]);
    expect(rows[1].stageOptions.map((s) => s.id)).toEqual(["r-contato", "r-negoc"]);
    expect(rows[1].pipelineName).toBe("João - Reposição");
  });

  it("põe abertos antes de fechados, cada grupo por updated_at desc", () => {
    const deals = [
      deal({ id: "fechado-novo", pipeline_stages: CLOSED_STAGE, updated_at: "2026-09-09T00:00:00Z" }),
      deal({ id: "aberto-velho", updated_at: "2026-01-01T00:00:00Z" }),
      deal({ id: "aberto-novo", updated_at: "2026-09-08T00:00:00Z" }),
      deal({ id: "fechado-velho", pipeline_stages: CLOSED_STAGE, updated_at: "2026-02-01T00:00:00Z" }),
    ];
    expect(buildDealRows(deals, STAGES).map((r) => r.deal.id)).toEqual([
      "aberto-novo",
      "aberto-velho",
      "fechado-novo",
      "fechado-velho",
    ]);
  });

  it("deal fechado não é editável e reabre no primeiro stage ativo", () => {
    const rows = buildDealRows([deal({ pipeline_stages: CLOSED_STAGE, lost_reason: "preço alto" })], STAGES);

    expect(rows[0].isClosed).toBe(true);
    expect(rows[0].canEditStage).toBe(false);
    expect(rows[0].reopenStageId).toBe("a-entrada");
    expect(rows[0].stageLabel).toBe("Fechado/Perdido");
    expect(rows[0].deal.lost_reason).toBe("preço alto");
  });

  it("escolhe o stage de reabertura por order_index, não pela ordem do array", () => {
    const embaralhado = {
      "p-atacado": [
        { id: "a-qualif", label: "Qualificação", dot_color: "#bbbbbb", order_index: 1, is_protected: false },
        { id: "a-perdido", label: "Fechado/Perdido", dot_color: "#aa0000", order_index: 3, is_protected: true },
        { id: "a-entrada", label: "Entrada", dot_color: "#aaaaaa", order_index: 0, is_protected: false },
      ],
    };
    const rows = buildDealRows([deal({ pipeline_stages: CLOSED_STAGE })], embaralhado);
    expect(rows[0].reopenStageId).toBe("a-entrada");
  });

  it("deal sem funil vira linha read-only", () => {
    const rows = buildDealRows(
      [deal({ pipeline_id: null, pipelines: null, pipeline_stages: null })],
      STAGES
    );
    expect(rows[0].pipelineName).toBe("Sem funil");
    expect(rows[0].canEditStage).toBe(false);
    expect(rows[0].reopenStageId).toBe(null);
    expect(rows[0].stageOptions).toEqual([]);
  });

  it("não deixa editar enquanto os stages do funil ainda não chegaram", () => {
    const rows = buildDealRows([deal()], {});
    expect(rows[0].canEditStage).toBe(false);
    expect(rows[0].stageOptions).toEqual([]);
  });
});

describe("reopenPatch", () => {
  it("limpa closed_at e lost_reason junto com o stage", () => {
    expect(reopenPatch("a-entrada")).toEqual({
      stage_id: "a-entrada",
      closed_at: null,
      lost_reason: null,
    });
  });
});
