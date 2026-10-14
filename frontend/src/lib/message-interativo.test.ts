import { describe, it, expect } from "vitest";
import { readInterativo, carrosselCorpo } from "@/lib/message-interativo";

function bot(metadata: unknown, over: Record<string, unknown> = {}) {
  return { role: "assistant", message_type: null, metadata, ...over } as Parameters<
    typeof readInterativo
  >[0];
}

describe("readInterativo", () => {
  it("botões com imagem", () => {
    expect(
      readInterativo(
        bot({
          interativo: {
            tipo: "botoes",
            imagem: "https://cdn.example/f.jpg",
            botoes: ["Fazer pedido", "Provar antes", "Tenho dúvida"],
          },
        })
      )
    ).toEqual({
      tipo: "botoes",
      imagem: "https://cdn.example/f.jpg",
      botoes: ["Fazer pedido", "Provar antes", "Tenho dúvida"],
    });
  });

  it("botões sem imagem (null) e rótulo vazio/não-texto descartado", () => {
    expect(
      readInterativo(bot({ interativo: { tipo: "botoes", imagem: null, botoes: ["Sim", "", 3, null] } }))
    ).toEqual({ tipo: "botoes", imagem: null, botoes: ["Sim"] });
  });

  it("imagem que não é URL http(s) vira null", () => {
    expect(
      readInterativo(bot({ interativo: { tipo: "botoes", imagem: "javascript:alert(1)", botoes: ["Sim"] } }))
    ).toEqual({ tipo: "botoes", imagem: null, botoes: ["Sim"] });
  });

  it("botões sem nenhum rótulo válido = nada", () => {
    expect(readInterativo(bot({ interativo: { tipo: "botoes", botoes: [] } }))).toBeNull();
    expect(readInterativo(bot({ interativo: { tipo: "botoes", botoes: "Sim" } }))).toBeNull();
  });

  it("lista: descrição ausente vira string vazia e linha sem título sai", () => {
    expect(
      readInterativo(
        bot({
          interativo: {
            tipo: "lista",
            botao: "Ver opções",
            linhas: [
              { titulo: "Pro meu negócio", descricao: "revenda, cafeteria" },
              { titulo: "Pra minha casa" },
              { descricao: "sem título" },
              "lixo",
            ],
          },
        })
      )
    ).toEqual({
      tipo: "lista",
      botao: "Ver opções",
      linhas: [
        { titulo: "Pro meu negócio", descricao: "revenda, cafeteria" },
        { titulo: "Pra minha casa", descricao: "" },
      ],
    });
  });

  it("lista sem rótulo do botão usa o default do WhatsApp; sem linhas = nada", () => {
    expect(
      readInterativo(bot({ interativo: { tipo: "lista", linhas: [{ titulo: "A" }] } }))
    ).toEqual({ tipo: "lista", botao: "Ver opções", linhas: [{ titulo: "A", descricao: "" }] });
    expect(readInterativo(bot({ interativo: { tipo: "lista", botao: "X", linhas: [] } }))).toBeNull();
  });

  it("carrossel: cards válidos, texto com quebra de linha preservado", () => {
    expect(
      readInterativo(
        bot({
          interativo: {
            tipo: "carrossel",
            cards: [
              { imagem: "https://cdn.example/1.jpg", texto: "Clássico\nR$ 28,70", botoes: ["Quero esse"] },
              { imagem: null, texto: "Suave", botoes: [] },
              { lixo: true },
            ],
          },
        })
      )
    ).toEqual({
      tipo: "carrossel",
      cards: [
        { imagem: "https://cdn.example/1.jpg", texto: "Clássico\nR$ 28,70", botoes: ["Quero esse"] },
        { imagem: null, texto: "Suave", botoes: [] },
      ],
    });
  });

  it("carrossel sem card válido = nada", () => {
    expect(readInterativo(bot({ interativo: { tipo: "carrossel", cards: [{}] } }))).toBeNull();
    expect(readInterativo(bot({ interativo: { tipo: "carrossel" } }))).toBeNull();
  });

  it("tipo desconhecido, metadata escalar/array/null = nada", () => {
    expect(readInterativo(bot({ interativo: { tipo: "produto", botoes: ["a"] } }))).toBeNull();
    expect(readInterativo(bot({ interativo: "botoes" }))).toBeNull();
    expect(readInterativo(bot([]))).toBeNull();
    expect(readInterativo(bot("x"))).toBeNull();
    expect(readInterativo(bot(null))).toBeNull();
    expect(readInterativo(bot(undefined))).toBeNull();
    expect(readInterativo(bot({}))).toBeNull();
  });

  it("só mensagem NOSSA: inbound com a mesma chave não vira tela", () => {
    expect(
      readInterativo(bot({ interativo: { tipo: "botoes", botoes: ["Sim"] } }, { role: "user" }))
    ).toBeNull();
  });

  it("o clique do lead (message_type button) nunca vira tela", () => {
    expect(
      readInterativo(
        bot({ interativo: { tipo: "botoes", botoes: ["Sim"] } }, { message_type: "button" })
      )
    ).toBeNull();
  });
});

describe("carrosselCorpo", () => {
  const cards = [
    { imagem: null, texto: "Clássico\nR$ 28,70", botoes: [] },
    { imagem: null, texto: "Suave\nR$ 28,70", botoes: [] },
  ];

  it("tira do content os textos dos cards que o backend anexou ao corpo", () => {
    expect(carrosselCorpo("olha\n\nClássico\nR$ 28,70\n\nSuave\nR$ 28,70", cards)).toBe("olha");
  });

  it("content diferente do esperado volta inteiro (nunca corta texto à toa)", () => {
    expect(carrosselCorpo("outra coisa", cards)).toBe("outra coisa");
  });

  it("content só com os cards vira vazio", () => {
    expect(carrosselCorpo("Clássico\nR$ 28,70\n\nSuave\nR$ 28,70", cards)).toBe("");
  });
});
