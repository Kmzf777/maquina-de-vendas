import { describe, expect, it } from "vitest";
import { resolveEffectivePipelineId } from "@/lib/deal-patch-guard";

/**
 * O corpo do PATCH real carrega muito mais que o funil (stage_id, title, value...).
 * Este passa-fora existe só para escapar do excess property check do TS em literal: a
 * assinatura de resolveEffectivePipelineId declara de propósito apenas o campo que ela lê.
 */
function corpo(body: { pipeline_id?: string | null; stage_id?: string }) {
  return body;
}

describe("resolveEffectivePipelineId", () => {
  it("só stage_id no corpo → a etapa tem que pertencer ao funil ATUAL do deal", () => {
    expect(
      resolveEffectivePipelineId(corpo({ stage_id: "s-1" }), { pipeline_id: "p-atacado" })
    ).toBe("p-atacado");
  });

  it("pipeline_id + stage_id no mesmo corpo (mover e trocar etapa) → funil do CORPO", () => {
    expect(
      resolveEffectivePipelineId(
        corpo({ pipeline_id: "p-reposicao", stage_id: "r-contato" }),
        { pipeline_id: "p-atacado" }
      )
    ).toBe("p-reposicao");
  });

  it("pipeline_id: null explícito no corpo → cai no funil atual (não é 'tirar do funil')", () => {
    expect(
      resolveEffectivePipelineId(corpo({ pipeline_id: null, stage_id: "a-qualif" }), {
        pipeline_id: "p-atacado",
      })
    ).toBe("p-atacado");
  });

  it("pipeline_id vazio no corpo → cai no funil atual (mesma truthiness do guard de destino da rota)", () => {
    expect(
      resolveEffectivePipelineId(corpo({ pipeline_id: "", stage_id: "a-qualif" }), {
        pipeline_id: "p-atacado",
      })
    ).toBe("p-atacado");
  });

  it("corpo sem funil e deal legado sem funil → null (a trava não bloqueia esses deals)", () => {
    expect(resolveEffectivePipelineId(corpo({}), { pipeline_id: null })).toBeNull();
  });

  it("pipeline_id: null no corpo e deal legado sem funil → null", () => {
    expect(resolveEffectivePipelineId(corpo({ pipeline_id: null }), { pipeline_id: null })).toBeNull();
  });

  it("deal legado sem funil ganhando funil pelo corpo → funil do corpo", () => {
    expect(
      resolveEffectivePipelineId(corpo({ pipeline_id: "p-atacado", stage_id: "a-entrada" }), {
        pipeline_id: null,
      })
    ).toBe("p-atacado");
  });

  it("mesmo funil repetido no corpo → o mesmo funil", () => {
    expect(
      resolveEffectivePipelineId(
        corpo({ pipeline_id: "p-atacado", stage_id: "a-qualif" }),
        { pipeline_id: "p-atacado" }
      )
    ).toBe("p-atacado");
  });
});
