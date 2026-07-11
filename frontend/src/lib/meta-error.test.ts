import { describe, expect, it } from "vitest";
import { describeMetaReactionError } from "./meta-error";

describe("describeMetaReactionError", () => {
  it("janela 24h fechada (131047) → mensagem amigável e status 422", () => {
    const body = JSON.stringify({
      error: { message: "Re-engagement message", code: 131047 },
    });
    const out = describeMetaReactionError(body);
    expect(out.status).toBe(422);
    expect(out.error).toMatch(/janela de 24h/i);
  });

  it("mensagem expirada p/ reação (131009) → 422", () => {
    const body = JSON.stringify({
      error: { message: "Parameter value is not valid", code: 131009 },
    });
    expect(describeMetaReactionError(body).status).toBe(422);
  });

  it("erro genérico → 502 com fallback", () => {
    const out = describeMetaReactionError('{"error":{"message":"boom","code":100}}');
    expect(out.status).toBe(502);
    expect(out.error).toMatch(/Falha ao enviar reação/);
  });

  it("corpo não-JSON não quebra", () => {
    const out = describeMetaReactionError("<html>oops</html>");
    expect(out.status).toBe(502);
  });
});
