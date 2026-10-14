/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { CHAVE_MENU, MenuLateralProvider, reduzirMenu, useMenuLateral } from "./menu-lateral";

const ABERTO = { recolhido: false, peloPainel: false };

describe("reduzirMenu", () => {
  it("alternar inverte e zera o 'pelo painel'", () => {
    expect(reduzirMenu(ABERTO, { tipo: "alternar" })).toEqual({ recolhido: true, peloPainel: false });
    expect(reduzirMenu({ recolhido: true, peloPainel: true }, { tipo: "alternar" })).toEqual(ABERTO);
  });
  it("painel recolhe o menu aberto e restaura ao fechar", () => {
    const r = reduzirMenu(ABERTO, { tipo: "recolherPeloPainel" });
    expect(r).toEqual({ recolhido: true, peloPainel: true });
    expect(reduzirMenu(r, { tipo: "restaurarDoPainel" })).toEqual(ABERTO);
  });
  it("menu recolhido à mão continua recolhido ao fechar o painel", () => {
    const mao = { recolhido: true, peloPainel: false };
    const r = reduzirMenu(mao, { tipo: "recolherPeloPainel" });
    expect(r).toEqual(mao);
    expect(reduzirMenu(r, { tipo: "restaurarDoPainel" })).toEqual(mao);
  });
  it("reabrir à mão com o painel aberto vence: fechar o painel não mexe", () => {
    let e = reduzirMenu(ABERTO, { tipo: "recolherPeloPainel" });
    e = reduzirMenu(e, { tipo: "alternar" });
    expect(reduzirMenu(e, { tipo: "restaurarDoPainel" })).toEqual(ABERTO);
  });
});

function Sonda() {
  const m = useMenuLateral();
  return (
    <div>
      <span data-testid="estado">{m.recolhido ? "recolhido" : "aberto"}</span>
      <button onClick={m.alternar}>alternar</button>
      <button onClick={m.recolherPeloPainel}>painel abre</button>
      <button onClick={m.restaurarDoPainel}>painel fecha</button>
    </div>
  );
}

describe("MenuLateralProvider", () => {
  beforeEach(() => localStorage.clear());
  afterEach(cleanup);

  it("lembra a escolha manual no localStorage", () => {
    render(<MenuLateralProvider><Sonda /></MenuLateralProvider>);
    act(() => screen.getByText("alternar").click());
    expect(screen.getByTestId("estado").textContent).toBe("recolhido");
    expect(localStorage.getItem(CHAVE_MENU)).toBe("1");
  });
  it("nasce recolhido se a escolha salva foi recolher", () => {
    localStorage.setItem(CHAVE_MENU, "1");
    render(<MenuLateralProvider><Sonda /></MenuLateralProvider>);
    expect(screen.getByTestId("estado").textContent).toBe("recolhido");
  });
  it("recolher pelo painel não grava preferência", () => {
    render(<MenuLateralProvider><Sonda /></MenuLateralProvider>);
    act(() => screen.getByText("painel abre").click());
    expect(screen.getByTestId("estado").textContent).toBe("recolhido");
    expect(localStorage.getItem(CHAVE_MENU)).toBeNull();
    act(() => screen.getByText("painel fecha").click());
    expect(screen.getByTestId("estado").textContent).toBe("aberto");
  });
  it("sem provider: aberto e funções inertes", () => {
    render(<Sonda />);
    act(() => screen.getByText("alternar").click());
    expect(screen.getByTestId("estado").textContent).toBe("aberto");
  });
});
