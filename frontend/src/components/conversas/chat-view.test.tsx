/**
 * @vitest-environment jsdom
 *
 * O bug de 30/09-01/10/2026 relatado pelo vendedor: ele colou a tabela de Private Label
 * no chat do Pedro e a mensagem foi entregue à Daisy — "que eu nem tava com a conversa
 * aberta" — e o Pedro não recebeu nada.
 *
 * Causa: `<ChatView>` é renderizado SEM `key` (page.tsx), então a mesma instância
 * atravessa a troca de conversa. O efeito de reset por `conversation.id` zera 13 estados
 * locais e esquece exatamente o único que carrega a mensagem: o `text` do composer. Como
 * `handleSend` lê `conversation.id` no instante do Enter, qualquer troca silenciosa de
 * conversa entre o "colar" e o "enviar" redireciona a mensagem para outro cliente.
 *
 * O gatilho em produção é o popup de SLA: ele abre sobre o chat de OUTRO lead, é modal e
 * põe `autoFocus` no botão "Responder agora", que navega para `?lead_id=<outro lead>`. Um
 * Enter (ou espaço) digitado sem olhar troca a conversa por baixo do rascunho.
 */
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import type { Conversation } from "@/lib/types";

vi.mock("@/hooks/use-realtime-messages", () => ({
  useRealtimeMessages: () => ({
    messages: [],
    loading: false,
    refetch: () => Promise.resolve(),
    hasMore: false,
    loadOlder: () => {},
    loadingOlder: false,
  }),
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({
      select: () => ({ eq: () => ({ order: () => ({ limit: () => ({ maybeSingle: () => Promise.resolve({ data: null }) }) }) }) }),
    }),
  }),
}));

import { ChatView } from "./chat-view";

beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});

const TABELA = "PRIVATE LABEL\n500g torrado e moido - R$ 34,90\n1kg em graos - R$ 62,00";

function makeConversation(id: string, leadId: string, leadName: string): Conversation {
  return {
    id,
    lead_id: leadId,
    channel_id: "chan-1",
    stage: "secretaria",
    status: "open",
    last_msg_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    agent_profile_id: null,
    last_message_text: null,
    unread_count: 0,
    // Janela de 24h aberta: sem isso o composer nasce bloqueado e o teste não prova nada.
    last_customer_message_at: new Date().toISOString(),
    whatsapp_window_expires_at: null,
    followup_enabled: true,
    first_seller_response_at: null,
    last_seller_response_at: null,
    leads: { id: leadId, name: leadName, phone: "5534988860000", opt_out: false } as Conversation["leads"],
    channels: { id: "chan-1", name: "Comercial", phone: "5534000000000", provider: "meta_cloud", agent_profile_id: null },
  };
}

const pedro = makeConversation("conv-pedro", "lead-pedro", "Pedro");
const daisy = makeConversation("conv-daisy", "lead-daisy", "Daisy");

const baseProps = {
  tags: [],
  aiEnabled: false,
  onToggleAi: () => {},
  followupEnabled: false,
  onToggleFollowup: () => {},
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as unknown as Response),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function textareaOf(container: HTMLElement): HTMLTextAreaElement {
  const node = container.querySelector("textarea");
  if (!node) throw new Error("composer não encontrado");
  return node as HTMLTextAreaElement;
}

function sendCalls(): string[] {
  return fetchMock.mock.calls
    .map((c) => String(c[0]))
    .filter((url) => url.includes("/send"));
}

describe("ChatView: o rascunho do composer pertence à conversa em que foi escrito", () => {
  it("troca de conversa por baixo do rascunho NÃO leva o texto para o chat novo", () => {
    const { container, rerender } = render(<ChatView conversation={pedro} {...baseProps} />);
    fireEvent.change(textareaOf(container), { target: { value: TABELA } });
    expect(textareaOf(container).value).toBe(TABELA);

    // Exatamente o que o popup de SLA provoca: mesma instância de ChatView, conversa nova.
    rerender(<ChatView conversation={daisy} {...baseProps} />);

    expect(textareaOf(container).value).toBe("");
  });

  it("Enter depois da troca NÃO envia a tabela do Pedro para a Daisy", () => {
    const { container, rerender } = render(<ChatView conversation={pedro} {...baseProps} />);
    fireEvent.change(textareaOf(container), { target: { value: TABELA } });
    rerender(<ChatView conversation={daisy} {...baseProps} />);

    fireEvent.keyDown(textareaOf(container), { key: "Enter", shiftKey: false });

    expect(sendCalls()).toEqual([]);
  });

  it("voltar para a conversa original devolve o rascunho intacto", () => {
    const { container, rerender } = render(<ChatView conversation={pedro} {...baseProps} />);
    fireEvent.change(textareaOf(container), { target: { value: TABELA } });
    rerender(<ChatView conversation={daisy} {...baseProps} />);
    rerender(<ChatView conversation={pedro} {...baseProps} />);

    expect(textareaOf(container).value).toBe(TABELA);
  });

  it("o caminho normal continua funcionando: digitar e enviar na conversa aberta", async () => {
    const { container } = render(<ChatView conversation={pedro} {...baseProps} />);
    fireEvent.change(textareaOf(container), { target: { value: "bom dia" } });
    fireEvent.keyDown(textareaOf(container), { key: "Enter", shiftKey: false });

    expect(sendCalls()).toEqual(["/api/conversations/conv-pedro/send"]);
  });
});
