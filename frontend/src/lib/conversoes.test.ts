import { describe, expect, it } from "vitest";
import { STAGE_LABEL, STATUS_LABEL, PLATFORM_LABEL, traduzErro } from "./conversoes";

describe("conversoes", () => {
  it("rotula etapas, status e plataformas", () => {
    expect(STAGE_LABEL.qualified).toBe("Qualificado");
    expect(STATUS_LABEL.fora_da_janela).toBe("Fora da janela");
    expect(PLATFORM_LABEL.google).toBe("Google Ads");
  });
  it("traduz erros conhecidos", () => {
    expect(traduzErro("META_CAPI_DATASET_ID não configurado", "meta")).toMatch(/configuração/i);
    expect(traduzErro("HTTP 400: Invalid parameter", "meta")).toMatch(/recusou/i);
    expect(traduzErro("falha ao obter access token do Google", "google")).toBe(
      "O Google recusou a autorização — regerar o refresh token.",
    );
    expect(traduzErro(null, "google")).toBe("");
  });
  it("erro de token da Meta não manda regerar o refresh token do Google", () => {
    const meta = traduzErro("HTTP 400: Error validating access token: Session has expired", "meta");
    expect(meta).toBe("O Meta recusou o token — gerar um novo token de usuário do sistema.");
    expect(traduzErro("HTTP 400: Invalid OAuth access token - Cannot parse access token", "meta")).toBe(meta);
    expect(traduzErro("HTTP 400: Error validating access token", "meta")).not.toMatch(/refresh token/i);
  });
});
