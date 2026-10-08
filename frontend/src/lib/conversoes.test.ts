import { describe, expect, it } from "vitest";
import { STAGE_LABEL, STATUS_LABEL, PLATFORM_LABEL, traduzErro } from "./conversoes";

describe("conversoes", () => {
  it("rotula etapas, status e plataformas", () => {
    expect(STAGE_LABEL.qualified).toBe("Qualificado");
    expect(STATUS_LABEL.fora_da_janela).toBe("Fora da janela");
    expect(PLATFORM_LABEL.google).toBe("Google Ads");
  });
  it("traduz erros conhecidos", () => {
    expect(traduzErro("META_CAPI_DATASET_ID não configurado")).toMatch(/configuração/i);
    expect(traduzErro("HTTP 400: Invalid parameter")).toMatch(/recusou/i);
    expect(traduzErro("falha ao obter access token do Google")).toMatch(/autoriza/i);
    expect(traduzErro(null)).toBe("");
  });
});
