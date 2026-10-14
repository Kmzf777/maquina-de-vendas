/**
 * @vitest-environment jsdom
 *
 * "+ Adicionar lead" (qualificação) gravava direto no Supabase, sem normalizar o
 * telefone nem procurar o lead existente — e duplicava número já cadastrado em
 * outro formato (cartão b747da43). Agora passa pelo POST /api/leads, que
 * normaliza e devolve 409 com o nome do lead existente; o erro aparece no form.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";

// Gravar direto no Supabase do navegador é justamente o caminho que duplicava.
const supabaseFrom = vi.fn();
vi.mock("@/lib/supabase/client", () => ({ createClient: () => ({ from: supabaseFrom }) }));

import { QuickAddLead } from "./quick-add-lead";

const resposta = (corpo: Record<string, unknown>, status = 200) =>
  ({ ok: status < 400, status, json: async () => corpo }) as Response;

function abrirEPreencher(telefone: string, nome = "") {
  fireEvent.click(screen.getByText("+ Adicionar lead"));
  fireEvent.change(screen.getByPlaceholderText("Telefone *"), { target: { value: telefone } });
  if (nome) fireEvent.change(screen.getByPlaceholderText("Nome"), { target: { value: nome } });
  fireEvent.click(screen.getByText("Criar"));
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("QuickAddLead", () => {
  it("cria pelo POST /api/leads com etapa e controle humano", async () => {
    fetchMock.mockResolvedValue(resposta({ id: "novo" }, 201));
    render(<QuickAddLead stage="secretaria" humanControl />);

    abrirEPreencher("(49) 9917-0363", "Douglas");

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/leads");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      name: "Douglas",
      phone: "(49) 9917-0363",
      company: null,
      stage: "secretaria",
      human_control: true,
      channel: "manual",
    });
    expect(supabaseFrom).not.toHaveBeenCalled();
    // Sucesso fecha o formulário.
    await waitFor(() => expect(screen.getByText("+ Adicionar lead")).toBeTruthy());
  });

  it("número já cadastrado mostra o erro da API e mantém o formulário aberto", async () => {
    fetchMock.mockResolvedValue(
      resposta({ error: "Lead com este telefone já existe: Douglas Schutz", lead: { id: "l1" } }, 409),
    );
    render(<QuickAddLead stage="secretaria" />);

    abrirEPreencher("4999170363");

    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toBe("Lead com este telefone já existe: Douglas Schutz");
    expect(screen.getByPlaceholderText("Telefone *")).toBeTruthy();
  });

  it("cancelar limpa o erro", async () => {
    fetchMock.mockResolvedValue(resposta({ error: "Telefone inválido: 3 dígito(s)" }, 422));
    render(<QuickAddLead stage="secretaria" />);

    abrirEPreencher("123");
    await screen.findByRole("alert");

    fireEvent.click(screen.getByText("Cancelar"));
    fireEvent.click(screen.getByText("+ Adicionar lead"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("erro de rede mostra a mensagem genérica e destrava o botão", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<QuickAddLead stage="secretaria" />);

    abrirEPreencher("4999170363");

    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toBe("Erro ao criar lead");
    const botao = screen.getByText("Criar") as HTMLButtonElement;
    expect(botao.disabled).toBe(false);
  });
});
