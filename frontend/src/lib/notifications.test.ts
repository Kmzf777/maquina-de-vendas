import { describe, it, expect } from "vitest";
import { shouldNotifyForMessage, truncate } from "./notifications";

describe("shouldNotifyForMessage", () => {
  it("notifica mensagens do contato (role=user)", () => {
    expect(shouldNotifyForMessage({ role: "user" })).toBe(true);
  });

  it("NÃO notifica respostas da IA (role=assistant)", () => {
    expect(shouldNotifyForMessage({ role: "assistant" })).toBe(false);
  });

  it("NÃO notifica mensagens de sistema (role=system)", () => {
    expect(shouldNotifyForMessage({ role: "system" })).toBe(false);
  });

  it("NÃO notifica quando role está ausente", () => {
    expect(shouldNotifyForMessage({})).toBe(false);
    expect(shouldNotifyForMessage({ role: null })).toBe(false);
  });

  // Garante a mudança de escopo: o alerta NÃO depende mais de ai_enabled.
  // Antes, mensagens de user com IA ligada eram silenciadas; agora notificam.
  it("notifica user independentemente de qualquer estado de IA", () => {
    expect(shouldNotifyForMessage({ role: "user" })).toBe(true);
  });
});

describe("truncate", () => {
  it("mantém textos curtos intactos", () => {
    expect(truncate("oi", 80)).toBe("oi");
  });

  it("mantém texto de tamanho exatamente igual ao limite", () => {
    expect(truncate("abc", 3)).toBe("abc");
  });

  it("corta e anexa reticências quando excede o limite", () => {
    expect(truncate("abcdef", 3)).toBe("abc...");
  });
});
