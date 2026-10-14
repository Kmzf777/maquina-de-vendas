/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  usePathname: () => "/conversas",
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: {
      getSession: () => Promise.resolve({ data: { session: { user: { email: "joao@cafecanastra.com", app_metadata: { role: "vendedor" } } } } }),
      signOut: () => Promise.resolve(),
    },
  }),
}));

import { Sidebar } from "./sidebar";

afterEach(cleanup);

describe("Sidebar", () => {
  it("aberto: mostra os nomes e o botão de recolher", () => {
    const onAlternar = vi.fn();
    render(<Sidebar onAlternar={onAlternar} />);
    expect(screen.getByText("WhatsApp")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Recolher menu" }));
    expect(onAlternar).toHaveBeenCalledTimes(1);
  });

  it("recolhido: só ícones, com o nome na dica, e botão de abrir", () => {
    const onAlternar = vi.fn();
    const { container } = render(<Sidebar recolhido onAlternar={onAlternar} />);
    expect(screen.queryByText("WhatsApp")).toBeNull();
    expect(screen.queryByText("Comunicação")).toBeNull();
    const link = screen.getByRole("link", { name: "WhatsApp" });
    expect(link.getAttribute("href")).toBe("/conversas");
    expect(link.getAttribute("title")).toBe("WhatsApp");
    expect(container.querySelector("aside")!.className).toContain("w-[56px]");
    fireEvent.click(screen.getByRole("button", { name: "Abrir menu" }));
    expect(onAlternar).toHaveBeenCalledTimes(1);
  });

  it("sem onAlternar (drawer mobile): sem botão de recolher", () => {
    render(<Sidebar onClose={() => {}} />);
    expect(screen.queryByRole("button", { name: "Recolher menu" })).toBeNull();
    expect(screen.getByRole("button", { name: "Fechar menu" })).toBeTruthy();
  });
});
