/**
 * @vitest-environment jsdom
 *
 * A casca do modal "ValerIA de Botões". Segue a convenção de
 * `cadence-card.test.tsx`: docblock de ambiente (o default do repo é `node`),
 * imports explícitos do vitest, `global.fetch` mockado, comentários em português.
 *
 * O que estes testes protegem, em uma frase cada:
 *
 *   • A troca de abas não remonta a casca (e portanto não refaz o `GET`) — o
 *     carregamento é por ABERTURA, não por aba.
 *   • O estado de carregamento existe. Sem ele o operador vê "0 telas" por um
 *     instante e acha que o fluxo está vazio.
 *   • A MENSAGEM DO BACKEND chega à tela literal, nos dois caminhos (o `GET` e o
 *     `PUT`) e nas duas chaves em que ela pode vir (`detail` do FastAPI, `error` do
 *     proxy do Next). O 503 da migration pendente é o estado real do banco hoje: se
 *     ele virar "Erro ao carregar", ninguém descobre que falta aplicar o SQL.
 *
 * Nota de cobertura: o salvamento é exercitado em `gravarConteudo`, que É a
 * implementação (o `salvar` da casca são seis linhas de `setState` em volta dela).
 * Enquanto `valeria-flow-editor.tsx` não existe, nenhum controle renderizado chama
 * `salvar` — e pôr um botão só para o teste alcançá-lo deixaria UI morta no produto.
 * Que a mensagem recusada aparece na faixa `role="alert"` está coberto pelo caminho
 * do `GET`, que escreve no MESMO estado `erro`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  ValeriaFlowModal,
  aplicarItem,
  gravarConteudo,
  mensagemDeErro,
} from "./valeria-flow-modal";
import type { FluxoResposta, NoFluxo, ReservadoFluxo } from "./valeria-flow-types";

const N0: NoFluxo = {
  id: "N0",
  tipo: "no",
  rotulo_interno: "N0 · Setor",
  tela: "lista",
  ramo: "entrada",
  corpo: "Oi! Com o que você trabalha?",
  corpo_default: "Oi! Com o que você trabalha?",
  foto: null,
  produto: null,
  botoes: [
    {
      id: "atacado",
      rotulo: "Revenda / atacado",
      rotulo_default: "Revenda / atacado",
      destino: "N1",
      grava: [["setor", "atacado"]],
      descricao: "Quem compra para revender",
      limite_rotulo: 24,
      editado: false,
    },
  ],
  editaveis: ["corpo", "rotulos"],
  rotulos_antigos: [],
  editado: false,
};

const NUDGE: ReservadoFluxo = {
  chave: "__nudge__",
  id: "__nudge__",
  tipo: "reservado",
  rotulo_interno: "Reoferecimento (nudge)",
  corpo: "Ainda por aqui?",
  corpo_default: "Ainda por aqui?",
  editaveis: ["corpo"],
  editado: false,
  teto: 3,
};

const FLUXO: FluxoResposta = {
  flow_id: "valeria_botoes_v1",
  no_entrada: "N0",
  limites: { rotulo_botao: 20, titulo_lista: 24, desc_lista: 72, max_botoes: 3, max_linhas_lista: 10 },
  editaveis: { no: ["corpo", "rotulos"], terminal: ["corpo"] },
  nos: [N0],
  terminais: [
    {
      id: "T_HANDOFF",
      tipo: "terminal",
      rotulo_interno: "T_HANDOFF · Passa para o vendedor",
      corpo: "Vou te passar para o João.",
      corpo_default: "Vou te passar para o João.",
      vendedor: "joao",
      tags: ["handoff"],
      silenciar_ia: true,
      handoff: true,
      optout: false,
      prazos: false,
      editaveis: ["corpo"],
      editado: false,
    },
  ],
  nudge: NUDGE,
  rotulo_lista: {
    chave: "__rotulo_lista__",
    id: "__rotulo_lista__",
    tipo: "reservado",
    rotulo_interno: "Botão que abre a folha de opções",
    corpo: "Ver opções",
    corpo_default: "Ver opções",
    editaveis: ["corpo"],
    editado: false,
    limite: 20,
  },
  prazos: [{ id: "p30", rotulo: "Em 30 dias", destino: "T_ADIADO", dias: 30, editavel: false }],
};

type Corpo = Record<string, unknown>;
const resposta = (corpo: Corpo, status = 200) =>
  ({ ok: status < 400, status, statusText: "Bad Request", json: async () => corpo }) as Response;

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ValeriaFlowModal — carregamento", () => {
  it("não renderiza nada nem busca o fluxo enquanto está fechado", () => {
    const { container } = render(<ValeriaFlowModal open={false} onClose={() => {}} />);
    expect(container.innerHTML).toBe("");
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("mostra o estado de carregamento antes da resposta e o troca pelo conteúdo", async () => {
    vi.mocked(global.fetch).mockResolvedValue(resposta(FLUXO as unknown as Corpo));
    render(<ValeriaFlowModal open onClose={() => {}} />);

    // Antes da resposta: o aviso de carregamento, e nenhuma contagem de telas.
    expect(screen.getByText("Carregando o fluxo…")).toBeTruthy();

    await waitFor(() => expect(screen.queryByText("Carregando o fluxo…")).toBeNull());
    expect(screen.getByText(/1 telas e 1 desfechos/)).toBeTruthy();
    expect(global.fetch).toHaveBeenCalledWith("/api/valeria-flow", expect.objectContaining({ cache: "no-store" }));
  });
});

describe("ValeriaFlowModal — abas", () => {
  it("troca para 'Onde está ativo' sem refazer o GET", async () => {
    vi.mocked(global.fetch).mockResolvedValue(resposta(FLUXO as unknown as Corpo));
    render(<ValeriaFlowModal open onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/1 telas e 1 desfechos/)).toBeTruthy());

    const fluxo = screen.getByRole("tab", { name: "Fluxo" });
    const canais = screen.getByRole("tab", { name: "Onde está ativo" });
    expect(fluxo.getAttribute("aria-selected")).toBe("true");
    expect(canais.getAttribute("aria-selected")).toBe("false");

    fireEvent.click(canais);

    expect(canais.getAttribute("aria-selected")).toBe("true");
    expect(fluxo.getAttribute("aria-selected")).toBe("false");
    // O painel de canais recebeu o flow_id que veio do servidor.
    expect(screen.getByText(/valeria_botoes_v1/)).toBeTruthy();
    // E o fluxo NÃO foi buscado de novo: o carregamento é por abertura.
    expect(global.fetch).toHaveBeenCalledTimes(1);

    fireEvent.click(fluxo);
    expect(screen.getByText(/1 telas e 1 desfechos/)).toBeTruthy();
  });

  it("anda entre as abas com as setas do teclado", async () => {
    vi.mocked(global.fetch).mockResolvedValue(resposta(FLUXO as unknown as Corpo));
    render(<ValeriaFlowModal open onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/1 telas e 1 desfechos/)).toBeTruthy());

    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Onde está ativo" }).getAttribute("aria-selected")).toBe("true");

    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Fluxo" }).getAttribute("aria-selected")).toBe("true");
  });
});

describe("ValeriaFlowModal — o erro do backend chega literal", () => {
  it("mostra o 503 da migration pendente com as palavras do backend", async () => {
    const migration =
      "a migration 20260929_valeria_botoes.sql ainda não foi aplicada neste banco — " +
      "aplique-a no Supabase antes de editar ou ativar";
    vi.mocked(global.fetch).mockResolvedValue(resposta({ detail: migration }, 503));
    render(<ValeriaFlowModal open onClose={() => {}} />);

    const alerta = await waitFor(() => screen.getByRole("alert"));
    expect(alerta.textContent).toBe(migration);
    // E não sobra o esqueleto de carregamento por cima do erro.
    expect(screen.queryByText("Carregando o fluxo…")).toBeNull();
  });

  it("cai numa frase própria quando a rede falha e não há corpo nenhum", async () => {
    vi.mocked(global.fetch).mockRejectedValue(new Error("Failed to fetch"));
    render(<ValeriaFlowModal open onClose={() => {}} />);
    // A mensagem do `Error` da rede é o que o navegador deu; o importante é que a
    // faixa aparece em vez de a tela ficar carregando para sempre.
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.queryByText("Carregando o fluxo…")).toBeNull();
  });

  it("ignora o AbortError de quem fechou o modal antes da resposta", async () => {
    const abortado = Object.assign(new Error("aborted"), { name: "AbortError" });
    vi.mocked(global.fetch).mockRejectedValue(abortado);
    render(<ValeriaFlowModal open onClose={() => {}} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("gravarConteudo — a recusa do backend é repassada palavra por palavra", () => {
  it("repassa o 400 de rótulo acima do limite da Meta", async () => {
    const recusa = "o rótulo 'Quero saber sobre revenda' tem 26 caracteres e o limite da Meta é 20";
    vi.mocked(global.fetch).mockResolvedValue(resposta({ detail: recusa }, 400));

    const { item, erro } = await gravarConteudo("N0", { rotulos: { atacado: "Quero saber sobre revenda" } });

    expect(item).toBeNull();
    expect(erro).toBe(recusa);
  });

  it("repassa o 400 de corpo vazio e o 404 de nó inexistente", async () => {
    vi.mocked(global.fetch).mockResolvedValue(resposta({ detail: "o corpo não pode ficar vazio" }, 400));
    expect((await gravarConteudo("N0", { corpo: "" })).erro).toBe("o corpo não pode ficar vazio");

    vi.mocked(global.fetch).mockResolvedValue(resposta({ detail: "nó 'N99' não existe no fluxo" }, 404));
    expect((await gravarConteudo("N99", { corpo: "x" })).erro).toBe("nó 'N99' não existe no fluxo");
  });

  it("devolve o item mesclado que o PUT respondeu, em vez de um otimismo local", async () => {
    const salvo = { ...N0, corpo: "Texto novo", editado: true };
    vi.mocked(global.fetch).mockResolvedValue(resposta(salvo as unknown as Corpo));

    const { item, erro } = await gravarConteudo("N0", { corpo: "Texto novo" });

    expect(erro).toBeNull();
    expect(item).toMatchObject({ id: "N0", corpo: "Texto novo", editado: true });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/valeria-flow/N0",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ corpo: "Texto novo" }) }),
    );
  });

  it("não explode quando a resposta de erro não é JSON", async () => {
    vi.mocked(global.fetch).mockResolvedValue({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: async () => { throw new Error("não é JSON"); },
    } as unknown as Response);

    expect((await gravarConteudo("N0", { corpo: "x" })).erro).toBe("Não foi possível salvar este texto.");
  });
});

describe("mensagemDeErro", () => {
  it("prefere `detail` (FastAPI) e aceita `error` (o proxy do Next)", () => {
    expect(mensagemDeErro({ detail: "do backend" }, "padrão")).toBe("do backend");
    expect(mensagemDeErro({ error: "Backend indisponível" }, "padrão")).toBe("Backend indisponível");
  });

  it("junta as mensagens de um `detail` em lista (422 do Pydantic, problemas[])", () => {
    expect(mensagemDeErro({ detail: [{ msg: "campo obrigatório" }, { msg: "tipo inválido" }] }, "padrão"))
      .toBe("campo obrigatório · tipo inválido");
    expect(mensagemDeErro({ detail: { problemas: [{ mensagem: "nó N3 sem template" }] } }, "padrão"))
      .toBe("nó N3 sem template");
  });

  it("usa o padrão só quando não há mensagem nenhuma", () => {
    expect(mensagemDeErro({}, "padrão")).toBe("padrão");
    expect(mensagemDeErro(null, "padrão")).toBe("padrão");
    expect(mensagemDeErro({ detail: "   " }, "padrão")).toBe("padrão");
  });
});

describe("aplicarItem", () => {
  it("substitui o nó pelo que o servidor devolveu, sem tocar nos outros", () => {
    const depois = aplicarItem(FLUXO, { ...N0, corpo: "Texto novo", editado: true });
    expect(depois.nos[0].corpo).toBe("Texto novo");
    expect(depois.terminais).toBe(FLUXO.terminais);
  });

  it("acerta o terminal e as duas chaves reservadas pelo `id`", () => {
    const comTerminal = aplicarItem(FLUXO, { ...FLUXO.terminais[0], corpo: "Outro desfecho" });
    expect(comTerminal.terminais[0].corpo).toBe("Outro desfecho");

    const comNudge = aplicarItem(FLUXO, { ...NUDGE, corpo: "Continua aí?" });
    expect(comNudge.nudge.corpo).toBe("Continua aí?");

    const comRotulo = aplicarItem(FLUXO, { ...FLUXO.rotulo_lista, corpo: "Escolher" });
    expect(comRotulo.rotulo_lista.corpo).toBe("Escolher");
    // O reservado não vaza para a lista de nós.
    expect(comRotulo.nos).toBe(FLUXO.nos);
  });
});
