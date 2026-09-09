import { describe, it, expect } from "vitest";
import { readButtonClick } from "@/lib/button-click";

describe("readButtonClick", () => {
  it("clique de template: título vem do metadata e o payload igual ao rótulo é omitido", () => {
    // Quick reply de TEMPLATE: sem parâmetro `payload` no componente, a Meta devolve
    // payload = texto do botão (meta_parser.py:138-149). Repetir na tela seria ruído.
    expect(
      readButtonClick({
        message_type: "button",
        content: "Preciso repor",
        metadata: { payload: "Preciso repor", title: "Preciso repor" },
      })
    ).toEqual({ title: "Preciso repor", payload: null });
  });

  it("clique de interativa nossa: payload é o id do botão e aparece", () => {
    expect(
      readButtonClick({
        message_type: "button",
        content: "Ainda tenho estoque",
        metadata: { payload: "adiar", title: "Ainda tenho estoque" },
      })
    ).toEqual({ title: "Ainda tenho estoque", payload: "adiar" });
  });

  it("texto digitado com o mesmo conteúdo NÃO é clique", () => {
    expect(
      readButtonClick({ message_type: "text", content: "Preciso repor", metadata: null })
    ).toBeNull();
  });

  it("mensagem legada (98 cliques gravados como texto puro) segue como texto", () => {
    // message_type NULL + metadata NULL: não há como reconstituir o clique, e inventar
    // um chip para elas seria mentir.
    expect(
      readButtonClick({ message_type: null, content: "Continuar atendimento", metadata: null })
    ).toBeNull();
  });

  it("sem metadata usa o content como rótulo", () => {
    expect(
      readButtonClick({ message_type: "button", content: "Parar mensagens", metadata: null })
    ).toEqual({ title: "Parar mensagens", payload: null });
  });

  it("metadata não-objeto (jsonb aceita array/escalar) não quebra", () => {
    expect(
      readButtonClick({
        message_type: "button",
        content: "Manter cadastro",
        metadata: [] as unknown as Record<string, unknown>,
      })
    ).toEqual({ title: "Manter cadastro", payload: null });
  });

  it("rótulo em branco cai fora — bolha volta a ser texto", () => {
    expect(
      readButtonClick({ message_type: "button", content: "   ", metadata: { title: "  " } })
    ).toBeNull();
  });

  it("outras mídias continuam intocadas", () => {
    for (const tipo of ["audio", "image", "reaction", "document", "template"]) {
      expect(readButtonClick({ message_type: tipo, content: "x", metadata: {} })).toBeNull();
    }
  });
});
