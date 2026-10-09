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
import { render, cleanup, screen, fireEvent } from "@testing-library/react";
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

/**
 * Com o painel de venda/orçamento acoplado o chat estreita (~390–700 px). A
 * bolha tem de QUEBRAR a linha — e-mail, endereço e links sem espaço inclusive
 * — em vez de vazar e ser cortada. `break-words` (overflow-wrap: break-word)
 * não entra no cálculo do min-content do item flex; `anywhere` entra, e o
 * `min-w-0` deixa a bolha encolher dentro da linha flex.
 */
describe("MessageBubble — quebra de linha com o chat estreito", () => {
  const longa = "cliente.com.um.email.bem.comprido.sem.espaco@dominio-muito-longo.com.br";

  it.each([
    ["recebida", "user"],
    ["enviada", "assistant"],
  ] as const)("bolha %s quebra palavra longa em qualquer ponto e pode encolher", (_, role) => {
    renderBubble({ role, sent_by: role === "user" ? "user" : "agent", content: longa });
    const texto = screen.getByText(longa);
    const bolha = texto.closest("div.rounded-\\[8px\\]") as HTMLElement;
    expect(bolha).toBeTruthy();
    expect(bolha.className).toContain("[overflow-wrap:anywhere]");
    expect(bolha.className).toContain("min-w-0");
  });
});

// ── A tela interativa que o bot mandou (10/2026) ─────────────────────────────
// O vendedor via só o texto: os botões, o menu e o carrossel que o lead tinha na tela
// não apareciam. A estrutura vem de `metadata.interativo` (lib/message-interativo.ts).
describe("MessageBubble — tela interativa do bot", () => {
  const bot = (metadata: Record<string, unknown>, over: Partial<Message> = {}) =>
    renderBubble({ role: "assistant", sent_by: "valeria_botoes", metadata, ...over });

  it("botões: mostra o texto e os rótulos como botões de resposta não clicáveis", () => {
    const { container } = bot(
      { interativo: { tipo: "botoes", imagem: null, botoes: ["Fazer pedido", "Provar antes", "Tenho dúvida"] } },
      { content: "o que você prefere?" }
    );
    expect(screen.getByText("o que você prefere?")).toBeTruthy();
    const lista = screen.getByRole("list", { name: "Botões enviados ao lead" });
    expect(lista.textContent).toContain("Fazer pedido");
    expect(lista.textContent).toContain("Provar antes");
    expect(lista.textContent).toContain("Tenho dúvida");
    // Não clicável: o vendedor não pode achar que "clicar" responde pelo lead.
    expect(lista.querySelector("button")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("botões com imagem: a foto aparece acima do texto", () => {
    const { container } = bot(
      { interativo: { tipo: "botoes", imagem: "https://cdn.example/n5.jpg", botoes: ["Sim"] } },
      { content: "Clássico 250g" }
    );
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("https://cdn.example/n5.jpg");
    const texto = screen.getByText("Clássico 250g");
    expect(img!.compareDocumentPosition(texto) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("botões com imagem numa linha que já é image: a foto não sai duas vezes", () => {
    const { container } = bot(
      { interativo: { tipo: "botoes", imagem: "https://cdn.example/n5.jpg", botoes: ["Sim"] } },
      { content: "Clássico 250g", message_type: "image", media_url: "https://cdn.example/n5.jpg" }
    );
    expect(container.querySelectorAll("img").length).toBe(1);
    expect(screen.getByText("Clássico 250g")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Botões enviados ao lead" }).textContent).toContain("Sim");
  });

  it("lista: fechada por padrão, o rótulo abre e fecha as linhas", () => {
    bot(
      {
        interativo: {
          tipo: "lista",
          botao: "Ver opções",
          linhas: [
            { titulo: "Pro meu negócio", descricao: "revenda, cafeteria" },
            { titulo: "Pra minha casa", descricao: "" },
          ],
        },
      },
      { content: "pra quem é o café?" }
    );
    const toggle = screen.getByRole("button", { name: /Ver opções/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Pro meu negócio")).toBeNull();

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Pro meu negócio")).toBeTruthy();
    expect(screen.getByText("revenda, cafeteria")).toBeTruthy();
    expect(screen.getByText("Pra minha casa")).toBeTruthy();

    fireEvent.click(toggle);
    expect(screen.queryByText("Pro meu negócio")).toBeNull();
  });

  it("carrossel: corpo + cards roláveis com foto, texto e botão, sem alargar o chat", () => {
    const { container } = bot(
      {
        interativo: {
          tipo: "carrossel",
          cards: [
            { imagem: "https://cdn.example/1.jpg", texto: "Clássico\nR$ 28,70", botoes: ["Quero esse"] },
            { imagem: "https://cdn.example/2.jpg", texto: "Suave\nR$ 28,70", botoes: ["Quero esse"] },
          ],
        },
      },
      // O content do carrossel é corpo + textos dos cards (preview em texto).
      { content: "olha nossos cafés\n\nClássico\nR$ 28,70\n\nSuave\nR$ 28,70" }
    );
    // A bolha mostra só o corpo; os textos dos cards ficam nos cards (sem eco).
    expect(screen.getByText("olha nossos cafés")).toBeTruthy();
    const trilho = screen.getByRole("list", { name: "Carrossel enviado ao lead" });
    expect(trilho.className).toContain("overflow-x-auto");
    const cards = trilho.querySelectorAll(":scope > li");
    expect(cards.length).toBe(2);
    expect(cards[0].querySelector("img")?.getAttribute("src")).toBe("https://cdn.example/1.jpg");
    expect(cards[0].textContent).toContain("Clássico");
    expect(cards[0].textContent).toContain("Quero esse");
    expect(container.querySelectorAll("img").length).toBe(2);
  });

  it("carrossel cujo content não começa pelos cards mostra o content inteiro", () => {
    bot(
      { interativo: { tipo: "carrossel", cards: [{ imagem: "https://cdn.example/1.jpg", texto: "Card A", botoes: [] }] } },
      { content: "texto qualquer" }
    );
    expect(screen.getByText("texto qualquer")).toBeTruthy();
  });

  it("metadata malformado: só o texto, como antes", () => {
    const { container } = bot({ interativo: { tipo: "botoes", botoes: "Sim" } }, { content: "oi" });
    expect(screen.getByText("oi")).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("o toque do lead continua sendo o chip 'Clicou'", () => {
    renderBubble({
      role: "user",
      message_type: "button",
      content: "Fazer pedido",
      metadata: { payload: "pedido", title: "Fazer pedido" },
    });
    expect(screen.getByText("Clicou")).toBeTruthy();
    expect(screen.getByText("Fazer pedido")).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
  });
});
