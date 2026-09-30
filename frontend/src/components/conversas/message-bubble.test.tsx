/**
 * @vitest-environment jsdom
 *
 * Bug relatado pelo vendedor (25/09/2026): "quando o cliente manda mensagem anexada a foto
 * eu nunca vejo" e "quando o cliente reage a uma mensagem e em seguida manda uma mensagem
 * escrita também não vejo".
 *
 * A bolha é um ternário por `message_type`: o ramo de mídia desenhava só o <img>/<video> e
 * o ramo de reação só o bloco "Reagiu com X" — `message.content`, que é onde a legenda e o
 * texto da janela do buffer moram, nunca era impresso. Medição em produção (29/09/2026):
 * 199 de 389 imagens inbound tinham legenda invisível.
 */
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";
import { MessageBubble } from "./message-bubble";
import type { Message } from "@/lib/types";

function makeMessage(over: Partial<Message>): Message {
  return {
    id: "m1",
    lead_id: "lead-1",
    conversation_id: "conv-1",
    role: "user",
    content: "",
    stage: null,
    sent_by: "user",
    created_at: "2026-09-25T19:12:00.000Z",
    ...over,
  };
}

function renderBubble(over: Partial<Message>) {
  return render(
    <MessageBubble message={makeMessage(over)} isGrouped={false} conversationId="conv-1" />
  );
}

afterEach(cleanup);

describe("MessageBubble — legenda de mídia", () => {
  it("mostra a legenda que o lead mandou junto da foto", () => {
    renderBubble({
      message_type: "image",
      media_url: "https://cdn.example/foto.jpg",
      content: "3 kg do Microlote e 2 do Canela",
    });

    expect(screen.getByText("3 kg do Microlote e 2 do Canela")).toBeTruthy();
  });

  it("continua renderizando a imagem junto da legenda", () => {
    const { container } = renderBubble({
      message_type: "image",
      media_url: "https://cdn.example/foto.jpg",
      content: "segue a arte",
    });

    expect(container.querySelector("img")).toBeTruthy();
    expect(screen.getByText("segue a arte")).toBeTruthy();
  });

  it("não imprime o marcador sintético de imagem sem legenda", () => {
    renderBubble({
      message_type: "image",
      media_url: "https://cdn.example/foto.jpg",
      content: "[imagem]",
    });

    expect(screen.queryByText("[imagem]")).toBeNull();
  });

  it("mostra a legenda do vídeo", () => {
    renderBubble({
      message_type: "video",
      media_url: "https://cdn.example/v.mp4",
      content: "Esse aí foi o do meu.",
    });

    expect(screen.getByText("Esse aí foi o do meu.")).toBeTruthy();
  });

  it("mostra as quantidades do caso real que motivou o report (Karine, 25/09/2026)", () => {
    // Linhas reais em produção: `image` com content '5 unidades' e
    // 'moído quero 7\nem grão 3'. O vendedor não viu nenhuma das duas e precisou escrever
    // "O sistema está me mostrando apenas os prints" para um cliente fechando pedido.
    renderBubble({
      message_type: "image",
      media_url: "https://cdn.example/print.jpg",
      content: "moído quero 7\nem grão 3",
    });

    expect(screen.getByText(/moído quero 7/)).toBeTruthy();
    expect(screen.getByText(/em grão 3/)).toBeTruthy();
  });

  it("mostra a legenda do documento sem repetir o nome do arquivo", () => {
    renderBubble({
      message_type: "document",
      media_url: "https://cdn.example/d.pdf",
      document_name: "comprovante.pdf",
      content: "Segue pagamento da amostra",
    });

    expect(screen.getByText("Segue pagamento da amostra")).toBeTruthy();
    expect(screen.getAllByText("comprovante.pdf")).toHaveLength(1);
  });
});

describe("MessageBubble — reação que veio junto de texto", () => {
  it("mostra a frase digitada na mesma janela da reação", () => {
    renderBubble({
      message_type: "reaction",
      content: "[reagiu com 👍]\nconsegue faturar em 35 dias?",
      metadata: { emoji: "👍", target_wamid: "wamid.ALVO" },
      reaction_attached: true,
    });

    expect(screen.getByText("consegue faturar em 35 dias?")).toBeTruthy();
  });

  it("não repete 'Reagiu com' quando o emoji já é badge na bolha alvo", () => {
    renderBubble({
      message_type: "reaction",
      content: "[reagiu com 👍]\nconsegue faturar em 35 dias?",
      metadata: { emoji: "👍", target_wamid: "wamid.ALVO" },
      reaction_attached: true,
    });

    expect(screen.queryByText(/Reagiu com/)).toBeNull();
  });

  it("mantém 'Reagiu com' quando o alvo ficou fora da janela carregada", () => {
    renderBubble({
      message_type: "reaction",
      content: "[reagiu com 🙏]",
      metadata: { emoji: "🙏", target_wamid: "wamid.ANTIGO" },
      reaction_attached: false,
    });

    expect(screen.getByText(/Reagiu com/)).toBeTruthy();
  });
});
