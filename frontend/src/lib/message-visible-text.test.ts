import { describe, expect, it } from "vitest";
import {
  mediaCaption,
  reactionExtraText,
  reactionRowHasOwnText,
  shouldHideReactionRow,
} from "@/lib/message-visible-text";

// Bug relatado pelo vendedor (25/09/2026): "quando o cliente manda mensagem anexada a
// foto eu nunca vejo" e "quando o cliente reage a uma mensagem e em seguida manda uma
// mensagem escrita também não vejo".
//
// O backend guarda TUDO certo: a legenda da imagem vira `content` (meta_parser.py:78) e
// o buffer junta reação + texto da mesma janela numa linha só, preservando os dois
// (buffer/manager.py:41 e processor.py:2473). Quem descarta é o RENDERIZADOR.
// Medição em produção (29/09/2026): 199 de 389 imagens inbound e 123 de 383 reações
// carregam texto que o vendedor nunca viu.

describe("mediaCaption", () => {
  it("devolve a legenda que o lead anexou à foto", () => {
    expect(mediaCaption({ message_type: "image", content: "Quero 3kg de cada" })).toBe(
      "Quero 3kg de cada"
    );
  });

  it("ignora o marcador sintético de imagem sem legenda", () => {
    // _MEDIA_MARKERS do processor.py — sinal para o LLM, não texto do lead.
    expect(mediaCaption({ message_type: "image", content: "[imagem]" })).toBe("");
  });

  it("devolve vazio quando a imagem não tem texto nenhum", () => {
    expect(mediaCaption({ message_type: "image", content: "" })).toBe("");
    expect(mediaCaption({ message_type: "image", content: null })).toBe("");
  });

  it("devolve a legenda de vídeo e de figurinha", () => {
    expect(mediaCaption({ message_type: "video", content: "Esse aí foi o do meu." })).toBe(
      "Esse aí foi o do meu."
    );
    expect(mediaCaption({ message_type: "sticker", content: "Mandei errado" })).toBe(
      "Mandei errado"
    );
  });

  it("não repete o nome do arquivo como se fosse legenda do documento", () => {
    // A bolha de documento já mostra `document_name`.
    expect(
      mediaCaption({
        message_type: "document",
        content: "Catálogo Inno vend.pdf",
        document_name: "Catálogo Inno vend.pdf",
      })
    ).toBe("");
  });

  it("devolve a legenda do documento quando ela não é o nome do arquivo", () => {
    expect(
      mediaCaption({
        message_type: "document",
        content: "Segue pagamento da amostra",
        document_name: "comprovante.pdf",
      })
    ).toBe("Segue pagamento da amostra");
  });

  it("mostra o texto digitado junto do áudio, mas nunca a transcrição", () => {
    // A transcrição no chat é um gap declarado e fora do escopo deste bug; o que não pode
    // sumir é o que o lead DIGITOU na mesma janela do buffer.
    expect(
      mediaCaption({
        message_type: "audio",
        content: "[audio transcrito: quero fechar o pedido]\nsegue meu CNPJ",
      })
    ).toBe("segue meu CNPJ");
    expect(
      mediaCaption({ message_type: "audio", content: "[audio transcrito: quero fechar]" })
    ).toBe("");
    expect(mediaCaption({ message_type: "audio", content: "[áudio]" })).toBe("");
    expect(
      mediaCaption({ message_type: "audio", content: "[audio: nao foi possivel transcrever]" })
    ).toBe("");
  });

  it("não se aplica a mensagem de texto comum", () => {
    expect(mediaCaption({ message_type: "text", content: "boa tarde" })).toBe("");
    expect(mediaCaption({ message_type: null, content: "boa tarde" })).toBe("");
  });
});

describe("reactionExtraText", () => {
  it("devolve vazio quando a linha é só a reação", () => {
    expect(reactionExtraText({ message_type: "reaction", content: "[reagiu com 👍]" })).toBe("");
  });

  it("devolve a mensagem que o lead digitou logo depois de reagir", () => {
    expect(
      reactionExtraText({
        message_type: "reaction",
        content: "[reagiu com 👍]\nconsegue faturar em 35 dias?",
      })
    ).toBe("consegue faturar em 35 dias?");
  });

  it("devolve o texto que veio ANTES da reação na mesma janela", () => {
    expect(
      reactionExtraText({
        message_type: "reaction",
        content: "Para o mercado Brasileiro\n[reagiu com ❤️]",
      })
    ).toBe("Para o mercado Brasileiro");
  });

  it("descarta duas reações seguidas sem texto", () => {
    expect(
      reactionExtraText({ message_type: "reaction", content: "[reagiu com 🙏]\n\n[reagiu com 🙏]" })
    ).toBe("");
  });

  it("preserva as linhas do lead e some só com os marcadores", () => {
    expect(
      reactionExtraText({
        message_type: "reaction",
        content: "Sim pode ser\nMaravilha\n[reagiu com ❤️]\n\n\n\nAh legal ok",
      })
    ).toBe("Sim pode ser\nMaravilha\nAh legal ok");
  });

  it("aceita emoji com modificador de tom de pele", () => {
    expect(
      reactionExtraText({ message_type: "reaction", content: "[reagiu com 👍🏽]\nOk" })
    ).toBe("Ok");
  });

  it("não se aplica a mensagem que não é reação", () => {
    expect(reactionExtraText({ message_type: "text", content: "[reagiu com 👍]" })).toBe("");
  });
});

describe("reactionRowHasOwnText", () => {
  it("é falso para a reação pura — ela pode virar só o badge na bolha alvo", () => {
    expect(
      reactionRowHasOwnText({ message_type: "reaction", content: "[reagiu com 👍]" })
    ).toBe(false);
  });

  it("é verdadeiro quando a linha carrega texto do lead — a bolha NÃO pode sumir", () => {
    expect(
      reactionRowHasOwnText({
        message_type: "reaction",
        content: "[reagiu com ❤️]\nSó preciso pagar rs",
      })
    ).toBe(true);
  });
});

describe("shouldHideReactionRow", () => {
  it("esconde a reação pura já virada badge na bolha alvo", () => {
    expect(
      shouldHideReactionRow({
        message_type: "reaction",
        content: "[reagiu com 👍]",
        reaction_attached: true,
      })
    ).toBe(true);
  });

  it("NÃO esconde a linha que também traz o texto digitado pelo lead", () => {
    // Regressão do bug: 40/40 linhas amostradas em produção tinham o alvo na janela,
    // então a thread inteira perdia frases como "consegue faturar em 35 dias?".
    expect(
      shouldHideReactionRow({
        message_type: "reaction",
        content: "[reagiu com 👍]\nconsegue faturar em 35 dias?",
        reaction_attached: true,
      })
    ).toBe(false);
  });

  it("não esconde reação cujo alvo ficou fora da janela", () => {
    expect(
      shouldHideReactionRow({
        message_type: "reaction",
        content: "[reagiu com 👍]",
        reaction_attached: false,
      })
    ).toBe(false);
  });

  it("nunca esconde mensagem que não é reação", () => {
    expect(shouldHideReactionRow({ message_type: "text", content: "boa tarde" })).toBe(false);
  });
});
