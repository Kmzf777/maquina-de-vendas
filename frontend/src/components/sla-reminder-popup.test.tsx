/**
 * @vitest-environment jsdom
 *
 * O popup de SLA foi o GATILHO do bug de 30/09-01/10/2026 (mensagem entregue ao cliente
 * errado). Ele abre sozinho, sobre o chat de outro lead, e o botão "Responder agora"
 * navega para a conversa do lead atrasado. Com `autoFocus` nesse botão, a próxima tecla
 * que o vendedor digitava — um Enter para enviar — acionava o botão e trocava a conversa
 * por baixo do rascunho.
 *
 * Invariante travada aqui: ABRIR O POPUP NÃO TIRA O FOCO DE ONDE O VENDEDOR ESTÁ
 * ESCREVENDO. O popup só age por clique deliberado.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent, screen } from "@testing-library/react";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/conversas",
  useRouter: () => ({ push, replace: vi.fn() }),
}));

vi.mock("@/hooks/use-current-role", () => ({
  useCurrentRole: () => ({ role: "vendedor", loading: false }),
}));

vi.mock("@/hooks/use-overdue-leads", () => ({
  useOverdueLeads: () => ({
    leads: [
      {
        conversationId: "conv-daisy",
        leadId: "lead-daisy",
        leadName: "Daisy",
        leadPhone: "5534988860000",
        elapsedMinutes: 73,
        windowStartMin: 480,
        windowEndMin: 1080,
      },
    ],
  }),
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({
      select: () => ({
        eq: () => ({
          eq: () => ({
            order: () => ({ limit: () => ({ maybeSingle: () => Promise.resolve({ data: null }) }) }),
          }),
        }),
      }),
    }),
  }),
}));

import { SlaReminderPopup } from "./sla-reminder-popup";

beforeEach(() => {
  push.mockClear();
});

afterEach(() => cleanup());

describe("popup de SLA não rouba o foco de quem está escrevendo", () => {
  it("o foco permanece no composer quando o popup abre", () => {
    const composer = document.createElement("textarea");
    document.body.appendChild(composer);
    composer.focus();
    expect(document.activeElement).toBe(composer);

    render(<SlaReminderPopup />);

    // Popup visível (o alerta de fato apareceu) e foco intocado.
    expect(screen.getByText("Daisy")).toBeDefined();
    expect(document.activeElement).toBe(composer);

    composer.remove();
  });

  it("nenhuma tecla do vendedor cai no botão que troca a conversa", () => {
    const composer = document.createElement("textarea");
    document.body.appendChild(composer);
    composer.focus();

    render(<SlaReminderPopup />);

    // O que causava o bug: Enter/espaço acionam o BOTÃO FOCADO. Enquanto o foco não
    // estiver em "Responder agora", nenhuma tecla digitada no chat troca a conversa.
    // (jsdom não traduz Enter em click, então a asserção é sobre o foco — que é a
    // condição real do estrago.)
    expect(document.activeElement).not.toBe(
      screen.getByRole("button", { name: /Responder agora/i }),
    );
    expect(push).not.toHaveBeenCalled();

    composer.remove();
  });

  it("o clique deliberado em 'Responder agora' continua abrindo a conversa do lead atrasado", () => {
    render(<SlaReminderPopup />);
    fireEvent.click(screen.getByRole("button", { name: /Responder agora/i }));

    expect(push).toHaveBeenCalledWith("/conversas?lead_id=lead-daisy");
  });
});
