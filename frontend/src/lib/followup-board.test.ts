import { describe, expect, it } from "vitest";
import {
  displayInstant,
  formatBRT,
  isCancellable,
  offsetLabel,
  touchTypeLabel,
} from "./followup-board";

/** Os cinco job_type das esteiras do João, como o motor os grava. */
const JOB_TYPES_JOAO = [
  "joao_novo",
  "joao_em_conversa",
  "joao_proposta",
  "joao_reposicao",
  "joao_em_atencao",
];

describe("touchTypeLabel — ValerIA (não pode mudar nada)", () => {
  it("toque de cadência (job_type='standard' como o motor grava) vira T<seq>", () => {
    expect(touchTypeLabel({ job_type: "standard", sequence: 2, toque: null, acao: null })).toBe("T2");
  });
  it("job_type null (linhas antigas) também é toque de cadência", () => {
    expect(touchTypeLabel({ job_type: null, sequence: 1, toque: null, acao: null })).toBe("T1");
  });
  it("standard sem sequence continua 'Toque'", () => {
    expect(touchTypeLabel({ job_type: "standard", sequence: null, toque: null, acao: null })).toBe("Toque");
  });
  it("os quatro tipos especializados mantêm o rótulo PT de hoje", () => {
    const base = { sequence: 1, toque: null, acao: null };
    expect(touchTypeLabel({ ...base, job_type: "handoff_rescue" })).toBe("Resgate de handoff");
    expect(touchTypeLabel({ ...base, job_type: "lp_welcome" })).toBe("Boas-vindas LP");
    expect(touchTypeLabel({ ...base, job_type: "ai_reengage" })).toBe("Reengajamento IA");
    expect(touchTypeLabel({ ...base, job_type: "ai_scheduled_return" })).toBe("Retorno agendado");
  });
  it("rótulo de cadência passado por engano não contamina os tipos da ValerIA", () => {
    // O componente passa o rótulo sempre; para job que não é do João ele é ignorado.
    expect(touchTypeLabel({ job_type: "standard", sequence: 3, toque: null, acao: null }, "Novo")).toBe("T3");
    expect(
      touchTypeLabel({ job_type: "handoff_rescue", sequence: 1, toque: null, acao: null }, "Novo"),
    ).toBe("Resgate de handoff");
  });
});

describe("touchTypeLabel — esteiras do João", () => {
  it("rótulo da cadência + número do toque ('Novo · 2º toque')", () => {
    expect(
      touchTypeLabel({ job_type: "joao_novo", sequence: 2, toque: 2, acao: null }, "Novo"),
    ).toBe("Novo · 2º toque");
  });
  it("o número vem de metadata.toque, não de sequence, quando os dois divergem", () => {
    expect(
      touchTypeLabel({ job_type: "joao_em_conversa", sequence: 9, toque: 3, acao: null }, "Em Conversa"),
    ).toBe("Em Conversa · 3º toque");
  });
  it("sem metadata.toque cai em sequence (reserva)", () => {
    expect(
      touchTypeLabel({ job_type: "joao_proposta", sequence: 4, toque: null, acao: null }, "Proposta Enviada"),
    ).toBe("Proposta Enviada · 4º toque");
  });
  it("definição ainda não carregada (sem rótulo) → só o número, NUNCA a chave crua", () => {
    expect(touchTypeLabel({ job_type: "joao_novo", sequence: 1, toque: 1, acao: null })).toBe("1º toque");
    expect(touchTypeLabel({ job_type: "joao_novo", sequence: 1, toque: 1, acao: null }, null)).toBe("1º toque");
    expect(touchTypeLabel({ job_type: "joao_novo", sequence: 1, toque: 1, acao: null }, "  ")).toBe("1º toque");
  });
  it("sem rótulo e sem número não escreve 'undefined' nem a chave", () => {
    expect(touchTypeLabel({ job_type: "joao_novo", sequence: null, toque: null, acao: null })).toBe("Toque");
    expect(
      touchTypeLabel({ job_type: "joao_novo", sequence: null, toque: null, acao: null }, "Novo"),
    ).toBe("Novo");
  });
  it("o rótulo sai do parâmetro (definição), não de mapa interno: trocar o rótulo muda a saída", () => {
    const job = { job_type: "joao_reposicao", sequence: 1, toque: 1, acao: null };
    expect(touchTypeLabel(job, "Reposição")).toBe("Reposição · 1º toque");
    expect(touchTypeLabel(job, "Reposição RENOMEADA")).toBe("Reposição RENOMEADA · 1º toque");
  });

  it("A CHAVE CRUA NÃO VAZA: nenhum dos cinco job_type aparece na saída, com ou sem rótulo", () => {
    const rotulos: Array<string | null | undefined> = [undefined, null, "", "Novo"];
    for (const jt of JOB_TYPES_JOAO) {
      for (const rotulo of rotulos) {
        for (const toque of [null, 2]) {
          const saida = touchTypeLabel({ job_type: jt, sequence: 3, toque, acao: null }, rotulo);
          expect(saida).not.toContain(jt);
          expect(saida).not.toContain("joao_");
          expect(saida).not.toContain("undefined");
          expect(saida).not.toContain("null");
        }
      }
    }
  });
});

describe("touchTypeLabel — o job que move o card não é toque", () => {
  it("acao='mover_etapa' vira 'move o card'", () => {
    expect(
      touchTypeLabel(
        { job_type: "joao_reposicao", sequence: 5, toque: null, acao: "mover_etapa" },
        "Reposição",
      ),
    ).toBe("move o card");
  });
  it("não mostra número de toque — sequence é último+1, um toque que nunca existiu", () => {
    const saida = touchTypeLabel(
      { job_type: "joao_novo", sequence: 4, toque: 4, acao: "mover_etapa" },
      "Novo",
    );
    expect(saida).not.toContain("toque");
    expect(saida).not.toContain("4");
    expect(saida).not.toContain("joao_");
  });
  it("vence antes do ramo do João mesmo sem rótulo carregado", () => {
    expect(
      touchTypeLabel({ job_type: "joao_em_atencao", sequence: 3, toque: 3, acao: "mover_etapa" }),
    ).toBe("move o card");
  });
  it("outra acao qualquer não é tratada como mover", () => {
    expect(
      touchTypeLabel({ job_type: "joao_novo", sequence: 2, toque: 2, acao: "enviar_template" }, "Novo"),
    ).toBe("Novo · 2º toque");
  });
});

describe("touchTypeLabel — tipo desconhecido", () => {
  it("não esconde o tipo, mas também não escreve a chave crua", () => {
    // Antes o fallback era `?? jt` e a chave vazava para a tela. Agora vira texto legível.
    expect(touchTypeLabel({ job_type: "novo_tipo", sequence: 1, toque: null, acao: null })).toBe("Novo tipo");
    expect(touchTypeLabel({ job_type: "novo_tipo", sequence: 1, toque: null, acao: null })).not.toBe(
      "novo_tipo",
    );
  });
});

describe("isCancellable", () => {
  it("pending e awaiting_reopen são canceláveis", () => {
    expect(isCancellable({ status: "pending" })).toBe(true);
    expect(isCancellable({ status: "awaiting_reopen" })).toBe(true);
  });
  it("sent/processing/cancelled nunca são canceláveis pela UI", () => {
    expect(isCancellable({ status: "sent" })).toBe(false);
    expect(isCancellable({ status: "processing" })).toBe(false);
    expect(isCancellable({ status: "cancelled" })).toBe(false);
  });
});

describe("displayInstant", () => {
  it("enviado usa sent_at", () => {
    expect(
      displayInstant({ status: "sent", fire_at: "2026-07-10T10:00:00Z", sent_at: "2026-07-10T11:00:00Z" }),
    ).toBe("2026-07-10T11:00:00Z");
  });
  it("pendente usa fire_at", () => {
    expect(
      displayInstant({ status: "pending", fire_at: "2026-07-13T12:00:00Z", sent_at: null }),
    ).toBe("2026-07-13T12:00:00Z");
  });
});

describe("formatBRT", () => {
  it("converte UTC para BRT (dd/mm HH:MM)", () => {
    // 12:00 UTC = 09:00 BRT
    expect(formatBRT("2026-07-13T12:00:00+00:00")).toMatch(/13\/07,? 09:00/);
  });
  it("null e lixo viram travessão", () => {
    expect(formatBRT(null)).toBe("—");
    expect(formatBRT("not-a-date")).toBe("—");
  });
});

describe("offsetLabel", () => {
  it("T1: mesmo dia com faixa de jitter", () => {
    expect(offsetLabel(0, [90, 210])).toBe("mesmo dia (+1h30–3h30)");
  });
  it("nudge outbound: +18h", () => {
    expect(offsetLabel(18, null)).toBe("+18h");
  });
  it("D+1 e D+3 exatos", () => {
    expect(offsetLabel(24, null)).toBe("D+1");
    expect(offsetLabel(72, null)).toBe("D+3");
  });
  it("D+6 com resto de horas (T4 = 6d20h)", () => {
    expect(offsetLabel(164, null)).toBe("D+6 (+20h)");
  });
});
