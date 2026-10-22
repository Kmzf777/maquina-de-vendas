/**
 * @vitest-environment jsdom
 *
 * Lista de seleção de vendedor (cartão b67f1c6b): grava o id de `vendedores`,
 * nunca texto livre. Mock do fetch por substring de URL, padrão de bling-settings.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { VendedorSelect, _limparCacheVendedores, nomeDoVendedor, type Vendedor } from "./vendedor-select";

const JOAO: Vendedor = { id: "u-joao", nome: "João Brás", email: "joao@x.com", ativo: true };
const ARTHUR: Vendedor = { id: "u-arthur", nome: "Arthur", email: "arthur@x.com", ativo: true };
const RAFAEL: Vendedor = { id: "u-rafael", nome: "Rafael", email: "rafael@x.com", ativo: false };

let chamadas = 0;
beforeEach(() => {
  _limparCacheVendedores();
  chamadas = 0;
  global.fetch = vi.fn(async (url: string) => {
    if (String(url).includes("/api/vendedores")) chamadas += 1;
    return { ok: true, status: 200, json: async () => [ARTHUR, JOAO, RAFAEL] } as Response;
  }) as unknown as typeof fetch;
});
afterEach(cleanup);

describe("VendedorSelect", () => {
  it("lista 'Sem vendedor' e só os ativos", async () => {
    render(<VendedorSelect value={null} onChange={() => {}} />);
    await waitFor(() => expect(screen.getByRole("option", { name: "João Brás" })).toBeTruthy());
    const nomes = screen.getAllByRole("option").map((o) => o.textContent);
    expect(nomes).toEqual(["Sem vendedor", "Arthur", "João Brás"]);
  });

  it("grava o id escolhido e null em 'Sem vendedor'", async () => {
    const onChange = vi.fn();
    render(<VendedorSelect value={null} onChange={onChange} />);
    await waitFor(() => screen.getByRole("option", { name: "Arthur" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "u-arthur" } });
    expect(onChange).toHaveBeenLastCalledWith("u-arthur");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("vendedor inativo atribuído continua visível como opção", async () => {
    render(<VendedorSelect value="u-rafael" onChange={() => {}} />);
    await waitFor(() => screen.getByRole("option", { name: "Rafael (inativo)" }));
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("u-rafael");
  });

  it("busca a lista uma vez só para vários selects", async () => {
    render(
      <>
        <VendedorSelect value={null} onChange={() => {}} />
        <VendedorSelect value={null} onChange={() => {}} />
      </>,
    );
    await waitFor(() => expect(screen.getAllByRole("option", { name: "Arthur" })).toHaveLength(2));
    expect(chamadas).toBe(1);
  });
});

describe("nomeDoVendedor", () => {
  it("resolve o nome pelo id e devolve null se não achar", () => {
    expect(nomeDoVendedor([JOAO, ARTHUR], "u-joao")).toBe("João Brás");
    expect(nomeDoVendedor([JOAO], "u-x")).toBeNull();
    expect(nomeDoVendedor([JOAO], null)).toBeNull();
    expect(nomeDoVendedor(null, "u-joao")).toBeNull();
  });
});
