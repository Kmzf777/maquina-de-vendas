import { describe, it, expect } from "vitest";
import type { CampaignNode } from "@/lib/types";
import { getDefaultConfig, nodeDetail, toRFNode, toRFEdges } from "./helpers";

function makeNode(overrides: Partial<CampaignNode>): CampaignNode {
  return {
    id: "n1",
    campaign_id: "c1",
    type: "trigger",
    config: {},
    position_x: 0,
    position_y: 0,
    next_node_id: null,
    yes_node_id: null,
    no_node_id: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("toRFEdges", () => {
  it("gera edge 'next' com id determinístico e handles out/in", () => {
    const nodes = [
      makeNode({ id: "a", next_node_id: "b" }),
      makeNode({ id: "b", type: "end" }),
    ];
    const edges = toRFEdges(nodes);
    expect(edges).toHaveLength(1);
    expect(edges[0].id).toBe("a→b");
    expect(edges[0].source).toBe("a");
    expect(edges[0].sourceHandle).toBe("out");
    expect(edges[0].target).toBe("b");
    expect(edges[0].targetHandle).toBe("in");
    expect(edges[0].type).toBe("deletable");
  });

  it("gera edges yes/no de condição com ids e labels próprios", () => {
    const nodes = [
      makeNode({ id: "cond", type: "condition", yes_node_id: "y", no_node_id: "n" }),
      makeNode({ id: "y", type: "send" }),
      makeNode({ id: "n", type: "end" }),
    ];
    const edges = toRFEdges(nodes);
    expect(edges).toHaveLength(2);

    const yes = edges.find(e => e.sourceHandle === "yes");
    expect(yes?.id).toBe("cond→yes→y");
    expect(yes?.target).toBe("y");
    expect(yes?.label).toBe("SIM");

    const no = edges.find(e => e.sourceHandle === "no");
    expect(no?.id).toBe("cond→no→n");
    expect(no?.target).toBe("n");
    expect(no?.label).toBe("NÃO");
  });

  it("ignora ponteiros para nós inexistentes", () => {
    const nodes = [makeNode({ id: "a", next_node_id: "fantasma" })];
    expect(toRFEdges(nodes)).toHaveLength(0);
  });
});

describe("nodeDetail", () => {
  it("trigger usa o label conhecido do trigger_type", () => {
    expect(nodeDetail("trigger", { trigger_type: "no_message" })).toBe("Sem mensagem");
    expect(nodeDetail("trigger", { trigger_type: "custom_x" })).toBe("custom_x");
  });

  it("action usa o label conhecido do action_type", () => {
    expect(nodeDetail("action", { action_type: "move_stage" })).toBe("Mover stage do lead");
    expect(nodeDetail("action", { action_type: "custom_y" })).toBe("custom_y");
  });

  it("wait formata dias com fallback 1", () => {
    expect(nodeDetail("wait", { days: 3 })).toBe("3 dia(s)");
    expect(nodeDetail("wait", {})).toBe("1 dia(s)");
  });

  it("send mostra template ou placeholder", () => {
    expect(nodeDetail("send", { template_name: "boas_vindas" })).toBe("boas_vindas");
    expect(nodeDetail("send", {})).toBe("template não definido");
  });
});

describe("getDefaultConfig", () => {
  it("send tem defaults de template e on_reply pause", () => {
    expect(getDefaultConfig("send")).toEqual({
      template_name: "",
      template_language: "pt_BR",
      template_variables: {},
      on_reply: "pause",
    });
  });

  it("wait tem 3 dias e janela de horário 7-18", () => {
    expect(getDefaultConfig("wait")).toEqual({ days: 3, send_start_hour: 7, send_end_hour: 18 });
  });

  it("condition usa subtype ou replied_recently", () => {
    expect(getDefaultConfig("condition")).toEqual({ condition_type: "replied_recently", days: 5 });
    expect(getDefaultConfig("condition", "has_tag")).toEqual({ condition_type: "has_tag", days: 5 });
  });

  it("trigger keyword_received inicia keywords vazio", () => {
    expect(getDefaultConfig("trigger", "keyword_received")).toEqual({
      trigger_type: "keyword_received",
      keywords: [],
    });
  });

  it("action move_stage inclui campo stage vazio", () => {
    expect(getDefaultConfig("action", "move_stage")).toEqual({ action_type: "move_stage", stage: "" });
  });
});

describe("toRFNode", () => {
  it("converte nó do banco em nó React Flow", () => {
    const rf = toRFNode(makeNode({ id: "x", position_x: 10, position_y: 20 }));
    expect(rf.id).toBe("x");
    expect(rf.type).toBe("campaignNode");
    expect(rf.position).toEqual({ x: 10, y: 20 });
    expect(rf.draggable).toBe(true);
    expect(rf.selectable).toBe(true);
  });
});
