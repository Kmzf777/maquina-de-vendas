import { describe, expect, it } from "vitest";
import { describeNode } from "./describe-node";

describe("describeNode — linguagem de operador por tipo de nó", () => {
  it("trigger no_message com dias e com silêncio (days 0)", () => {
    expect(describeNode("trigger", { trigger_type: "no_message", days: 30 })).toBe(
      "Inicia o fluxo quando o lead fica 30 dias sem mandar mensagem.",
    );
    expect(describeNode("trigger", { trigger_type: "no_message", days: 0 })).toContain("silêncio");
  });

  it("trigger keyword_received lista as palavras", () => {
    expect(
      describeNode("trigger", { trigger_type: "keyword_received", keywords: ["preço", "catálogo"] }),
    ).toContain("preço, catálogo");
  });

  it("send: template, idioma, reação à resposta e regra da janela", () => {
    const s = describeNode("send", {
      template_name: "utilidade_geral_confirmacao_v1",
      template_language: "en_US",
      on_reply: "pause",
    });
    expect(s).toContain('"utilidade_geral_confirmacao_v1"');
    expect(s).toContain("(en_US)");
    expect(s).toContain("PAUSA");
    expect(s).toContain("janela de 24h fechada");
  });

  it("send_text: prévia truncada, cancelamento na resposta e exigência de janela aberta", () => {
    const longo = "a".repeat(200);
    const s = describeNode("send_text", { message_text: longo, on_reply: "cancel" });
    expect(s).toContain("a".repeat(140) + "…");
    expect(s).toContain("CANCELADO");
    expect(s).toContain("janela de 24h");
    expect(s).toContain("ABERTA");
  });

  it("send_text vazio avisa em vez de mostrar aspas vazias", () => {
    expect(describeNode("send_text", { message_text: "" })).toContain("(mensagem vazia)");
  });

  it("wait: dias (singular/plural) e janela de horário", () => {
    expect(describeNode("wait", { days: 1, send_start_hour: 9, send_end_hour: 16 })).toBe(
      "Espera 1 dia antes do próximo passo; o passo seguinte só sai entre 9h e 16h.",
    );
    expect(describeNode("wait", { days: 3, send_start_hour: 7, send_end_hour: 18 })).toContain("3 dias");
  });

  it("wait com HORAS: combinação dias+horas e espera sub-diária (11/07)", () => {
    expect(describeNode("wait", { days: 3, hours: 20, send_start_hour: 9, send_end_hour: 16 })).toContain(
      "Espera 3 dias e 20 horas",
    );
    expect(describeNode("wait", { days: 0, hours: 2, send_start_hour: 9, send_end_hour: 16 })).toContain(
      "Espera 2 horas",
    );
    expect(describeNode("wait", { days: 0, hours: 1, send_start_hour: 9, send_end_hour: 16 })).toContain(
      "Espera 1 hora ",
    );
  });

  it("condition replied_recently menciona a regra e os ramos", () => {
    const s = describeNode("condition", { condition_type: "replied_recently", days: 1 });
    expect(s).toContain("respondeu nos últimos 1 dia");
    expect(s).toContain("SIM");
    expect(s).toContain("NÃO");
  });

  it("condition numérica com operador", () => {
    expect(
      describeNode("condition", { condition_type: "total_spend", operator: "gte", value: 500 }),
    ).toContain("total gasto pelo lead é ≥ R$ 500");
  });

  it("action usa o rótulo humano e o alvo", () => {
    expect(describeNode("action", { action_type: "add_tag", tag_name: "VIP" })).toContain('Adicionar tag — "VIP"');
  });

  it("end mostra o rótulo e as ações finais quando existem", () => {
    expect(describeNode("end", { label: "Cadência concluída", final_actions: [] })).toBe(
      'Encerra o fluxo aqui: "Cadência concluída".',
    );
    expect(describeNode("end", { label: "Fim", final_actions: [{}, {}] })).toContain("2 ação(ões)");
  });
});
