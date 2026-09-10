import { describe, expect, it } from "vitest";
import {
  buildJourney,
  buildMovements,
  computeVitals,
  formatEventText,
  humanDuration,
  stageLabel,
  type LeadOverview,
} from "./lead-overview";

// ─── Fixtures ──────────────────────────────────────────────────────────────────

const LEAD_CRIADO_EM = "2026-09-01T12:00:00.000Z";
/** 8 dias depois da criação do lead. Base de todos os cálculos de "agora". */
const AGORA = Date.parse("2026-09-09T12:00:00.000Z");

function overview(patch: Partial<LeadOverview> = {}): LeadOverview {
  return {
    lead: {
      id: "lead-1",
      name: "Padaria do Zé",
      phone: "5534988861441",
      company: null,
      email: null,
      stage: "secretaria",
      status: "active",
      channel: "evolution",
      assigned_to: null,
      created_at: LEAD_CRIADO_EM,
      last_msg_at: null,
      last_customer_message_at: null,
      first_response_at: null,
      entered_stage_at: null,
      utm_source: "google",
      utm_medium: "cpc",
      utm_campaign: "atacado-brasil",
      traffic_type: "paid",
      notes: null,
      ...patch.lead,
    },
    deals: patch.deals ?? [],
    sales: patch.sales ?? [],
    events: patch.events ?? [],
    notes: patch.notes ?? [],
    messages: {
      total: 0,
      inbound: 0,
      outbound: 0,
      first_inbound_at: null,
      last_at: null,
      ...patch.messages,
    },
    cadences: patch.cadences ?? [],
    broadcasts: patch.broadcasts ?? [],
    followups: patch.followups ?? [],
  };
}

const deal = (p: Partial<LeadOverview["deals"][number]> = {}) => ({
  id: "deal-1",
  title: "Atacado — 20kg",
  value: 1500,
  stage_key: "negociacao",
  stage_label: "Negociacao",
  dot_color: "#5b8aad",
  pipeline_name: "Vendas",
  created_at: "2026-09-03T10:00:00.000Z",
  updated_at: "2026-09-04T10:00:00.000Z",
  lost_reason: null,
  ...p,
});

const sale = (p: Partial<LeadOverview["sales"][number]> = {}) => ({
  id: "sale-1",
  value: 900,
  product: "Microlote 1kg",
  sold_at: "2026-09-05T10:00:00.000Z",
  sold_by: "joao@canastra",
  origin: "crm",
  status: "confirmed",
  ...p,
});

// ─── stageLabel ────────────────────────────────────────────────────────────────

describe("stageLabel", () => {
  it("traduz etapa de funil gravada em pipeline_stages", () => {
    expect(stageLabel("fechado_ganho")).toBe("Fechado Ganho");
    expect(stageLabel("proposta_enviada")).toBe("Proposta Enviada");
  });

  it("traduz etapa do agente (leads.stage)", () => {
    expect(stageLabel("secretaria")).toBe("Secretaria");
    expect(stageLabel("private_label")).toBe("Private Label");
  });

  it("etapa desconhecida cai no próprio slug — a UI nunca esconde o dado cru", () => {
    expect(stageLabel("etapa_que_ainda_nao_existe")).toBe("etapa_que_ainda_nao_existe");
  });

  it("sem etapa vira travessão", () => {
    expect(stageLabel(null)).toBe("—");
    expect(stageLabel("")).toBe("—");
  });
});

// ─── humanDuration ─────────────────────────────────────────────────────────────

describe("humanDuration", () => {
  it("abaixo de um minuto não vira '0 min'", () => {
    expect(humanDuration(30_000)).toBe("<1 min");
  });

  it("minutos, horas e dias truncam para baixo", () => {
    expect(humanDuration(5 * 60_000)).toBe("5 min");
    expect(humanDuration(3 * 3_600_000 + 59 * 60_000)).toBe("3 h");
    expect(humanDuration(50 * 3_600_000)).toBe("2 d");
  });

  it("nulo e duração negativa (relógio torto) viram travessão", () => {
    expect(humanDuration(null)).toBe("—");
    expect(humanDuration(-1000)).toBe("—");
  });
});

// ─── formatEventText ───────────────────────────────────────────────────────────

describe("formatEventText", () => {
  it("stage_change mostra os rótulos, não os slugs", () => {
    expect(
      formatEventText({ event_type: "stage_change", old_value: "secretaria", new_value: "atacado" }),
    ).toBe("Etapa do agente: Secretaria → Atacado");
  });

  it("eventos de funil e de cadência ganham texto em PT", () => {
    expect(
      formatEventText({ event_type: "deal_stage_change", old_value: "novo", new_value: "proposta" }),
    ).toBe("Oportunidade: Novo → Proposta");
    expect(
      formatEventText({ event_type: "cadence_enrolled", old_value: null, new_value: "Reativação" }),
    ).toBe("Entrou na cadência Reativação");
    expect(formatEventText({ event_type: "first_response", old_value: null, new_value: null })).toBe(
      "Primeira resposta recebida",
    );
  });

  it("tipo desconhecido cai no próprio slug (nunca esconde)", () => {
    expect(formatEventText({ event_type: "tipo_novo", old_value: null, new_value: null })).toBe(
      "tipo_novo",
    );
  });
});

// ─── computeVitals ─────────────────────────────────────────────────────────────

describe("computeVitals", () => {
  it("conta dias no CRM a partir da criação do lead", () => {
    expect(computeVitals(overview(), AGORA).diasNoCrm).toBe(8);
  });

  it("soma receita, pedidos e ticket médio das vendas", () => {
    const v = computeVitals(
      overview({ sales: [sale({ id: "s1", value: 900 }), sale({ id: "s2", value: 300 })] }),
      AGORA,
    );
    expect(v.receita).toBe(1200);
    expect(v.pedidos).toBe(2);
    expect(v.ticketMedio).toBe(600);
  });

  it("ticket médio de lead sem venda é zero, não NaN", () => {
    expect(computeVitals(overview(), AGORA).ticketMedio).toBe(0);
  });

  it("pipeline aberto ignora oportunidades já fechadas (ganhas ou perdidas)", () => {
    const v = computeVitals(
      overview({
        deals: [
          deal({ id: "d1", value: 1500, stage_key: "negociacao" }),
          deal({ id: "d2", value: 9000, stage_key: "fechado_ganho" }),
          deal({ id: "d3", value: 7000, stage_key: "fechado_perdido" }),
        ],
      }),
      AGORA,
    );
    expect(v.pipelineAberto).toBe(1500);
    expect(v.dealsAbertos).toBe(1);
    expect(v.dealsTotal).toBe(3);
  });

  it("mede o tempo até o lead falar e o tempo até a nossa primeira resposta", () => {
    const v = computeVitals(
      overview({
        lead: { first_response_at: "2026-09-01T12:30:00.000Z" } as LeadOverview["lead"],
        messages: { first_inbound_at: "2026-09-01T12:05:00.000Z" } as LeadOverview["messages"],
      }),
      AGORA,
    );
    expect(v.tempoAteContatoMs).toBe(5 * 60_000);
    expect(v.tempoAteRespostaMs).toBe(30 * 60_000);
  });

  it("sem primeira resposta registrada os tempos são nulos (não zero)", () => {
    const v = computeVitals(overview(), AGORA);
    expect(v.tempoAteContatoMs).toBeNull();
    expect(v.tempoAteRespostaMs).toBeNull();
  });

  it("inatividade parte da última mensagem da conversa", () => {
    const v = computeVitals(
      overview({ lead: { last_msg_at: "2026-09-07T12:00:00.000Z" } as LeadOverview["lead"] }),
      AGORA,
    );
    expect(v.inatividadeMs).toBe(2 * 24 * 3_600_000);
  });

  it("repassa a contagem de mensagens e o engajamento em outros canais", () => {
    const v = computeVitals(
      overview({
        messages: { total: 12, inbound: 5, outbound: 7 } as LeadOverview["messages"],
        cadences: [{ id: "c1", name: "Reativação", status: "active", enrolled_at: null }],
        broadcasts: [
          { id: "b1", name: "Black Friday", message_status: "sent", sent_at: null, first_replied_at: null },
        ],
        notes: [{ id: "n1", author: "João", content: "ligou", created_at: "2026-09-02T10:00:00.000Z" }],
      }),
      AGORA,
    );
    expect(v.mensagens).toEqual({ total: 12, inbound: 5, outbound: 7 });
    expect(v.cadencias).toBe(1);
    expect(v.disparos).toBe(1);
    expect(v.notas).toBe(1);
  });
});

// ─── buildJourney ──────────────────────────────────────────────────────────────

describe("buildJourney", () => {
  it("lead recém-criado só cumpriu a entrada e para aí", () => {
    const { steps, stalledAt } = buildJourney(overview());
    expect(steps.map((s) => s.reached)).toEqual([true, false, false, false]);
    expect(stalledAt).toBe(0);
  });

  it("'Conversou' segue o mesmo critério do relatório: o cliente falou", () => {
    const { steps, stalledAt } = buildJourney(
      overview({
        lead: { last_customer_message_at: "2026-09-02T10:00:00.000Z" } as LeadOverview["lead"],
      }),
    );
    expect(steps[1].reached).toBe(true);
    expect(stalledAt).toBe(1);
  });

  it("mensagem só nossa (outbound) não conta como conversa", () => {
    const { steps } = buildJourney(
      overview({ messages: { total: 3, outbound: 3 } as LeadOverview["messages"] }),
    );
    expect(steps[1].reached).toBe(false);
  });

  it("venda sem oportunidade preenche as etapas anteriores — o funil nunca fica furado", () => {
    // Venda vinda do Bling costuma chegar sem deal no CRM. Sem monotonicidade a
    // trilha mostraria "comprou mas nunca virou oportunidade", que lê como bug.
    const { steps, stalledAt } = buildJourney(overview({ sales: [sale()] }));
    expect(steps.map((s) => s.reached)).toEqual([true, true, true, true]);
    expect(stalledAt).toBeNull();
  });

  it("carimba a data de cada etapa alcançada", () => {
    const { steps } = buildJourney(
      overview({
        messages: { first_inbound_at: "2026-09-02T10:00:00.000Z" } as LeadOverview["messages"],
        deals: [deal()],
        sales: [sale()],
      }),
    );
    expect(steps[0].at).toBe(LEAD_CRIADO_EM);
    expect(steps[1].at).toBe("2026-09-02T10:00:00.000Z");
    expect(steps[2].at).toBe("2026-09-03T10:00:00.000Z");
    expect(steps[3].at).toBe("2026-09-05T10:00:00.000Z");
  });
});

// ─── buildMovements ────────────────────────────────────────────────────────────

describe("buildMovements", () => {
  it("junta todas as fontes numa linha do tempo decrescente", () => {
    const movs = buildMovements(
      overview({
        events: [
          {
            id: "e1",
            event_type: "stage_change",
            old_value: "secretaria",
            new_value: "atacado",
            created_at: "2026-09-02T10:00:00.000Z",
          },
        ],
        notes: [{ id: "n1", author: "João", content: "ligou", created_at: "2026-09-06T10:00:00.000Z" }],
        deals: [deal()],
        sales: [sale()],
        broadcasts: [
          {
            id: "b1",
            name: "Black Friday",
            message_status: "sent",
            sent_at: "2026-09-04T10:00:00.000Z",
            first_replied_at: null,
          },
        ],
      }),
    );
    expect(movs.map((m) => m.kind)).toEqual([
      "nota",
      "venda",
      "disparo",
      "oportunidade",
      "evento",
      "entrada",
    ]);
  });

  it("a criação do lead é sempre o item mais antigo da trilha", () => {
    const movs = buildMovements(overview());
    expect(movs).toHaveLength(1);
    expect(movs[0].kind).toBe("entrada");
    expect(movs[0].at).toBe(LEAD_CRIADO_EM);
  });

  it("descarta itens sem data em vez de jogá-los para 1970", () => {
    const movs = buildMovements(
      overview({
        sales: [sale({ sold_at: null })],
        broadcasts: [
          { id: "b1", name: "Fila", message_status: "queued", sent_at: null, first_replied_at: null },
        ],
        followups: [
          { sequence: 1, job_type: "standard", status: "pending", fire_at: null, sent_at: null, objetivo: null },
        ],
      }),
    );
    expect(movs.map((m) => m.kind)).toEqual(["entrada"]);
  });

  it("follow-up só entra na trilha depois de enviado", () => {
    const movs = buildMovements(
      overview({
        followups: [
          {
            sequence: 2,
            job_type: "standard",
            status: "sent",
            fire_at: "2026-09-03T09:00:00.000Z",
            sent_at: "2026-09-03T10:00:00.000Z",
            objetivo: "reengajar",
          },
          {
            sequence: 3,
            job_type: "standard",
            status: "pending",
            fire_at: "2026-09-20T09:00:00.000Z",
            sent_at: null,
            objetivo: null,
          },
        ],
      }),
    );
    const followups = movs.filter((m) => m.kind === "followup");
    expect(followups).toHaveLength(1);
    expect(followups[0].at).toBe("2026-09-03T10:00:00.000Z");
  });

  it("status da cadência aparece traduzido, não como enum cru", () => {
    const movs = buildMovements(
      overview({
        cadences: [{ id: "c1", name: "Reativação", status: "active", enrolled_at: "2026-09-02T10:00:00.000Z" }],
      }),
    );
    expect(movs.find((m) => m.kind === "cadencia")!.detail).toBe("ativa");
  });

  it("status de cadência desconhecido cai no próprio slug (nunca esconde)", () => {
    const movs = buildMovements(
      overview({
        cadences: [{ id: "c1", name: "X", status: "status_novo", enrolled_at: "2026-09-02T10:00:00.000Z" }],
      }),
    );
    expect(movs.find((m) => m.kind === "cadencia")!.detail).toBe("status_novo");
  });

  it("venda mostra o valor no título e o produto no detalhe", () => {
    const movs = buildMovements(overview({ sales: [sale({ value: 1234.5, product: "Microlote 1kg" })] }));
    const venda = movs.find((m) => m.kind === "venda")!;
    expect(venda.title).toContain("1.234,50");
    expect(venda.detail).toBe("Microlote 1kg");
  });
});
