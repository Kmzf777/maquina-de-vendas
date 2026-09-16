import { describe, it, expect, afterEach } from "vitest";
import type { CampaignNode } from "@/lib/types";
import { getDefaultConfig, nodeDetail, resolveNodeIcon, toRFNode, toRFEdges } from "./helpers";
import { buildPaletteFromSchema } from "./constants";
import { primeNodeSchema, schemaDefaults } from "@/lib/node-schema";
import { NODE_SCHEMA_FIXTURE } from "@/lib/node-schema.fixture";

afterEach(() => {
  primeNodeSchema(null);
});

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
  const schema = NODE_SCHEMA_FIXTURE;

  // O contrato inteiro, não uma amostra: qualquer subtipo do schema tem de nascer
  // com EXATAMENTE os defaults declarados no registro (mais o discriminador que a
  // tela usa para saber qual subtipo é). Era essa tabela paralela — mantida à mão
  // dentro de um `switch` — que divergia do motor.
  it("todo subtipo do schema nasce com os defaults declarados", () => {
    for (const tipo of schema.tipos) {
      const sub = tipo.subtipo ?? "";
      const esperado: Record<string, unknown> = { ...schemaDefaults(schema, tipo.tipo, tipo.subtipo) };
      if (tipo.tipo === "trigger") esperado.trigger_type = sub;
      if (tipo.tipo === "condition") esperado.condition_type = sub;
      if (tipo.tipo === "action") esperado.action_type = sub;
      // `final_actions` não é campo do registro: é a lista de ações finais que a
      // própria tela monta dentro do nó `end`.
      if (tipo.tipo === "end") esperado.final_actions = [];

      expect(
        getDefaultConfig(tipo.tipo as CampaignNode["type"], sub, schema),
        `defaults de ${tipo.tipo}/${sub}`,
      ).toEqual(esperado);
    }
  });

  it("send NÃO grava on_reply — gravar aqui sequestra a política do gatilho", () => {
    // `_apply_reply_policy` dá precedência ao NÓ sobre o GATILHO. Enquanto o builder
    // semeava on_reply="pause" em todo nó de envio, uma esteira com gatilho
    // on_reply="reset" pausava na primeira resposta em vez de rebobinar — sem erro
    // em lugar nenhum.
    const send = getDefaultConfig("send", "", schema);
    expect(send).not.toHaveProperty("on_reply");
    expect(send).toEqual({ template_language: "pt_BR" });
    expect(getDefaultConfig("send_text", "", schema)).not.toHaveProperty("on_reply");
  });

  it("wait NÃO grava janela de envio — o nó herda a da campanha", () => {
    // `_wait_target` faz cfg.get("send_start_hour", camp.get(...)): o valor do NÓ
    // vence o da CAMPANHA. Gravar 7/18 em todo nó novo fazia o nó "opinar" sempre.
    const wait = getDefaultConfig("wait", "", schema);
    expect(wait).toEqual({ days: 1, hours: 0 });
    for (const chave of ["send_start_hour", "send_end_hour", "skip_weekends"]) {
      expect(wait, `wait não pode nascer com ${chave}`).not.toHaveProperty(chave);
    }
  });

  it("o gatilho continua sendo o dono do on_reply", () => {
    expect(getDefaultConfig("trigger", "deal_stage_stagnation", schema)).toMatchObject({
      trigger_type: "deal_stage_stagnation",
      on_reply: "pause",
    });
  });

  it("sem schema carregado, o nó nasce só com o discriminador — vazio é melhor que errado", () => {
    primeNodeSchema(null);
    expect(getDefaultConfig("send")).toEqual({});
    expect(getDefaultConfig("trigger", "stage_stagnation")).toEqual({ trigger_type: "stage_stagnation" });
    expect(getDefaultConfig("action")).toEqual({ action_type: "move_stage" });
  });

  it("com o schema no cache, dispensa o terceiro argumento", () => {
    primeNodeSchema(schema);
    expect(getDefaultConfig("condition", "replied_recently")).toEqual({
      condition_type: "replied_recently",
      days: 5,
    });
  });
});

describe("paleta montada do schema", () => {
  const paleta = buildPaletteFromSchema(NODE_SCHEMA_FIXTURE);

  it("expõe as NOVE condições, uma a uma", () => {
    // Até 16/09/2026 a paleta tinha um único item "Condição" que nascia
    // `replied_recently`; as outras oito só existiam num <select> escondido dentro
    // do inspector — ninguém que não conhecesse o código sabia que existiam.
    const condicoes = paleta.actions.filter(i => i.type === "condition");
    expect(condicoes).toHaveLength(9);
    expect(condicoes.map(i => i.subtype)).toEqual([
      "replied_recently", "in_stage", "has_deal", "has_tag", "sale_count",
      "total_spend", "last_sale_value", "deal_value", "repurchase_days",
    ]);
  });

  it("os 12 gatilhos viram itens de paleta com ícone e rótulo do registro", () => {
    expect(paleta.triggers).toHaveLength(12);
    const stagnation = paleta.triggers.find(i => i.subtype === "stage_stagnation");
    expect(stagnation).toMatchObject({ type: "trigger", icon: "🕐", label: "Parado no segmento" });
    for (const item of [...paleta.triggers, ...paleta.actions]) {
      expect(item.icon, `ícone de ${item.type}/${item.subtype}`).toBeTruthy();
      expect(item.label, `rótulo de ${item.type}/${item.subtype}`).toBeTruthy();
      expect(item.desc, `descrição de ${item.type}/${item.subtype}`).toBeTruthy();
    }
  });

  it("tipo fora da paleta some da lista, mas continua sendo um tipo válido", () => {
    const aposentado = {
      ...NODE_SCHEMA_FIXTURE,
      tipos: NODE_SCHEMA_FIXTURE.tipos.map(t =>
        t.subtipo === "post_broadcast" ? { ...t, na_paleta: false } : t,
      ),
    };
    expect(buildPaletteFromSchema(aposentado).triggers.map(i => i.subtype)).not.toContain("post_broadcast");
  });

  it("cada item da paleta produz um default válido", () => {
    for (const item of [...paleta.triggers, ...paleta.actions]) {
      const cfg = getDefaultConfig(item.type, item.subtype, NODE_SCHEMA_FIXTURE);
      if (item.type === "trigger") expect(cfg.trigger_type).toBe(item.subtype);
      if (item.type === "action") expect(cfg.action_type).toBe(item.subtype);
      if (item.type === "condition") expect(cfg.condition_type).toBe(item.subtype);
    }
  });
});

describe("rótulos e ícones do canvas", () => {
  it("resolveNodeIcon usa o ícone do subtipo", () => {
    expect(resolveNodeIcon("trigger", { trigger_type: "deal_stage_stagnation" })).toBe("📋");
    expect(resolveNodeIcon("action", { action_type: "alert_seller" })).toBe("🔔");
  });

  it("condição deixa de aparecer como key crua no card", () => {
    // Com o contrato carregado, o rótulo do card é o do REGISTRO — os mapas locais
    // são só a semente do primeiro paint. Antes desta leva o card exibia a key crua
    // (`repurchase_days`), porque não havia mapa nenhum de condição.
    primeNodeSchema(NODE_SCHEMA_FIXTURE);
    expect(nodeDetail("condition", { condition_type: "repurchase_days" })).toBe("Dias desde a ultima compra");
    expect(nodeDetail("condition", { condition_type: "inventada" })).toBe("inventada");
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
