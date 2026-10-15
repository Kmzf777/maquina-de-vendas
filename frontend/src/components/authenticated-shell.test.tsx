/**
 * @vitest-environment jsdom
 *
 * O pop-up de SLA ("Lead sem resposta há X") foi desligado a pedido da operação
 * (cartão ca54ae27). O shell não pode voltar a montá-lo sem uma decisão explícita.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  usePathname: () => "/conversas",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/components/sidebar", () => ({ Sidebar: () => null }));
vi.mock("@/components/notification-toast", () => ({ NotificationToast: () => null }));
vi.mock("@/hooks/use-presence", () => ({
  PresenceProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/hooks/use-realtime-keepalive", () => ({ useRealtimeKeepAlive: () => {} }));
vi.mock("@/components/sla-reminder-popup", () => ({
  SlaReminderPopup: () => <div data-testid="sla-popup">Lead sem resposta há</div>,
}));

import { AuthenticatedShell } from "./authenticated-shell";

afterEach(() => cleanup());

describe("AuthenticatedShell", () => {
  it("não monta o pop-up de SLA", () => {
    render(<AuthenticatedShell><p>conteúdo</p></AuthenticatedShell>);
    expect(screen.getByText("conteúdo")).toBeTruthy();
    expect(screen.queryByTestId("sla-popup")).toBeNull();
  });
});
