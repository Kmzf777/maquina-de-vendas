/**
 * @vitest-environment jsdom
 *
 * Modal "Iniciar conversa" (cartão 70d844a6): lead sem conversa → escolhe o
 * número e o modelo aprovado → POST /api/leads/<id>/iniciar-conversa. Fetch é
 * dublê: nada sai para a Meta.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { IniciarConversaModal } from "./iniciar-conversa-modal";

type Resposta = { ok: boolean; status: number; json: () => Promise<unknown> };
const resp = (status: number, body: unknown): Resposta => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

const lead = { id: "L1", name: "Micheli Souza", phone: "5534988861441", company: null };
let getBody: unknown;
let postResposta: Resposta;

const modelos: Record<string, unknown[]> = {
  "canal-1": [{ name: "modelo_um", language: "pt_BR", category: "MARKETING", body: "Oi {{1}}", params: [{ index: 1, paramName: "primeiro_nome", example: "Ana" }], paramsType: "positional" }],
  "canal-2": [{ name: "modelo_dois", language: "pt_BR", category: "UTILITY", body: "Olá!", params: [], paramsType: "none" }],
};

const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
  const u = String(url);
  if (u === "/api/leads/L1/iniciar-conversa") {
    return init?.method === "POST" ? postResposta : resp(200, getBody);
  }
  const canal = u.match(/channels\/([^/]+)\/templates/)?.[1];
  if (canal) return resp(200, modelos[canal] ?? []);
  return resp(404, { error: "?" });
});

beforeEach(() => {
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
  getBody = {
    lead,
    telefone: "5534988861441",
    canais: [
      { id: "canal-1", name: "NUMERO ARTHUR" },
      { id: "canal-2", name: "NUMERO JOAO" },
    ],
  };
  postResposta = resp(200, { conversation_id: "conv-novo" });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const templatesChamados = () =>
  fetchMock.mock.calls.map((c) => String(c[0])).filter((u) => u.includes("/templates"));

describe("IniciarConversaModal", () => {
  it("carrega o lead e lista os números", async () => {
    render(<IniciarConversaModal leadId="L1" onClose={vi.fn()} onIniciada={vi.fn()} />);
    expect(screen.getByText("Carregando…")).toBeTruthy();
    expect(await screen.findByText("Iniciar conversa")).toBeTruthy();
    expect(screen.getByText(/Micheli Souza/)).toBeTruthy();
    expect(screen.getByText(/5534988861441/)).toBeTruthy();
    const select = screen.getByLabelText("Número") as HTMLSelectElement;
    const opcoes = Array.from(select.options).map((o) => o.textContent);
    expect(opcoes).toContain("NUMERO ARTHUR");
    expect(opcoes).toContain("NUMERO JOAO");
    expect(templatesChamados()).toHaveLength(0); // dois números: nenhum escolhido ainda
  });

  it("um número só já vem escolhido", async () => {
    getBody = { lead, telefone: "5534988861441", canais: [{ id: "canal-2", name: "NUMERO JOAO" }] };
    render(<IniciarConversaModal leadId="L1" onClose={vi.fn()} onIniciada={vi.fn()} />);
    expect(await screen.findByText("modelo_dois")).toBeTruthy();
    expect((screen.getByLabelText("Número") as HTMLSelectElement).value).toBe("canal-2");
  });

  it("escolher o número busca os modelos daquele número", async () => {
    render(<IniciarConversaModal leadId="L1" onClose={vi.fn()} onIniciada={vi.fn()} />);
    const select = (await screen.findByLabelText("Número")) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "canal-1" } });
    expect(await screen.findByText("modelo_um")).toBeTruthy();
    fireEvent.change(select, { target: { value: "canal-2" } });
    expect(await screen.findByText("modelo_dois")).toBeTruthy();
    expect(screen.queryByText("modelo_um")).toBeNull();
    expect(templatesChamados()).toEqual(["/api/channels/canal-1/templates", "/api/channels/canal-2/templates"]);
  });

  it("enviar manda o corpo certo e chama onIniciada com a conversa nova", async () => {
    const onIniciada = vi.fn();
    render(<IniciarConversaModal leadId="L1" onClose={vi.fn()} onIniciada={onIniciada} />);
    const enviar = (await screen.findByRole("button", { name: "Enviar" })) as HTMLButtonElement;
    expect(enviar.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Número"), { target: { value: "canal-1" } });
    fireEvent.click(await screen.findByText("modelo_um"));
    expect(enviar.disabled).toBe(false);
    fireEvent.click(enviar);

    await waitFor(() => expect(onIniciada).toHaveBeenCalledWith("conv-novo"));
    const post = fetchMock.mock.calls.find((c) => c[1]?.method === "POST");
    expect(post?.[0]).toBe("/api/leads/L1/iniciar-conversa");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      channel_id: "canal-1",
      template_name: "modelo_um",
      template_language_code: "pt_BR",
      template_variables: { __params_type__: "positional", primeiro_nome: "Micheli" },
      template_body: "Oi Micheli",
    });
  });

  it("erro da rota aparece no modal, que continua aberto", async () => {
    postResposta = resp(403, { error: "Sem acesso a este número" });
    const onIniciada = vi.fn();
    const onClose = vi.fn();
    render(<IniciarConversaModal leadId="L1" onClose={onClose} onIniciada={onIniciada} />);
    fireEvent.change(await screen.findByLabelText("Número"), { target: { value: "canal-2" } });
    fireEvent.click(await screen.findByText("modelo_dois"));
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    expect(await screen.findByText("Sem acesso a este número")).toBeTruthy();
    expect(onIniciada).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("sem números: avisa e não mostra modelos", async () => {
    getBody = { lead, telefone: "5534988861441", canais: [] };
    render(<IniciarConversaModal leadId="L1" onClose={vi.fn()} onIniciada={vi.fn()} />);
    expect(await screen.findByText("Você não tem número do WhatsApp para iniciar conversa.")).toBeTruthy();
    expect(screen.queryByLabelText("Número")).toBeNull();
    expect(templatesChamados()).toHaveLength(0);
  });

  /** Abre o modal, escolhe canal-2 e o modelo, e devolve o botão Enviar. */
  async function prontoParaEnviar(props: { onClose?: () => void; onIniciada?: (id: string) => unknown }) {
    render(
      <IniciarConversaModal
        leadId="L1"
        onClose={props.onClose ?? vi.fn()}
        onIniciada={(props.onIniciada ?? vi.fn()) as (id: string) => void}
      />,
    );
    fireEvent.change(await screen.findByLabelText("Número"), { target: { value: "canal-2" } });
    fireEvent.click(await screen.findByText("modelo_dois"));
    return screen.getByRole("button", { name: "Enviar" }) as HTMLButtonElement;
  }
  const posts = () => fetchMock.mock.calls.filter((c) => c[1]?.method === "POST");
  const fundo = () => screen.getByRole("dialog").parentElement as HTMLElement;

  it("depois do envio certo, Enviar fica travado em 'Enviado' e não manda de novo", async () => {
    const onIniciada = vi.fn();
    const enviar = await prontoParaEnviar({ onIniciada });
    fireEvent.click(enviar);
    await waitFor(() => expect(onIniciada).toHaveBeenCalledTimes(1));
    const travado = (await screen.findByRole("button", { name: "Enviado" })) as HTMLButtonElement;
    await new Promise((r) => setTimeout(r, 0));
    expect(travado.disabled).toBe(true);
    fireEvent.click(travado);
    expect(posts()).toHaveLength(1);
  });

  it("onIniciada assíncrono é aguardado: enquanto não termina, fundo, X e Cancelar não fecham", async () => {
    let terminar!: () => void;
    const onIniciada = vi.fn(() => new Promise<void>((r) => { terminar = r; }));
    const onClose = vi.fn();
    const enviar = await prontoParaEnviar({ onIniciada, onClose });
    fireEvent.click(enviar);
    await waitFor(() => expect(onIniciada).toHaveBeenCalledWith("conv-novo"));
    await new Promise((r) => setTimeout(r, 0));
    fireEvent.click(fundo());
    fireEvent.click(screen.getByRole("button", { name: "Fechar" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(onClose).not.toHaveBeenCalled();
    terminar();
    const travado = (await screen.findByRole("button", { name: "Enviado" })) as HTMLButtonElement;
    expect(travado.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Fechar" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(posts()).toHaveLength(1);
  });

  it("durante o POST, fundo e X não fecham o modal", async () => {
    let responder!: (r: Resposta) => void;
    const pendente = new Promise<Resposta>((r) => { responder = r; });
    const onClose = vi.fn();
    const enviar = await prontoParaEnviar({ onClose });
    fetchMock.mockImplementationOnce(() => pendente);
    fireEvent.click(enviar);
    expect(await screen.findByRole("button", { name: "Enviando..." })).toBeTruthy();
    fireEvent.click(fundo());
    fireEvent.click(screen.getByRole("button", { name: "Fechar" }));
    expect(onClose).not.toHaveBeenCalled();
    responder(resp(200, { conversation_id: "conv-novo" }));
    expect(await screen.findByRole("button", { name: "Enviado" })).toBeTruthy();
  });

  it("falha incerta (502 com conversation_id): mostra o aviso e não deixa reenviar", async () => {
    postResposta = resp(502, {
      error: "Não deu para confirmar o envio. Confira a conversa antes de tentar de novo.",
      conversation_id: "conv-novo",
    });
    const enviar = await prontoParaEnviar({});
    fireEvent.click(enviar);
    expect(await screen.findByText(/Não deu para confirmar o envio/)).toBeTruthy();
    expect(enviar.disabled).toBe(true);
    fireEvent.click(enviar);
    expect(posts()).toHaveLength(1);
  });
});
