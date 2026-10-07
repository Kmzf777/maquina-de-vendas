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
let respostaContato: () => Response;

const resposta = (status: number, corpo: unknown) =>
  ({ ok: status < 300, status, json: async () => corpo }) as Response;

beforeEach(() => {
  chamadas = [];
  respostaCep = async () => resposta(404, {});
  respostaContato = () => resposta(200, { bling_contact_id: 1 });
  global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    chamadas.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.startsWith("https://viacep.com.br/")) return respostaCep(url);
    if (url === "/api/bling/contacts") return respostaContato();
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

describe("BlingContactResolver — busca de CEP", () => {
  const FRUTAL = {
    cep: "38200-000",
    logradouro: "Avenida Brasil",
    bairro: "Centro",
    localidade: "Frutal",
    uf: "MG",
  };

  it("ao sair do CEP com 8 dígitos preenche logradouro, bairro, município e UF", async () => {
    respostaCep = async () => resposta(200, FRUTAL);
    abrir();
    digitar("CEP", "38200-000");
    fireEvent.blur(screen.getByPlaceholderText("CEP"));

    await waitFor(() =>
      expect((screen.getByPlaceholderText("Município") as HTMLInputElement).value).toBe("Frutal"),
    );
    expect((screen.getByPlaceholderText("Logradouro") as HTMLInputElement).value).toBe(
      "Avenida Brasil",
    );
    expect((screen.getByPlaceholderText("Bairro") as HTMLInputElement).value).toBe("Centro");
    expect((screen.getByPlaceholderText("UF") as HTMLInputElement).value).toBe("MG");
    expect(chamadas.some((c) => c.url === "https://viacep.com.br/ws/38200000/json/")).toBe(true);
  });

  it("não sobrescreve o que o vendedor já digitou", async () => {
    respostaCep = async () => resposta(200, FRUTAL);
    abrir();
    digitar("Logradouro", "Rua do Cliente");
    digitar("CEP", "38200000");
    fireEvent.blur(screen.getByPlaceholderText("CEP"));

    await waitFor(() =>
      expect((screen.getByPlaceholderText("Município") as HTMLInputElement).value).toBe("Frutal"),
    );
    expect((screen.getByPlaceholderText("Logradouro") as HTMLInputElement).value).toBe(
      "Rua do Cliente",
    );
  });

  it("CEP incompleto não consulta", () => {
    abrir();
    digitar("CEP", "3820");
    fireEvent.blur(screen.getByPlaceholderText("CEP"));
    expect(chamadas.some((c) => c.url.startsWith("https://viacep.com.br/"))).toBe(false);
  });

  it("CEP inexistente não preenche nem impede o cadastro", async () => {
    respostaCep = async () => resposta(200, { erro: "true" });
    const { onResolved } = abrir();
    digitar("CEP", "99999999");
    fireEvent.blur(screen.getByPlaceholderText("CEP"));
    await waitFor(() =>
      expect(chamadas.some((c) => c.url.startsWith("https://viacep.com.br/"))).toBe(true),
    );
    expect((screen.getByPlaceholderText("Município") as HTMLInputElement).value).toBe("");

    digitar("Logradouro", "Rua A");
    digitar("Município", "Frutal");
    digitar("UF", "MG");
    fireEvent.click(screen.getByRole("button", { name: "Cadastrar e lançar o pedido" }));
    await waitFor(() => expect(onResolved).toHaveBeenCalled());
    const envio = chamadas.find((c) => c.url === "/api/bling/contacts");
    expect(envio?.body).toMatchObject({
      endereco: { geral: { cep: "99999999", endereco: "Rua A", municipio: "Frutal", uf: "MG" } },
    });
  });
});

describe("BlingContactResolver — aviso não bloqueante", () => {
  const AVISO =
    "Cliente vinculado, mas o Bling não aceitou atualizar o cadastro: dataNascimento: Data inválida. Corrija direto no Bling.";

  it("mostra o aviso e só segue quando o vendedor confirma", async () => {
    respostaContato = () => resposta(200, { bling_contact_id: 1, aviso: AVISO });
    const { onResolved } = abrir();
    fireEvent.click(screen.getByRole("button", { name: "Cadastrar e lançar o pedido" }));

    expect(await screen.findByText(AVISO)).toBeTruthy();
    expect(onResolved).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Seguir com o pedido" }));
    expect(onResolved).toHaveBeenCalledTimes(1);
  });

  it("sem aviso, segue direto como antes", async () => {
    const { onResolved } = abrir();
    fireEvent.click(screen.getByRole("button", { name: "Cadastrar e lançar o pedido" }));
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
  });
});
