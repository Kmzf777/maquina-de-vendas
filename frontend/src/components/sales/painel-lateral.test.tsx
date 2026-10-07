/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PainelAcopladoContext, PainelLateral } from "./painel-lateral";

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

/**
 * Em /conversas o painel vira coluna do layout ao lado do chat (print do
 * vendedor, 1600 px: o painel sobreposto cortava justamente a mensagem com
 * CPF, endereço e e-mail que ele precisava copiar). Quem decide é o contexto:
 * fora dele (painel-vendas, orçamento, funil, modal do lead) nada muda.
 */
describe("PainelLateral acoplado (coluna do layout em /conversas)", () => {
  function acoplado(onFechar = vi.fn(), filhos: React.ReactNode = <input aria-label="dentro" />) {
    return render(
      <PainelAcopladoContext value={true}>
        <PainelLateral titulo="Novo orçamento — Vida Natural" onFechar={onFechar}>
          {filhos}
        </PainelLateral>
      </PainelAcopladoContext>,
    );
  }

  it("renderiza inline, no lugar onde foi montado — sem portal e sem Sheet", () => {
    const { container } = acoplado();
    expect(container.contains(screen.getByText("Novo orçamento — Vida Natural"))).toBe(true);
    expect(container.contains(screen.getByLabelText("dentro"))).toBe(true);
    expect(document.querySelector('[data-slot="sheet-content"]')).toBeNull();
    expect(container.querySelector('[data-slot="painel-acoplado"]')).toBeTruthy();
  });

  it("mantém a largura do modo sobreposto (o formulário não fica mais apertado)", () => {
    const { container } = acoplado();
    const painel = container.querySelector('[data-slot="painel-acoplado"]') as HTMLElement;
    expect(painel.className).toContain("w-[42rem]");
    expect(painel.className).toContain("shrink-0");
  });

  it("o X fecha", () => {
    const onFechar = vi.fn();
    acoplado(onFechar);
    fireEvent.click(screen.getByRole("button", { name: "Fechar" }));
    expect(onFechar).toHaveBeenCalledTimes(1);
  });

  it("Esc com o foco dentro do painel fecha", () => {
    const onFechar = vi.fn();
    acoplado(onFechar);
    const dentro = screen.getByLabelText("dentro");
    dentro.focus();
    fireEvent.keyDown(dentro, { key: "Escape" });
    expect(onFechar).toHaveBeenCalledTimes(1);
  });

  it("Esc já consumido por um popover/select de dentro (defaultPrevented) não fecha", () => {
    const onFechar = vi.fn();
    acoplado(onFechar);
    const dentro = screen.getByLabelText("dentro");
    dentro.addEventListener("keydown", (e) => e.preventDefault());
    fireEvent.keyDown(dentro, { key: "Escape" });
    expect(onFechar).not.toHaveBeenCalled();
  });

  it("Esc com o foco no chat não fecha", () => {
    const onFechar = vi.fn();
    const campoDoChat = document.createElement("textarea");
    document.body.appendChild(campoDoChat);
    acoplado(onFechar);
    campoDoChat.focus();
    fireEvent.keyDown(campoDoChat, { key: "Escape" });
    expect(onFechar).not.toHaveBeenCalled();
    campoDoChat.remove();
  });

  it("recebe o foco ao abrir, para o Esc funcionar sem clicar antes", () => {
    const { container } = acoplado();
    const painel = container.querySelector('[data-slot="painel-acoplado"]') as HTMLElement;
    expect(painel.contains(document.activeElement)).toBe(true);
  });

  it("sem o contexto, continua no portal do Sheet (comportamento das outras telas)", async () => {
    const { container } = render(
      <PainelLateral titulo="Registrar Venda" onFechar={vi.fn()}>
        <p>corpo</p>
      </PainelLateral>,
    );
    await espera();
    expect(container.contains(screen.getByText("corpo"))).toBe(false);
    expect(document.querySelector('[data-slot="sheet-content"]')).toBeTruthy();
    expect(document.querySelector('[data-slot="painel-acoplado"]')).toBeNull();
  });
});
