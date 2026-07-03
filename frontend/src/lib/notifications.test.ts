import { describe, it, expect } from "vitest";
import { shouldNotifyForMessage, isChannelAllowed, truncate } from "./notifications";

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

describe("isChannelAllowed", () => {
  it("admin (allowed=null) pode ver qualquer canal", () => {
    expect(isChannelAllowed("ch-1", null)).toBe(true);
    // Mesmo canal não resolvido: admin não tem restrição de escopo.
    expect(isChannelAllowed(null, null)).toBe(true);
  });

  it("vendedor só vê canais da própria lista", () => {
    expect(isChannelAllowed("ch-1", ["ch-1", "ch-2"])).toBe(true);
    expect(isChannelAllowed("ch-3", ["ch-1", "ch-2"])).toBe(false);
  });

  it("vendedor sem canais (lista vazia) nunca é notificado", () => {
    expect(isChannelAllowed("ch-1", [])).toBe(false);
  });

  // Fail-closed: enquanto o escopo não carrega (ou se a busca falhou),
  // NENHUMA notificação dispara — nunca vazar por padrão.
  it("escopo não carregado (undefined) bloqueia tudo", () => {
    expect(isChannelAllowed("ch-1", undefined)).toBe(false);
    expect(isChannelAllowed(null, undefined)).toBe(false);
  });

  // Fail-closed: conversa sem canal resolvido não notifica vendedor.
  it("canal não resolvido bloqueia para vendedor", () => {
    expect(isChannelAllowed(null, ["ch-1"])).toBe(false);
    expect(isChannelAllowed(undefined, ["ch-1"])).toBe(false);
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
