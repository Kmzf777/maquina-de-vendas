import { describe, expect, it } from "vitest";
import {
  embedded,
  mapBroadcast,
  mapCadence,
  mapDeal,
  mapEvent,
  mapFollowup,
  mapLead,
  mapNote,
  mapSale,
} from "./lead-overview-rows";

describe("embedded", () => {
  // O PostgREST devolve a relação embutida como objeto quando a FK é única e
  // como array de um quando não consegue provar a unicidade. Ler só uma das
  // formas deixaria a etapa da oportunidade em branco sem erro nenhum.
  it("aceita a relação como objeto", () => {
    expect(embedded({ label: "Novo" })).toEqual({ label: "Novo" });
  });

  it("aceita a relação como array de um", () => {
    expect(embedded([{ label: "Novo" }])).toEqual({ label: "Novo" });
  });

  it("array vazio e nulo viram nulo", () => {
    expect(embedded([])).toBeNull();
    expect(embedded(null)).toBeNull();
    expect(embedded(undefined)).toBeNull();
  });
});

describe("mapDeal", () => {
  it("desembrulha etapa e pipeline vindos como objeto", () => {
    const d = mapDeal({
      id: "d1",
      title: "Atacado 20kg",
      value: "1500.00",
      created_at: "2026-09-03T10:00:00.000Z",
      updated_at: "2026-09-04T10:00:00.000Z",
      lost_reason: null,
      pipeline_stages: { key: "negociacao", label: "Negociacao", dot_color: "#5b8aad" },
      pipelines: { name: "Vendas" },
    });
    expect(d).toEqual({
      id: "d1",
      title: "Atacado 20kg",
      value: 1500,
      stage_key: "negociacao",
      stage_label: "Negociacao",
      dot_color: "#5b8aad",
      pipeline_name: "Vendas",
      created_at: "2026-09-03T10:00:00.000Z",
      updated_at: "2026-09-04T10:00:00.000Z",
      lost_reason: null,
    });
  });

  it("desembrulha etapa vinda como array de um", () => {
    const d = mapDeal({ id: "d1", pipeline_stages: [{ key: "novo", label: "Novo" }] });
    expect(d.stage_key).toBe("novo");
    expect(d.stage_label).toBe("Novo");
  });

  it("deal órfão de etapa não quebra — vira nulo, e a UI mostra travessão", () => {
    const d = mapDeal({ id: "d1", pipeline_stages: null, pipelines: null });
    expect(d.stage_key).toBeNull();
    expect(d.dot_color).toBeNull();
    expect(d.pipeline_name).toBeNull();
  });

  it("valor ausente ou ilegível vira zero, nunca NaN", () => {
    expect(mapDeal({ id: "d1" }).value).toBe(0);
    expect(mapDeal({ id: "d1", value: "abc" }).value).toBe(0);
  });

  it("deal sem título ganha rótulo genérico em vez de string vazia", () => {
    expect(mapDeal({ id: "d1", title: "" }).title).toBe("Oportunidade");
  });
});

describe("mapSale", () => {
  it("mapeia os campos da venda", () => {
    expect(
      mapSale({
        id: "s1",
        value: 900.5,
        product: "Microlote 1kg",
        sold_at: "2026-09-05T10:00:00.000Z",
        sold_by: "joao@canastra",
        origin: "bling",
        status: "registrada",
      }),
    ).toEqual({
      id: "s1",
      value: 900.5,
      product: "Microlote 1kg",
      sold_at: "2026-09-05T10:00:00.000Z",
      sold_by: "joao@canastra",
      origin: "bling",
      status: "registrada",
    });
  });

  it("produto vazio vira nulo — a UI decide o rótulo, não a string vazia", () => {
    expect(mapSale({ id: "s1", product: "" }).product).toBeNull();
  });
});

describe("mapEvent", () => {
  it("mapeia o evento", () => {
    expect(
      mapEvent({
        id: "e1",
        event_type: "stage_change",
        old_value: "secretaria",
        new_value: "atacado",
        created_at: "2026-09-02T10:00:00.000Z",
      }),
    ).toEqual({
      id: "e1",
      event_type: "stage_change",
      old_value: "secretaria",
      new_value: "atacado",
      created_at: "2026-09-02T10:00:00.000Z",
    });
  });

  it("evento sem tipo ganha rótulo genérico", () => {
    expect(mapEvent({ id: "e1", created_at: "2026-09-02T10:00:00.000Z" }).event_type).toBe("evento");
  });
});

describe("mapNote", () => {
  it("mapeia a nota", () => {
    expect(
      mapNote({ id: "n1", author: "João", content: "ligou", created_at: "2026-09-06T10:00:00.000Z" }),
    ).toEqual({
      id: "n1",
      author: "João",
      content: "ligou",
      created_at: "2026-09-06T10:00:00.000Z",
    });
  });
});

describe("mapCadence", () => {
  it("puxa o nome da campanha embutida", () => {
    expect(
      mapCadence({
        id: "ce1",
        status: "active",
        enrolled_at: "2026-09-02T10:00:00.000Z",
        campaigns: { name: "Reativação Bling" },
      }),
    ).toEqual({
      id: "ce1",
      name: "Reativação Bling",
      status: "active",
      enrolled_at: "2026-09-02T10:00:00.000Z",
    });
  });

  it("campanha apagada não deixa a inscrição sem nome", () => {
    expect(mapCadence({ id: "ce1", campaigns: null }).name).toBe("Cadência");
  });
});

describe("mapBroadcast", () => {
  it("renomeia `status` da linha para `message_status` e puxa o nome do disparo", () => {
    // A coluna `status` de broadcast_leads é o status da MENSAGEM daquele lead,
    // não o do disparo. Manter os dois com o mesmo nome já confundiu leitura antes.
    expect(
      mapBroadcast({
        id: "bl1",
        status: "sent",
        sent_at: "2026-09-04T10:00:00.000Z",
        first_replied_at: null,
        broadcasts: [{ name: "Black Friday" }],
      }),
    ).toEqual({
      id: "bl1",
      name: "Black Friday",
      message_status: "sent",
      sent_at: "2026-09-04T10:00:00.000Z",
      first_replied_at: null,
    });
  });
});

describe("mapFollowup", () => {
  it("extrai o objetivo de dentro do metadata", () => {
    const f = mapFollowup({
      sequence: 2,
      job_type: "standard",
      status: "sent",
      fire_at: "2026-09-03T09:00:00.000Z",
      sent_at: "2026-09-03T10:00:00.000Z",
      metadata: { objetivo: "reengajar" },
    });
    expect(f.objetivo).toBe("reengajar");
    expect(f.sequence).toBe(2);
  });

  it("metadata ausente não explode", () => {
    expect(mapFollowup({ sequence: 1 }).objetivo).toBeNull();
  });

  it("sequence ilegível vira nulo em vez de NaN", () => {
    expect(mapFollowup({ sequence: null }).sequence).toBeNull();
  });
});

describe("mapLead", () => {
  it("mapeia o cadastro e normaliza vazios para nulo", () => {
    const l = mapLead({
      id: "lead-1",
      name: "Padaria do Zé",
      phone: "5534988861441",
      company: "",
      email: null,
      stage: "secretaria",
      status: "active",
      channel: "evolution",
      assigned_to: null,
      created_at: "2026-09-01T12:00:00.000Z",
      last_msg_at: "2026-09-07T12:00:00.000Z",
      last_customer_message_at: "2026-09-07T11:00:00.000Z",
      first_response_at: null,
      entered_stage_at: null,
      utm_source: "google",
      utm_medium: "cpc",
      utm_campaign: "atacado-brasil",
      traffic_type: "paid",
      notes: null,
    });
    expect(l.id).toBe("lead-1");
    expect(l.company).toBeNull();
    expect(l.utm_campaign).toBe("atacado-brasil");
    expect(l.created_at).toBe("2026-09-01T12:00:00.000Z");
  });
});
