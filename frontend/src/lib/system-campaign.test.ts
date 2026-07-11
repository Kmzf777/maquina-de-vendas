import { describe, expect, it } from "vitest";
import { VALERIA_CADENCE_CAMPAIGN_ID, isSystemCampaign } from "./system-campaign";
import { toRFEdges } from "@/components/campaigns/cadence-flow/helpers";
import type { CampaignNode } from "@/lib/types";

describe("VALERIA_CADENCE_CAMPAIGN_ID", () => {
  it("fixa o literal — DEVE ser idêntico a system_cadence.py no backend", () => {
    // uuid5(NAMESPACE_URL, "canastra://system/valeria-followup-cadence")
    expect(VALERIA_CADENCE_CAMPAIGN_ID).toBe("d4a7ffa3-62c2-51c4-91fc-5fcc06ec9055");
  });
  it("isSystemCampaign casa só o UUID de sistema", () => {
    expect(isSystemCampaign(VALERIA_CADENCE_CAMPAIGN_ID)).toBe(true);
    expect(isSystemCampaign("outro-id")).toBe(false);
    expect(isSystemCampaign(null)).toBe(false);
    expect(isSystemCampaign(undefined)).toBe(false);
  });
});

// Fixture com o MESMO shape do grafo do espelho (build_valeria_cadence_graph):
// trigger → t1 → wait → condition ⟨yes→ t2 → … → end_done | no→ reopen → end_reopen⟩.
// Valida que o conversor do PRÓPRIO builder renderiza a cadeia e os dois ramos.
function node(id: string, type: CampaignNode["type"], links: Partial<CampaignNode> = {}): CampaignNode {
  return {
    id,
    campaign_id: "camp",
    type,
    config: {},
    position_x: 0,
    position_y: 0,
    next_node_id: null,
    yes_node_id: null,
    no_node_id: null,
    created_at: "2026-07-10T00:00:00Z",
    ...links,
  } as CampaignNode;
}

describe("toRFEdges renderiza o grafo do espelho do motor", () => {
  const nodes: CampaignNode[] = [
    node("trigger", "trigger", { next_node_id: "t1" }),
    node("t1", "send_text", { next_node_id: "wait_d1" }),
    node("wait_d1", "wait", { next_node_id: "window" }),
    node("window", "condition", { yes_node_id: "t2", no_node_id: "reopen" }),
    node("t2", "send_text", { next_node_id: "end_done" }),
    node("end_done", "end"),
    node("reopen", "send", { next_node_id: "end_reopen" }),
    node("end_reopen", "end"),
  ];

  it("gera a cadeia linear e os ramos SIM/NÃO do condition", () => {
    const edges = toRFEdges(nodes);
    const byId = new Map(edges.map((e) => [e.id, e]));
    expect(byId.has("trigger→t1")).toBe(true);
    expect(byId.has("t1→wait_d1")).toBe(true);
    expect(byId.has("wait_d1→window")).toBe(true);
    expect(byId.get("window→yes→t2")?.label).toBe("SIM");
    expect(byId.get("window→no→reopen")?.label).toBe("NÃO");
    expect(byId.has("reopen→end_reopen")).toBe(true);
    expect(byId.has("t2→end_done")).toBe(true);
    expect(edges).toHaveLength(7);
  });

  it("nós end não emitem arestas de saída", () => {
    const edges = toRFEdges(nodes);
    expect(edges.some((e) => e.source === "end_done" || e.source === "end_reopen")).toBe(false);
  });
});
