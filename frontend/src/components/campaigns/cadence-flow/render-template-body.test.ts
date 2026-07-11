import { describe, expect, it } from "vitest";
import { renderTemplateBody } from "./render-template-body";

describe("renderTemplateBody — prévia do texto real do template", () => {
  it("substitui params posicionais configurados", () => {
    const body = "Ola, {{1}}! O Cafe Canastra esta aguardando sua confirmacao sobre {{2}} desde {{3}}.";
    expect(
      renderTemplateBody(body, { "1": "Tainara", "2": "a continuidade do atendimento", "3": "09/07/2026" }),
    ).toBe(
      "Ola, Tainara! O Cafe Canastra esta aguardando sua confirmacao sobre a continuidade do atendimento desde 09/07/2026.",
    );
  });

  it("substitui params nomeados", () => {
    expect(renderTemplateBody("Olá, {{primeiro_nome}}!", { primeiro_nome: "João" })).toBe("Olá, João!");
  });

  it("placeholder sem valor configurado permanece visível", () => {
    expect(renderTemplateBody("Ola, {{1}}! Sobre {{2}}.", { "1": "Ana" })).toBe("Ola, Ana! Sobre {{2}}.");
    expect(renderTemplateBody("Ola, {{1}}!", { "1": "  " })).toBe("Ola, {{1}}!");
  });

  it("tokens dinâmicos usados como VALOR aparecem como estão (resolvidos no envio)", () => {
    expect(renderTemplateBody("Ola, {{1}}!", { "1": "{{nome}}" })).toBe("Ola, {{nome}}!");
  });

  it("body vazio/sem variáveis degrada com segurança", () => {
    expect(renderTemplateBody("", { "1": "x" })).toBe("");
    expect(renderTemplateBody("Sem placeholders.", undefined)).toBe("Sem placeholders.");
  });
});
