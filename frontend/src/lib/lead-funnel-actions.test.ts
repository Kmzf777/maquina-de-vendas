import { describe, expect, it } from "vitest";
import {
  buildDealTitle,
  findOpenDealInPipeline,
  isSameTarget,
} from "@/lib/lead-funnel-actions";
import type { LeadDeal } from "@/lib/deal-rows";

const STAGE_ABERTA = {
  id: "v-negoc",
  label: "Negociação",
  dot_color: "#bbbbbb",
  key: null,
  is_protected: false,
};

/** Etapa terminal por `key` — is_protected é false em todas as linhas do banco. */
const STAGE_GANHO = {
  id: "v-ganho",
  label: "Fechado/Ganho",
  dot_color: "#00aa00",
  key: "fechado_ganho",
  is_protected: false,
};

function deal(over: Partial<LeadDeal> = {}): LeadDeal {
  return {
    id: "d1",
    title: "João Silva - João - Vendas",
    value: 1200,
    category: null,
    stage_id: "v-negoc",
    pipeline_id: "p-vendas",
    updated_at: "2026-09-16T12:00:00Z",
    lost_reason: null,
    pipeline_stages: STAGE_ABERTA,
    pipelines: { id: "p-vendas", name: "João - Vendas" },
    ...over,
  };
}

describe("findOpenDealInPipeline", () => {
  it("acha o card aberto do funil", () => {
    const encontrado = findOpenDealInPipeline([deal()], "p-vendas");
    expect(encontrado?.id).toBe("d1");
  });

  it("ignora card fechado no funil (recompra/reposição é fluxo normal)", () => {
    const fechado = deal({ stage_id: "v-ganho", pipeline_stages: STAGE_GANHO });
    expect(findOpenDealInPipeline([fechado], "p-vendas")).toBeNull();
  });

  it("ignora card aberto de outro funil", () => {
    const outro = deal({
      id: "d2",
      pipeline_id: "p-reposicao",
      pipelines: { id: "p-reposicao", name: "João - Reposição" },
    });
    expect(findOpenDealInPipeline([outro], "p-vendas")).toBeNull();
  });

  it("devolve o primeiro quando há dois cards abertos no mesmo funil", () => {
    const primeiro = deal({ id: "d1" });
    const segundo = deal({ id: "d2" });
    expect(findOpenDealInPipeline([primeiro, segundo], "p-vendas")?.id).toBe("d1");
  });

  it("devolve null quando o funil não foi escolhido ainda", () => {
    expect(findOpenDealInPipeline([deal()], "")).toBeNull();
  });
});

describe("buildDealTitle", () => {
  it("usa o formato do autoTitle do DealCreateModal", () => {
    expect(buildDealTitle("João Silva", "João - Vendas")).toBe("João Silva - João - Vendas");
  });

  it("cai no telefone quando o lead não tem nome, igual ao DealCreateModal", () => {
    const lead = { name: null as string | null, phone: "5534988861441" };
    // Mesma expressão do modal: `selectedLead?.name || selectedLead?.phone || "Lead"`.
    expect(buildDealTitle(lead.name || lead.phone, "João - Vendas")).toBe(
      "5534988861441 - João - Vendas",
    );
  });

  it("cai nos fallbacks 'Lead' e 'Funil' quando os dois lados vêm vazios", () => {
    expect(buildDealTitle("   ", "")).toBe("Lead - Funil");
  });
});

describe("isSameTarget", () => {
  it("é true só quando funil E etapa coincidem", () => {
    const atual = deal();
    expect(isSameTarget(atual, "p-vendas", "v-negoc")).toBe(true);
    expect(isSameTarget(atual, "p-vendas", "v-entrada")).toBe(false);
    expect(isSameTarget(atual, "p-reposicao", "v-negoc")).toBe(false);
    expect(isSameTarget(atual, "p-reposicao", "r-contato")).toBe(false);
  });

  it("é false para deal sem funil/etapa, mesmo com argumentos vazios", () => {
    const legado = deal({ pipeline_id: null, stage_id: null });
    expect(isSameTarget(legado, "", "")).toBe(false);
  });
});
