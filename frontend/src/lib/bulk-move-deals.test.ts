import { describe, it, expect } from "vitest";
import {
  buildMovePayload,
  chunk,
  summarizeMoveResults,
  selectableStages,
} from "./bulk-move-deals";
import type { PipelineStage } from "./types";

function stage(over: Partial<PipelineStage> & { id: string }): PipelineStage {
  return {
    pipeline_id: "p1",
    label: over.id,
    key: null,
    dot_color: "#5b8aad",
    order_index: 0,
    is_protected: false,
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

describe("buildMovePayload", () => {
  it("omite pipeline_id quando o funil nao muda", () => {
    const payload = buildMovePayload({ pipeline_id: "p1" }, "p1", "s9");
    expect(payload).toEqual({ stage_id: "s9" });
  });

  it("inclui pipeline_id quando o funil muda", () => {
    const payload = buildMovePayload({ pipeline_id: "p1" }, "p2", "s9");
    expect(payload).toEqual({ stage_id: "s9", pipeline_id: "p2" });
  });

  it("inclui pipeline_id quando o deal nao tem funil", () => {
    const payload = buildMovePayload({ pipeline_id: null }, "p2", "s9");
    expect(payload).toEqual({ stage_id: "s9", pipeline_id: "p2" });
  });
});

describe("chunk", () => {
  it("quebra 12 itens em lotes de 5", () => {
    const items = Array.from({ length: 12 }, (_, i) => i);
    expect(chunk(items, 5)).toEqual([
      [0, 1, 2, 3, 4],
      [5, 6, 7, 8, 9],
      [10, 11],
    ]);
  });

  it("devolve lista vazia para entrada vazia", () => {
    expect(chunk([], 5)).toEqual([]);
  });

  it("devolve um unico lote quando cabe tudo", () => {
    expect(chunk([1, 2], 5)).toEqual([[1, 2]]);
  });
});

describe("summarizeMoveResults", () => {
  it("conta tudo como movido quando nao ha falha", () => {
    const summary = summarizeMoveResults([
      { id: "d1", ok: true },
      { id: "d2", ok: true },
    ]);
    expect(summary).toEqual({ moved: 2, failed: 0, failedIds: [], message: "" });
  });

  it("reporta parciais com a mensagem da API", () => {
    const summary = summarizeMoveResults([
      { id: "d1", ok: true },
      { id: "d2", ok: false, error: "Permissão insuficiente para este funil." },
      { id: "d3", ok: false, error: "Permissão insuficiente para este funil." },
    ]);
    expect(summary.moved).toBe(1);
    expect(summary.failed).toBe(2);
    expect(summary.failedIds).toEqual(["d2", "d3"]);
    expect(summary.message).toBe(
      "1 de 3 deals movidos. 2 falharam: Permissão insuficiente para este funil."
    );
  });

  it("junta mensagens de erro diferentes sem repetir", () => {
    const summary = summarizeMoveResults([
      { id: "d1", ok: false, error: "Erro A" },
      { id: "d2", ok: false, error: "Erro B" },
      { id: "d3", ok: false, error: "Erro A" },
    ]);
    expect(summary.message).toBe("0 de 3 deals movidos. 3 falharam: Erro A; Erro B");
  });

  it("usa mensagem generica quando a API nao devolve erro", () => {
    const summary = summarizeMoveResults([{ id: "d1", ok: false }]);
    expect(summary.message).toBe("0 de 1 deals movidos. 1 falharam: Erro desconhecido");
  });
});

describe("selectableStages", () => {
  it("esconde etapas protegidas", () => {
    const stages = [
      stage({ id: "s1" }),
      stage({ id: "s2" }),
      stage({ id: "won", is_protected: true }),
    ];
    expect(selectableStages(stages, "s1").map((s) => s.id)).toEqual(["s1", "s2"]);
  });

  it("mantem a etapa atual mesmo protegida, na posicao original", () => {
    const stages = [
      stage({ id: "s1", order_index: 0 }),
      stage({ id: "won", is_protected: true, order_index: 1 }),
      stage({ id: "lost", is_protected: true, order_index: 2 }),
    ];
    expect(selectableStages(stages, "won").map((s) => s.id)).toEqual(["s1", "won"]);
  });

  it("aceita etapa atual nula", () => {
    const stages = [stage({ id: "s1" }), stage({ id: "won", is_protected: true })];
    expect(selectableStages(stages, null).map((s) => s.id)).toEqual(["s1"]);
  });
});
