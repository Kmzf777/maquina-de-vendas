/**
 * @vitest-environment jsdom
 *
 * Com o painel de venda/orçamento acoplado em /conversas, o chat fica com
 * ~390–700 px numa tela larga. O rótulo "Finalizar Conversa" dependia da
 * VIEWPORT (`sm:`), então numa tela de 1366 px ele continuava visível num chat
 * de ~470 px e espremia o nome do lead a quase nada. Agora depende da largura
 * do próprio cabeçalho (container query): estreito, fica só o ícone.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

vi.mock("@/lib/supabase/client", () => ({ createClient: () => ({}) }));

import { ChatHeader } from "./chat-header";
import type { Conversation } from "@/lib/types";

afterEach(cleanup);

const conversa = {
  id: "conv-a",
  leads: { id: "lead-a", name: "Vida Natural", phone: "5531999990000" },
  channels: { name: "NUMERO JOAO", mode: "ai" },
} as unknown as Conversation;

describe("ChatHeader — chat estreito ao lado do painel acoplado", () => {
  it("o rótulo 'Finalizar Conversa' segue a largura do cabeçalho, não a da tela", () => {
    render(
      <ChatHeader
        conversation={conversa}
        tags={[]}
        aiEnabled
        onToggleAi={vi.fn()}
        followupEnabled
        onToggleFollowup={vi.fn()}
      />,
    );
    const botao = screen.getByRole("button", { name: "Finalizar Conversa" });
    const rotulo = botao.querySelector("span") as HTMLElement;
    expect(rotulo.textContent).toBe("Finalizar Conversa");
    expect(rotulo.className.split(/\s+/)).toEqual(expect.arrayContaining(["hidden", "@xl:inline"]));
    expect(rotulo.className).not.toContain("sm:inline");
    const cabecalho = screen.getByText("Vida Natural").closest(".\\@container");
    expect(cabecalho).toBeTruthy();
  });
});

describe("ChatHeader — cor do avatar pelo segmento (b67f1c6b)", () => {
  function corDoAvatar(leads: Record<string, unknown>): string {
    const { container } = render(
      <ChatHeader
        conversation={{ ...conversa, leads: { ...conversa.leads, ...leads } } as unknown as Conversation}
        tags={[]}
        aiEnabled
        onToggleAi={vi.fn()}
        followupEnabled
        onToggleFollowup={vi.fn()}
      />,
    );
    const avatar = Array.from(container.querySelectorAll<HTMLElement>("[style]")).find((el) =>
      el.style.backgroundColor,
    );
    cleanup();
    return avatar?.style.backgroundColor ?? "";
  }

  it("lê leads.segmento, não a fase", () => {
    // #8b6bab = private_label
    expect(corDoAvatar({ stage: "qualificando", segmento: "private_label" })).toBe("rgb(139, 107, 171)");
  });

  it("cai no stage antigo enquanto o backfill não roda", () => {
    expect(corDoAvatar({ stage: "atacado", segmento: null })).toBe("rgb(91, 138, 173)");
  });
});
