/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PainelLateral } from "./painel-lateral";

afterEach(cleanup);

const espera = () => new Promise((r) => setTimeout(r, 20));

describe("PainelLateral", () => {
  it("não cobre a conversa: sem overlay e sem travar o resto da página", async () => {
    render(
      <PainelLateral titulo="Registrar Venda" onFechar={vi.fn()}>
        <p>corpo</p>
      </PainelLateral>,
    );
    await espera();
    expect(screen.getByText("corpo")).toBeTruthy();
    expect(document.querySelector('[data-slot="sheet-overlay"]')).toBeNull();
    expect(document.body.style.pointerEvents).not.toBe("none");
  });

  it("clicar fora (no chat) não fecha o painel", async () => {
    const onFechar = vi.fn();
    const fora = document.createElement("div");
    document.body.appendChild(fora);
    render(
      <PainelLateral titulo="Registrar Venda" onFechar={onFechar}>
        <p>corpo</p>
      </PainelLateral>,
    );
    await espera();
    fireEvent.pointerDown(fora);
    fireEvent.focusIn(fora);
    await espera();
    expect(onFechar).not.toHaveBeenCalled();
    fora.remove();
  });

  it("o X fecha", () => {
    const onFechar = vi.fn();
    render(
      <PainelLateral titulo="Registrar Venda" onFechar={onFechar}>
        <p>corpo</p>
      </PainelLateral>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Fechar" }));
    expect(onFechar).toHaveBeenCalledTimes(1);
  });

  it("mostra o título", () => {
    render(
      <PainelLateral titulo="Novo Orçamento" onFechar={vi.fn()}>
        <p>corpo</p>
      </PainelLateral>,
    );
    expect(screen.getByText("Novo Orçamento")).toBeTruthy();
  });

  it("Esc com o foco fora do painel (no chat) não fecha nem descarta o pedido", async () => {
    const onFechar = vi.fn();
    const campoDoChat = document.createElement("textarea");
    document.body.appendChild(campoDoChat);
    render(
      <PainelLateral titulo="Registrar Venda" onFechar={onFechar}>
        <input aria-label="dentro" />
      </PainelLateral>,
    );
    await espera();
    campoDoChat.focus();
    fireEvent.keyDown(campoDoChat, { key: "Escape" });
    await espera();
    expect(onFechar).not.toHaveBeenCalled();
    campoDoChat.remove();
  });

  it("Esc com o foco dentro do painel fecha", async () => {
    const onFechar = vi.fn();
    render(
      <PainelLateral titulo="Registrar Venda" onFechar={onFechar}>
        <input aria-label="dentro" />
      </PainelLateral>,
    );
    await espera();
    const dentro = screen.getByLabelText("dentro");
    dentro.focus();
    fireEvent.keyDown(dentro, { key: "Escape" });
    await espera();
    expect(onFechar).toHaveBeenCalledTimes(1);
  });
});
