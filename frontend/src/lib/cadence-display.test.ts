import { describe, it, expect } from "vitest";
import { touchStateLabel, objectiveLabel, type FollowupJob } from "@/lib/cadence-display";

function job(overrides: Partial<FollowupJob>): FollowupJob {
  return {
    sequence: 1, job_type: null, status: "pending",
    fire_at: null, sent_at: null, cancel_reason: null, objetivo: null,
    ...overrides,
  };
}

describe("touchStateLabel", () => {
  it("pending → Agendado", () => {
    expect(touchStateLabel(job({ status: "pending" }))).toBe("Agendado");
  });
  it("sent → Texto enviado", () => {
    expect(touchStateLabel(job({ status: "sent" }))).toBe("Texto enviado");
  });
  it("awaiting_reopen → Template enviado", () => {
    expect(touchStateLabel(job({ status: "awaiting_reopen" }))).toBe("Template enviado");
  });
  it("cancelled + reopen_context_refreshed → Contexto atualizado", () => {
    expect(touchStateLabel(job({ status: "cancelled", cancel_reason: "reopen_context_refreshed" })))
      .toBe("Contexto atualizado");
  });
  it("cancelled other reason → Cancelado", () => {
    expect(touchStateLabel(job({ status: "cancelled", cancel_reason: "window_expired" })))
      .toBe("Cancelado");
  });
});

describe("objectiveLabel", () => {
  it("maps known slugs", () => {
    expect(objectiveLabel("reengajar")).toBe("Reengajar");
    expect(objectiveLabel("reforco_valor")).toBe("Reforço de valor");
    expect(objectiveLabel("prova_social")).toBe("Prova social");
    expect(objectiveLabel("ultima_chamada")).toBe("Última chamada");
  });
  it("unknown / null → dash", () => {
    expect(objectiveLabel(null)).toBe("—");
    expect(objectiveLabel("xpto")).toBe("—");
  });
});
