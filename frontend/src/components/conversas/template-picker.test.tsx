/**
 * @vitest-environment jsdom
 *
 * Seletor de modelo extraído do TemplateDispatchModal (cartão 70d844a6) para o
 * modal "Iniciar conversa" reaproveitar: lista os modelos aprovados do número,
 * variáveis e prévia, e entrega o payload pronto do envio por `onChange`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TemplatePicker } from "./template-picker";

const modelosPorCanal: Record<string, unknown[]> = {
  "canal-1": [
    {
      name: "boas_vindas",
      language: "pt_BR",
      category: "MARKETING",
      body: "Olá {{1}}, aqui é da {{2}}.",
      params: [
        { index: 1, paramName: "primeiro_nome", example: "Ana" },
        { index: 2, paramName: "loja", example: "Canastra" },
      ],
      paramsType: "positional",
    },
    {
      name: "simples",
      language: "pt_BR",
      category: "UTILITY",
      body: "Oi, tudo bem?",
      params: [],
      paramsType: "none",
    },
  ],
  "canal-2": [
    { name: "outro_numero", language: "en_US", category: "MARKETING", body: "Hi", params: [], paramsType: "none" },
  ],
};

type Resposta = { ok: boolean; status: number; json: () => Promise<unknown> };
const fetchMock = vi.fn(async (url: string): Promise<Resposta> => {
  const canal = String(url).match(/channels\/([^/]+)\/templates/)?.[1] ?? "";
  return { ok: true, status: 200, json: async () => modelosPorCanal[canal] ?? [] };
});

const lead = { name: "Micheli Souza", phone: "5534988861441", company: null };

beforeEach(() => {
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("TemplatePicker", () => {
  it("lista os modelos do canal", async () => {
    render(<TemplatePicker channelId="canal-1" lead={lead} onChange={vi.fn()} />);
    expect(screen.getByText("Buscando templates...")).toBeTruthy();
    expect(await screen.findByText("boas_vindas")).toBeTruthy();
    expect(screen.getByText("simples")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/channels/canal-1/templates");
  });

  it("selecionar chama onChange com nome, idioma e corpo resolvido; desmarcar manda null", async () => {
    const onChange = vi.fn();
    render(<TemplatePicker channelId="canal-1" lead={lead} onChange={onChange} />);
    fireEvent.click(await screen.findByText("simples"));
    expect(onChange).toHaveBeenLastCalledWith({
      template_name: "simples",
      template_language_code: "pt_BR",
      template_variables: null,
      template_body: "Oi, tudo bem?",
    });
    fireEvent.click(screen.getByText("simples"));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("variável do lead é resolvida e a manual entra em template_variables", async () => {
    const onChange = vi.fn();
    render(<TemplatePicker channelId="canal-1" lead={lead} onChange={onChange} />);
    fireEvent.click(await screen.findByText("boas_vindas"));
    expect(onChange).toHaveBeenLastCalledWith({
      template_name: "boas_vindas",
      template_language_code: "pt_BR",
      template_variables: { __params_type__: "positional", primeiro_nome: "Micheli", loja: "Canastra" },
      template_body: "Olá Micheli, aqui é da [Canastra].",
    });
    fireEvent.change(screen.getByPlaceholderText("Canastra"), { target: { value: "Loja Azul" } });
    expect(onChange).toHaveBeenLastCalledWith({
      template_name: "boas_vindas",
      template_language_code: "pt_BR",
      template_variables: { __params_type__: "positional", primeiro_nome: "Micheli", loja: "Loja Azul" },
      template_body: "Olá Micheli, aqui é da Loja Azul.",
    });
  });

  it("trocar channelId busca de novo", async () => {
    const { rerender } = render(<TemplatePicker channelId="canal-1" lead={lead} onChange={vi.fn()} />);
    await screen.findByText("boas_vindas");
    rerender(<TemplatePicker channelId="canal-2" lead={lead} onChange={vi.fn()} />);
    expect(await screen.findByText("outro_numero")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/channels/canal-2/templates");
    await waitFor(() => expect(screen.queryByText("boas_vindas")).toBeNull());
  });

  it("erro e lista vazia aparecem como hoje", async () => {
    fetchMock.mockImplementationOnce(async () => ({ ok: false, status: 500, json: async () => ({ error: "Falha na Meta" }) }));
    render(<TemplatePicker channelId="canal-1" lead={lead} onChange={vi.fn()} />);
    expect(await screen.findByText("Falha na Meta")).toBeTruthy();
    cleanup();
    render(<TemplatePicker channelId="canal-x" lead={lead} onChange={vi.fn()} />);
    expect(await screen.findByText("Nenhum template aprovado encontrado.")).toBeTruthy();
  });
});
