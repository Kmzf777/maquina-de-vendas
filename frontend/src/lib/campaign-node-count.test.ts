import { describe, expect, it } from "vitest";
import { campaignNodeCount } from "./campaign-node-count";
import type { CampaignNode } from "@/lib/types";

const node = { id: "n1" } as CampaignNode;

describe("campaignNodeCount", () => {
  it("listagem: usa o agregado nodes_count (fix do card '0 nós')", () => {
    expect(campaignNodeCount({ nodes_count: 12 })).toBe(12);
  });
  it("detalhe: nodes embutidos são a autoridade quando presentes", () => {
    expect(campaignNodeCount({ nodes: [node, node], nodes_count: 99 })).toBe(2);
  });
  it("payload sem contagem nenhuma cai em 0 (nunca NaN/undefined)", () => {
    expect(campaignNodeCount({})).toBe(0);
    expect(campaignNodeCount({ nodes: undefined, nodes_count: undefined })).toBe(0);
  });
  it("campanha vazia real (0 nós de verdade) continua 0", () => {
    expect(campaignNodeCount({ nodes: [], nodes_count: 0 })).toBe(0);
  });
});
