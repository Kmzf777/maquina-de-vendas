import { describe, it, expect } from "vitest";
import { STATUS_CONFIG } from "./cadence-execution-log";

// O motor grava quatro status em campaign_execution_log. Um status ausente do mapa
// cai no `?? STATUS_CONFIG.done` do LogEntry e é pintado de verde "OK" — foi assim
// que `cancelled` (encerramento pela guarda de etapa) aparecia como sucesso.
const STATUS_DO_MOTOR = ["done", "failed", "skipped", "cancelled"];

describe("STATUS_CONFIG do log de execução", () => {
  it("conhece todos os status que o motor grava", () => {
    for (const status of STATUS_DO_MOTOR) {
      expect(STATUS_CONFIG[status], `status ${status}`).toBeDefined();
    }
  });

  it("cancelled não se parece com sucesso nem com falha", () => {
    const cancelled = STATUS_CONFIG.cancelled;
    expect(cancelled.label).toBe("ENCERRADO");
    expect(cancelled.dot).not.toBe(STATUS_CONFIG.done.dot);
    expect(cancelled.dot).not.toBe(STATUS_CONFIG.failed.dot);
    expect(cancelled.bg).not.toBe(STATUS_CONFIG.done.bg);
  });

  it("toda entrada tem rótulo curto para a pílula do resumo", () => {
    for (const [status, cfg] of Object.entries(STATUS_CONFIG)) {
      expect(cfg.short, `short de ${status}`).toBeTruthy();
    }
  });
});
