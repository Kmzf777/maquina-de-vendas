/**
 * @vitest-environment jsdom
 *
 * Cadastro do contato no Bling pelo resolvedor: endereço pela metade é barrado
 * antes de sair do navegador, e o CEP preenche o resto do endereço.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BlingContactResolver } from "./bling-contact-resolver";

type Chamada = { url: string; method: string; body: unknown };
let chamadas: Chamada[] = [];
let respostaCep: (url: string) => Promise<Response>;

const resposta = (status: number, corpo: unknown) =>
  ({ ok: status < 300, status, json: async () => corpo }) as Response;

beforeEach(() => {
  chamadas = [];
  respostaCep = async () => resposta(404, {});
  global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    chamadas.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.startsWith("/api/cep/")) return respostaCep(url);
    if (url === "/api/bling/contacts") return resposta(200, { bling_contact_id: 1 });
    return resposta(200, {});
  }) as unknown as typeof fetch;
});

afterEach(() => cleanup());

function abrir() {
  const onResolved = vi.fn();
  render(
    <BlingContactResolver
      leadId="L1"
      status="missing"
      candidates={[]}
      conta="default"
      defaults={{ nome: "Fulano", documento: "12345678909", email: "a@b.com" }}
      onResolved={onResolved}
      onCancel={vi.fn()}
    />,
  );
  return { onResolved };
}

const digitar = (placeholder: string, value: string) =>
  fireEvent.change(screen.getByPlaceholderText(placeholder), { target: { value } });

describe("BlingContactResolver — endereço", () => {
  it("endereço começado e incompleto mostra o que falta e não envia", async () => {
    abrir();
    digitar("Nº", "12");
    fireEvent.click(screen.getByRole("button", { name: "Cadastrar e lançar o pedido" }));

    expect(
      await screen.findByText(
        "Informe o CEP · Informe o logradouro · Informe o município · Informe a UF",
      ),
    ).toBeTruthy();
    expect(chamadas.some((c) => c.url === "/api/bling/contacts")).toBe(false);
  });
});
