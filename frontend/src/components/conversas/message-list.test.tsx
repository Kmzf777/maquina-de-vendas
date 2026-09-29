/**
 * @vitest-environment jsdom
 *
 * A metade mais grave do bug de 25/09/2026: a linha de reação não ficava só sem texto —
 * ela saía INTEIRA da thread. `rawMessages.filter((m) => !m.reaction_attached)` trocava a
 * bolha por um badge de emoji na bolha alvo, e o buffer havia fundido nessa mesma linha a
 * frase que o lead digitou logo depois de reagir. Amostra de produção (29/09/2026): 40 de
 * 40 linhas de reação com texto tinham o alvo na janela — ou seja, 100% sumiam.
 */
import { describe, it, expect, afterEach, beforeAll } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";
import { MessageList } from "./message-list";
import type { Message } from "@/lib/types";

// jsdom não implementa scrollIntoView; a lista rola para o fim ao montar.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});

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

const alvo = makeMessage({
  id: "alvo",
  role: "assistant",
  sent_by: "seller",
  content: "Boa tarde Karine",
  wamid: "wamid.ALVO",
  created_at: "2026-09-25T19:12:00.000Z",
});

function renderList(messages: Message[]) {
  return render(
    <MessageList messages={messages} loading={false} conversationId="conv-1" />
  );
}

afterEach(cleanup);

describe("MessageList — reação com texto não pode sumir da thread", () => {
  it("mantém a frase que o lead digitou junto da reação", () => {
    renderList([
      alvo,
      makeMessage({
        id: "reacao",
        content: "[reagiu com 👍]\nconsegue faturar em 35 dias?",
        message_type: "reaction",
        metadata: { emoji: "👍", target_wamid: "wamid.ALVO" },
        reaction_attached: true,
        created_at: "2026-09-25T19:13:00.000Z",
      }),
    ]);

    expect(screen.getByText("consegue faturar em 35 dias?")).toBeTruthy();
  });

  it("continua trocando a reação PURA pelo badge no alvo", () => {
    renderList([
      alvo,
      makeMessage({
        id: "reacao",
        content: "[reagiu com 👍]",
        message_type: "reaction",
        metadata: { emoji: "👍", target_wamid: "wamid.ALVO" },
        reaction_attached: true,
        reactions: undefined,
        created_at: "2026-09-25T19:13:00.000Z",
      }),
    ]);

    // Sem bolha própria: nada de "Reagiu com" na thread.
    expect(screen.queryByText(/Reagiu com/)).toBeNull();
  });
});
