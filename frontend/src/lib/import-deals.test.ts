import { describe, it, expect } from "vitest";
import { buildImportDeals, type ImportDealLead } from "@/lib/import-deals";

const leads: ImportDealLead[] = [
  { id: "lead-1", name: "Padaria Sol", phone: "5531999990001" },
  { id: "lead-2", name: null, phone: "5531999990002" },
  { id: "lead-3", name: "Mercado Lua", phone: "5531999990003" },
];

describe("buildImportDeals", () => {
  it("cria uma linha de deal por lead, com pipeline/stage e stage 'novo'", () => {
    const rows = buildImportDeals({
      leads,
      pipelineId: "pipe-1",
      stageId: "stage-frio",
      pipelineName: "Leads Frio Disparos",
      existingDealLeadIds: new Set<string>(),
    });
    expect(rows).toHaveLength(3);
    expect(rows[0]).toEqual({
      lead_id: "lead-1",
      title: "Padaria Sol - Leads Frio Disparos",
      value: 0,
      pipeline_id: "pipe-1",
      stage_id: "stage-frio",
      stage: "novo",
    });
  });

  it("usa o telefone como título quando o lead não tem nome", () => {
    const rows = buildImportDeals({
      leads: [leads[1]],
      pipelineId: "pipe-1",
      stageId: "stage-frio",
      pipelineName: "Leads Frio Disparos",
      existingDealLeadIds: new Set<string>(),
    });
    expect(rows[0].title).toBe("5531999990002 - Leads Frio Disparos");
  });

  it("usa o telefone quando o nome é só espaços em branco", () => {
    const rows = buildImportDeals({
      leads: [{ id: "lead-x", name: "   ", phone: "5531999990009" }],
      pipelineId: "pipe-1",
      stageId: "stage-frio",
      pipelineName: "Leads Frio Disparos",
      existingDealLeadIds: new Set<string>(),
    });
    expect(rows[0].title).toBe("5531999990009 - Leads Frio Disparos");
  });

  it("retorna vazio quando não há leads", () => {
    const rows = buildImportDeals({
      leads: [],
      pipelineId: "pipe-1",
      stageId: "stage-frio",
      pipelineName: "Leads Frio Disparos",
      existingDealLeadIds: new Set<string>(),
    });
    expect(rows).toEqual([]);
  });

  it("pula leads que já têm deal no funil (anti-duplicação)", () => {
    const rows = buildImportDeals({
      leads,
      pipelineId: "pipe-1",
      stageId: "stage-frio",
      pipelineName: "Leads Frio Disparos",
      existingDealLeadIds: new Set<string>(["lead-2"]),
    });
    expect(rows.map((r) => r.lead_id)).toEqual(["lead-1", "lead-3"]);
  });

  it("retorna vazio quando todos já têm deal no funil", () => {
    const rows = buildImportDeals({
      leads,
      pipelineId: "pipe-1",
      stageId: "stage-frio",
      pipelineName: "Leads Frio Disparos",
      existingDealLeadIds: new Set<string>(["lead-1", "lead-2", "lead-3"]),
    });
    expect(rows).toEqual([]);
  });
});
