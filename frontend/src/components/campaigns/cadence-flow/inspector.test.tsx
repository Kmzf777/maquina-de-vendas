/**
 * @vitest-environment jsdom
 *
 * O inspector renderiza cada campo pelo VOCABULÁRIO declarado no contrato
 * (`backend/app/campaigns/node_registry.py`), nunca pelo nome do subtipo.
 *
 * É essa regra que impede o bug de voltar: `stage_filter` tem o MESMO nome em
 * `stage_stagnation` (onde o motor compara com `leads.stage`, o segmento) e em
 * `deal_stage_enter` (onde compara com `pipeline_stages.key`, a coluna). Um único
 * <select> servia os dois e gravava o RÓTULO da coluna — errado para ambos, e cinco
 * dos doze gatilhos nunca casavam.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import type { CampaignNode } from "@/lib/types";
import { primeNodeSchema } from "@/lib/node-schema";
import { NODE_SCHEMA_FIXTURE } from "@/lib/node-schema.fixture";
import { Inspector } from "./inspector";
import type { FlowBuilderData } from "./types";

const PIPELINES = [
  { id: "pipe-vendas", name: "João - Vendas" },
  { id: "pipe-reposicao", name: "João - Reposição" },
];

const DATA: FlowBuilderData = {
  templates: [
    { id: "t1", name: "boas_vindas", status: "approved", language: "pt_BR", body: "Olá {{1}}", params: [], paramsType: "none" },
    { id: "t2", name: "promo_setembro", status: "PENDING", language: "pt_BR", body: "Promo", params: [], paramsType: "none" },
  ],
  allStages: [
    { id: "stg-novo", label: "Novo lead", pipeline_name: "João - Vendas", key: "novo" },
    { id: "stg-conversa", label: "Em conversa", pipeline_name: "João - Vendas", key: "respondeu" },
    { id: "stg-ganho", label: "Ganho", pipeline_name: "João - Vendas", key: "fechado_ganho" },
    // Mesma key em outro funil: o <select> de `etapa_key` casa a key em todos os
    // funis, então a opção não pode aparecer duplicada.
    { id: "stg-repo-novo", label: "Reposição — novo", pipeline_name: "João - Reposição", key: "novo" },
    // Coluna legada sem key: não pode virar opção de `etapa_key` (gravaria vazio).
    { id: "stg-sem-key", label: "Coluna antiga", pipeline_name: "João - Reposição", key: null },
  ],
  tags: [{ id: "tag1", name: "vip" }],
  users: [{ id: "u1", name: "João", email: "joao@x.com" }],
  channels: [{ id: "ch1", name: "Comercial", is_active: true, provider: "meta" }],
};

function node(overrides: Partial<CampaignNode>): CampaignNode {
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

function renderInspector(n: CampaignNode) {
  const onSave = vi.fn().mockResolvedValue(undefined);
  const utils = render(
    <Inspector
      node={n}
      saving={false}
      data={DATA}
      onSave={onSave}
      onDelete={vi.fn().mockResolvedValue(undefined)}
      onClose={vi.fn()}
    />,
  );
  return { ...utils, onSave };
}

/** Os `value` das <option> de um campo — o que de fato vai para o banco. */
function opcoes(container: HTMLElement, chave: string): string[] {
  const select = container.querySelector(`[data-campo="${chave}"] select`) as HTMLSelectElement | null;
  if (!select) throw new Error(`campo ${chave} não renderizou um <select>`);
  return Array.from(select.options).map(o => o.value).filter(v => v !== "");
}

function campo(container: HTMLElement, chave: string): HTMLElement | null {
  return container.querySelector(`[data-campo="${chave}"]`);
}

beforeEach(() => {
  primeNodeSchema(NODE_SCHEMA_FIXTURE);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).includes("/api/pipelines")) {
        return { ok: true, status: 200, json: async () => PIPELINES } as Response;
      }
      return { ok: true, status: 200, json: async () => NODE_SCHEMA_FIXTURE } as Response;
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  primeNodeSchema(null);
});

describe("cada vocabulário recebe a sua lista", () => {
  it("segmento_lead recebe SEGMENTOS DE LEAD, e grava a key do segmento", async () => {
    const { container } = renderInspector(node({ config: { trigger_type: "stage_stagnation" } }));
    expect(opcoes(container, "stage_filter")).toEqual([
      "secretaria", "atacado", "private_label", "exportacao", "consumo", "pending", "perdido",
    ]);
    // O rótulo da coluna de Kanban era o que se gravava antes — não pode voltar.
    expect(opcoes(container, "stage_filter")).not.toContain("Em conversa");
  });

  it("etapa_key recebe KEYS de coluna, sem duplicar key repetida entre funis", () => {
    const { container } = renderInspector(node({ config: { trigger_type: "deal_stage_enter" } }));
    expect(opcoes(container, "stage_filter")).toEqual(["novo", "respondeu", "fechado_ganho"]);
  });

  it("etapa_id recebe UUID de coluna", () => {
    const { container } = renderInspector(
      node({ type: "action", config: { action_type: "move_deal_stage" } }),
    );
    expect(opcoes(container, "stage_id")).toEqual([
      "stg-novo", "stg-conversa", "stg-ganho", "stg-repo-novo", "stg-sem-key",
    ]);
  });

  it("funil_id recebe os funis", async () => {
    const { container } = renderInspector(
      node({ type: "action", config: { action_type: "create_deal" } }),
    );
    await waitFor(() => expect(opcoes(container, "pipeline_id")).toEqual(["pipe-vendas", "pipe-reposicao"]));
  });

  it("canal_id, tag e usuario_id vêm das listas do CRM", () => {
    const comTag = renderInspector(node({ type: "action", config: { action_type: "add_tag" } }));
    expect(opcoes(comTag.container, "tag_name")).toEqual(["vip"]);
    cleanup();

    const comVendedor = renderInspector(node({ type: "action", config: { action_type: "assign_to" } }));
    expect(opcoes(comVendedor.container, "user_id")).toEqual(["u1"]);
    cleanup();

    const texto = renderInspector(node({ type: "send_text", config: {} }));
    expect(opcoes(texto.container, "channel_id")).toEqual(["ch1"]);
  });

  it("vocabulários fechados saem de valores_fixos, não de uma cópia na tela", () => {
    const { container } = renderInspector(
      node({ type: "condition", config: { condition_type: "sale_count" } }),
    );
    expect(opcoes(container, "operator")).toEqual(["gte", "lte", "gt", "lt", "eq"]);
  });
});

describe("REGRESSÃO: stage_filter é a mesma chave com dois vocabulários", () => {
  it("stage_stagnation e deal_stage_enter recebem listas DIFERENTES", () => {
    const lead = renderInspector(node({ config: { trigger_type: "stage_stagnation" } }));
    const listaDeLead = opcoes(lead.container, "stage_filter");
    cleanup();

    const deal = renderInspector(node({ config: { trigger_type: "deal_stage_enter" } }));
    const listaDeDeal = opcoes(deal.container, "stage_filter");

    expect(listaDeLead).not.toEqual(listaDeDeal);
    expect(listaDeLead).toContain("atacado");
    expect(listaDeLead).not.toContain("novo");
    expect(listaDeDeal).toContain("novo");
    expect(listaDeDeal).not.toContain("atacado");
  });

  it("in_stage (condição) é a sexta ocorrência do bug e também usa segmento", () => {
    const { container } = renderInspector(
      node({ type: "condition", config: { condition_type: "in_stage" } }),
    );
    expect(opcoes(container, "stage")).toContain("private_label");
    expect(opcoes(container, "stage")).not.toContain("Em conversa");
  });

  it("no_message ganha o filtro de segmento que o inspector nunca ofereceu", () => {
    const { container } = renderInspector(node({ config: { trigger_type: "no_message" } }));
    expect(opcoes(container, "stage_filter")).toContain("consumo");
  });
});

describe("template", () => {
  it("template não aprovado é SELECIONÁVEL — quem recusa é a ativação, não a seleção", () => {
    const { container } = renderInspector(node({ type: "send", config: {} }));
    const select = container.querySelector('[data-campo="template_name"] select') as HTMLSelectElement;
    const pendente = Array.from(select.options).find(o => o.value === "promo_setembro");
    expect(pendente, "o template pendente tem de estar na lista").toBeTruthy();
    expect(pendente!.disabled, "pendente não pode estar disabled").toBe(false);
  });

  it("com template pendente escolhido, o nó mostra selo de pendência", () => {
    renderInspector(node({ type: "send", config: { template_name: "promo_setembro" } }));
    expect(screen.getByText(/aguardando aprova/i)).toBeTruthy();
  });

  it("template aprovado não mostra selo", () => {
    renderInspector(node({ type: "send", config: { template_name: "boas_vindas" } }));
    expect(screen.queryByText(/aguardando aprova/i)).toBeNull();
  });
});

describe("on_reply — o gatilho manda, o nó de envio sobrepõe", () => {
  it("aparece no gatilho de card parado", () => {
    const { container } = renderInspector(node({ config: { trigger_type: "deal_stage_stagnation" } }));
    expect(opcoes(container, "on_reply")).toEqual(["pause", "cancel", "reset"]);
  });

  it("no nó de envio vem vazio por padrão e diz que sobrepõe o gatilho", () => {
    const { container } = renderInspector(node({ type: "send", config: {} }));
    const select = container.querySelector('[data-campo="on_reply"] select') as HTMLSelectElement;
    expect(select.value, "vazio = herda a política do gatilho").toBe("");
    expect(campo(container, "on_reply")!.textContent).toMatch(/herda|sobrepoe|sobrepõe/i);
  });

  it("escolher vazio no envio grava null, não string vazia", () => {
    const { container, onSave } = renderInspector(
      node({ type: "send", config: { on_reply: "cancel" } }),
    );
    const select = container.querySelector('[data-campo="on_reply"] select') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "" } });
    fireEvent.click(screen.getByText("Salvar"));
    expect(onSave).toHaveBeenCalledWith("n1", expect.objectContaining({ on_reply: null }));
  });
});

describe("campos que faltavam e campos que sobravam", () => {
  it("create_deal renderiza pipeline_id, stage_key, category e dedupe_open", async () => {
    const { container } = renderInspector(
      node({ type: "action", config: { action_type: "create_deal" } }),
    );
    for (const chave of ["title_template", "pipeline_id", "stage_key", "category", "dedupe_open"]) {
      expect(campo(container, chave), `create_deal precisa do campo ${chave}`).toBeTruthy();
    }
    await waitFor(() => expect(opcoes(container, "pipeline_id").length).toBe(2));
  });

  it("post_broadcast NÃO renderiza replied_only — ninguém lê esse campo", () => {
    const { container } = renderInspector(node({ config: { trigger_type: "post_broadcast" } }));
    expect(campo(container, "replied_only")).toBeNull();
    expect(screen.queryByText(/apenas quem respondeu/i)).toBeNull();
  });

  it("wait mostra a janela de envio como opcional e vazia", () => {
    const { container } = renderInspector(node({ type: "wait", config: { days: 3, hours: 0 } }));
    const inicio = container.querySelector('[data-campo="send_start_hour"] input') as HTMLInputElement;
    expect(inicio.value).toBe("");
    expect(campo(container, "skip_weekends")).toBeTruthy();
  });

  it("campo obrigatório é sinalizado", () => {
    const { container } = renderInspector(node({ config: { trigger_type: "stage_stagnation" } }));
    expect(campo(container, "stage_filter")!.textContent).toContain("*");
  });

  it("requer_um_de vira aviso na tela", () => {
    const { container } = renderInspector(node({ config: { trigger_type: "deal_stage_stagnation" } }));
    expect(container.textContent).toMatch(/ao menos um/i);
  });
});

describe("o seletor de subtipo também sai do schema", () => {
  it("condição oferece as nove, não uma", () => {
    const { container } = renderInspector(
      node({ type: "condition", config: { condition_type: "replied_recently" } }),
    );
    const select = container.querySelector('[data-campo="condition_type"] select') as HTMLSelectElement;
    expect(Array.from(select.options).map(o => o.value)).toEqual([
      "replied_recently", "in_stage", "has_deal", "has_tag", "sale_count",
      "total_spend", "last_sale_value", "deal_value", "repurchase_days",
    ]);
  });

  it("gatilho oferece os doze", () => {
    const { container } = renderInspector(node({ config: { trigger_type: "no_message" } }));
    const select = container.querySelector('[data-campo="trigger_type"] select') as HTMLSelectElement;
    expect(select.options).toHaveLength(12);
  });

  it("trocar de subtipo troca os campos renderizados", () => {
    const { container } = renderInspector(node({ config: { trigger_type: "stage_stagnation" } }));
    expect(opcoes(container, "stage_filter")).toContain("atacado");

    const select = container.querySelector('[data-campo="trigger_type"] select') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "deal_stage_enter" } });
    expect(opcoes(container, "stage_filter")).toContain("novo");
  });
});

describe("degradação sem o contrato", () => {
  it("schema ausente não quebra a tela", () => {
    primeNodeSchema(null);
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    const { container } = renderInspector(node({ config: { trigger_type: "stage_stagnation" } }));
    expect(container.textContent).toMatch(/contrato/i);
    expect(screen.getByText("Salvar")).toBeTruthy();
  });
});
