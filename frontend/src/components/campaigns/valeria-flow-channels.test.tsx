/**
 * @vitest-environment jsdom
 *
 * O painel "Onde está ativo". Docblock de ambiente porque o default do repo é `node`
 * (`vitest.config.ts`) — sem ele o erro parece dependência faltando.
 *
 * Sem `@testing-library/jest-dom` (não está nas dependências do projeto) — as
 * asserções usam a API crua do DOM, mesmo padrão de `bling-order-form.test.tsx`.
 *
 * O que estes testes travam, e o modo de falha de cada um:
 *
 *   • O AVISO DE PERFIL COMPARTILHADO aparece, e CITA os canais acoplados. Sem ele,
 *     uma pessoa olhando dois canais não tem como saber que eles dividem um
 *     `agent_profile_id` — é o caso real do canal do João (`a3a607b1`) e da ValerIA
 *     (`674beb13`), verificado em produção em 09/09. E ele NÃO aparece onde não há
 *     acoplamento: um aviso que aparece sempre é um aviso que ninguém lê.
 *
 *   • O AVISO DE FLUXO DESLIGADO aparece quando `ligado: false`, que é o estado do
 *     ambiente hoje (`VALERIA_BOTOES_ENABLED` não está no `.env`, default off). Sem
 *     ele o operador ativa, nada acontece, e conclui que a feature está quebrada.
 *
 *   • O `POST` manda o `channel_id` do canal que a pessoa escolheu. Trocar de canal
 *     aqui é apontar o número errado para o robô.
 *
 *   • A MENSAGEM DO BACKEND chega VERBATIM (400 e o 503 que nomeia a migration
 *     `20260929_valeria_botoes.sql`). É o único texto acionável da recusa.
 *
 *   • Os botões travam durante o `POST`, e a lista é RELIDA depois do sucesso — o
 *     `perfil_compartilhado` dos outros canais muda com a ativação, e só o servidor
 *     sabe o novo agrupamento.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import {
  ValeriaFlowChannels,
  listarNomes,
  nomesIrmaos,
  type CanaisResposta,
  type CanalDoFluxo,
} from "./valeria-flow-channels";

const FLOW_ID = "valeria_botoes_v1";

/** O perfil que os dois canais de produção dividem hoje. */
const PERFIL_COMPARTILHADO = {
  id: "perfil-llm-1",
  name: "Valéria Inbound",
  kind: "llm",
  flow_id: null,
};

const CANAL_VALERIA: CanalDoFluxo = {
  id: "674beb13",
  name: "ValerIA",
  phone: "5534988860000",
  mode: "ai",
  is_active: true,
  agent_profile_id: PERFIL_COMPARTILHADO.id,
  perfil: PERFIL_COMPARTILHADO,
  perfil_compartilhado: true,
  compartilhado_com: ["João"],
  atende_este_fluxo: false,
};

const CANAL_JOAO: CanalDoFluxo = {
  id: "a3a607b1",
  name: "João",
  phone: "5534988861441",
  mode: "human",
  is_active: true,
  agent_profile_id: PERFIL_COMPARTILHADO.id,
  perfil: PERFIL_COMPARTILHADO,
  perfil_compartilhado: true,
  compartilhado_com: ["ValerIA"],
  atende_este_fluxo: false,
};

/** Um canal com perfil só dele: nada a avisar. */
const CANAL_SOZINHO: CanalDoFluxo = {
  id: "c3",
  name: "Suporte",
  phone: "5534988862222",
  mode: "ai",
  is_active: true,
  agent_profile_id: "perfil-llm-2",
  perfil: { id: "perfil-llm-2", name: "Suporte LLM", kind: "llm", flow_id: null },
  perfil_compartilhado: false,
  compartilhado_com: [],
  atende_este_fluxo: false,
};

function corpo(canais: CanalDoFluxo[], ligado: boolean): CanaisResposta {
  return { flow_id: FLOW_ID, ligado, canais };
}

/** `Response` mínimo — o painel só lê `.ok` e `.json()`. */
const resposta = (body: unknown, ok = true, status = 200) =>
  ({ ok, status, json: async () => body }) as Response;

interface Chamada {
  url: string;
  method: string;
  body: unknown;
}

/**
 * `fetch` roteado por URL. `gets` são os corpos sucessivos do `GET /channels` (o
 * último repete), para o teste de releitura poder devolver uma lista DIFERENTE depois
 * da ativação.
 */
function instalarFetch(gets: unknown[], post?: () => Promise<Response>): Chamada[] {
  const fila = [...gets];
  const chamadas: Chamada[] = [];
  global.fetch = vi.fn((url: unknown, init?: RequestInit) => {
    const alvo = String(url);
    chamadas.push({
      url: alvo,
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? JSON.parse(init.body) : null,
    });
    if (alvo.includes("/activate")) {
      return post ? post() : Promise.resolve(resposta({ channel_id: "x", ligado: true }));
    }
    return Promise.resolve(resposta(fila.length > 1 ? fila.shift() : fila[0]));
  }) as unknown as typeof fetch;
  return chamadas;
}

/** O `<li>` de um canal, para não confundir o botão "Ativar" de um com o do outro. */
function linha(nome: string): HTMLElement {
  const alvo = screen.getByText(nome).closest("li");
  if (!alvo) throw new Error(`linha do canal ${nome} não encontrada`);
  return alvo as HTMLElement;
}

function botao(escopo: HTMLElement, nome: string): HTMLButtonElement {
  return within(escopo).getByRole("button", { name: nome }) as HTMLButtonElement;
}

/** Renderiza e espera o `GET` inicial pousar. */
async function montar(ligado = true, canais = [CANAL_VALERIA, CANAL_JOAO, CANAL_SOZINHO]) {
  const chamadas = instalarFetch([corpo(canais, ligado)]);
  render(<ValeriaFlowChannels flowId={FLOW_ID} />);
  await waitFor(() => expect(screen.getByText(canais[0].name as string)).toBeTruthy());
  return chamadas;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ═══════════════════════════════════════════════════════════════════════════════
describe("ValeriaFlowChannels — aviso de perfil compartilhado", () => {
  it("avisa e CITA o outro canal quando `perfil_compartilhado` é true", async () => {
    await montar();

    const daValeria = within(linha("ValerIA")).getByText(/Perfil compartilhado com/);
    expect(daValeria.textContent).toContain("João");

    // E o recíproco: a linha do João cita a ValerIA. Os dois lados do acoplamento
    // precisam do aviso — quem abre a tela pode clicar em qualquer um deles.
    const doJoao = within(linha("João")).getByText(/Perfil compartilhado com/);
    expect(doJoao.textContent).toContain("ValerIA");
  });

  it("explica que Ativar cria um perfil NOVO em vez de editar o compartilhado", async () => {
    await montar();
    const texto = linha("ValerIA").textContent ?? "";
    expect(texto).toContain("MESMO perfil de agente");
    expect(texto).toContain("cria um perfil NOVO");
    expect(texto).toContain("continua no perfil atual");
  });

  it("NÃO avisa quando `perfil_compartilhado` é false", async () => {
    await montar(true, [CANAL_SOZINHO]);
    expect(screen.queryByText(/Perfil compartilhado/)).toBeNull();
  });

  it("cai no genérico quando os irmãos vêm sem nome (o router não filtra NULL)", async () => {
    const semNome: CanalDoFluxo = {
      ...CANAL_SOZINHO,
      perfil_compartilhado: true,
      compartilhado_com: [null],
    };
    await montar(true, [semNome]);
    // "compartilhado com " seguido de nada seria uma frase truncada na cara do operador.
    expect(screen.getByText(/Perfil compartilhado com outro canal/)).toBeTruthy();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
describe("ValeriaFlowChannels — kill switch", () => {
  it("mostra o aviso de fluxo DESLIGADO e nomeia a variável de ambiente", async () => {
    await montar(false);
    expect(screen.getByText("O fluxo de botões está DESLIGADO")).toBeTruthy();
    expect(screen.getAllByText("VALERIA_BOTOES_ENABLED").length).toBeGreaterThan(0);
    expect(screen.getByText("VALERIA_BOTOES_ENABLED=true")).toBeTruthy();
  });

  it("não mostra o aviso quando a chave está ligada", async () => {
    await montar(true);
    expect(screen.queryByText("O fluxo de botões está DESLIGADO")).toBeNull();
  });

  it("depois de ativar com a chave desligada, diz que nada será respondido ainda", async () => {
    const chamadas = instalarFetch([corpo([CANAL_SOZINHO], false)], () =>
      Promise.resolve(resposta({ channel_id: CANAL_SOZINHO.id, ligado: false })),
    );
    render(<ValeriaFlowChannels flowId={FLOW_ID} />);
    await waitFor(() => expect(screen.getByText("Suporte")).toBeTruthy());

    fireEvent.click(botao(linha("Suporte"), "Ativar"));
    fireEvent.click(botao(linha("Suporte"), "Confirmar ativação"));

    await waitFor(() =>
      expect(screen.getByText(/o fluxo continua DESLIGADO/)).toBeTruthy(),
    );
    expect(chamadas.some((c) => c.method === "POST")).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
describe("ValeriaFlowChannels — ativação", () => {
  it("só pede o POST depois da confirmação no painel (nenhum diálogo nativo)", async () => {
    const chamadas = await montar();

    fireEvent.click(botao(linha("João"), "Ativar"));
    // Clicar em "Ativar" NÃO ativa: abre a confirmação.
    expect(chamadas.filter((c) => c.method === "POST")).toHaveLength(0);
    expect(within(linha("João")).getByRole("group", { name: /Confirmar ativação em João/ })).toBeTruthy();
  });

  it("manda o `channel_id` do canal escolhido, e só dele", async () => {
    const chamadas = await montar();

    fireEvent.click(botao(linha("João"), "Ativar"));
    fireEvent.click(botao(linha("João"), "Confirmar ativação"));

    await waitFor(() => expect(chamadas.filter((c) => c.method === "POST")).toHaveLength(1));
    const posts = chamadas.filter((c) => c.method === "POST");
    expect(posts[0].url).toContain("/api/valeria-flow/activate");
    expect(posts[0].body).toEqual({ channel_id: "a3a607b1", flow_id: FLOW_ID });
  });

  it("Cancelar fecha a confirmação sem mandar nada", async () => {
    const chamadas = await montar();

    fireEvent.click(botao(linha("João"), "Ativar"));
    fireEvent.click(botao(linha("João"), "Cancelar"));

    expect(within(linha("João")).queryByRole("group")).toBeNull();
    expect(chamadas.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("trava os botões enquanto o POST está em voo", async () => {
    let resolver!: (r: Response) => void;
    const pendente = new Promise<Response>((res) => {
      resolver = res;
    });
    instalarFetch([corpo([CANAL_JOAO, CANAL_SOZINHO], true)], () => pendente);
    render(<ValeriaFlowChannels flowId={FLOW_ID} />);
    await waitFor(() => expect(screen.getByText("João")).toBeTruthy());

    fireEvent.click(botao(linha("João"), "Ativar"));
    fireEvent.click(botao(linha("João"), "Confirmar ativação"));

    // O botão em voo mostra o progresso e não aceita um segundo clique.
    await waitFor(() => expect(botao(linha("João"), "Ativando…").disabled).toBe(true));
    expect(botao(linha("João"), "Cancelar").disabled).toBe(true);
    // E nenhum OUTRO canal pode ser ativado ao mesmo tempo: repontar dois números a
    // partir de uma lista meio atualizada é o caminho para apontar o errado.
    expect(botao(linha("Suporte"), "Ativar").disabled).toBe(true);

    resolver(resposta({ channel_id: CANAL_JOAO.id, ligado: true }));
    await waitFor(() => expect(within(linha("João")).queryByText("Ativando…")).toBeNull());
  });

  it("relê a lista depois do sucesso, em vez de deduzir o novo estado", async () => {
    const depois: CanalDoFluxo = {
      ...CANAL_JOAO,
      perfil: { id: "perfil-botoes", name: "Valéria Botões · João", kind: "button_flow", flow_id: FLOW_ID },
      agent_profile_id: "perfil-botoes",
      perfil_compartilhado: false,
      compartilhado_com: [],
      atende_este_fluxo: true,
    };
    const chamadas = instalarFetch(
      [corpo([CANAL_JOAO], true), corpo([depois], true)],
      () => Promise.resolve(resposta({ channel_id: CANAL_JOAO.id, ligado: true })),
    );
    render(<ValeriaFlowChannels flowId={FLOW_ID} />);
    await waitFor(() => expect(screen.getByText("João")).toBeTruthy());
    expect(chamadas.filter((c) => c.method === "GET")).toHaveLength(1);

    fireEvent.click(botao(linha("João"), "Ativar"));
    fireEvent.click(botao(linha("João"), "Confirmar ativação"));

    await waitFor(() => expect(chamadas.filter((c) => c.method === "GET")).toHaveLength(2));
    // O estado novo veio do servidor: o aviso de perfil compartilhado saiu e o canal
    // aparece como atendido por este fluxo.
    await waitFor(() => expect(screen.getByText("Atende por este fluxo")).toBeTruthy());
    expect(screen.queryByText(/Perfil compartilhado/)).toBeNull();
    expect(within(linha("João")).queryByRole("button", { name: "Ativar" })).toBeNull();
  });

  it("leva o foco para Cancelar ao abrir a confirmação — nunca para o botão destrutivo", async () => {
    await montar();
    const alvo = linha("João");

    fireEvent.click(botao(alvo, "Ativar"));
    // O "Ativar" que tinha o foco foi desmontado. Sem reconduzir, o foco cai no
    // `<body>` e o Tab-trap da casca joga quem usa teclado para o topo do modal.
    expect(document.activeElement).toBe(botao(alvo, "Cancelar"));
    expect(document.activeElement).not.toBe(botao(alvo, "Confirmar ativação"));

    fireEvent.click(botao(alvo, "Cancelar"));
    expect(document.activeElement).toBe(botao(alvo, "Ativar"));
  });

  it("avisa que `modo human` não protege o número (o gate do fluxo roda antes dele)", async () => {
    await montar();

    fireEvent.click(botao(linha("João"), "Ativar"));
    // João é `mode: "human"` — e o gate dos fluxos de botões roda ANTES do bloqueio
    // de canal humano em `buffer/processor.py`, de propósito.
    expect(within(linha("João")).getByText(/NÃO/).textContent).toContain(
      "impede o roteiro de responder",
    );

    // A ValerIA é `mode: "ai"`: o aviso seria ruído ali.
    fireEvent.click(botao(linha("ValerIA"), "Ativar"));
    expect(within(linha("ValerIA")).queryByText(/impede o roteiro de responder/)).toBeNull();
  });

  it("não oferece Ativar num canal que já atende por este fluxo", async () => {
    await montar(true, [{ ...CANAL_SOZINHO, atende_este_fluxo: true }]);
    expect(screen.queryByRole("button", { name: "Ativar" })).toBeNull();
    expect(screen.getByText("Atende por este fluxo")).toBeTruthy();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
describe("ValeriaFlowChannels — a mensagem do backend, verbatim", () => {
  const MSG_MIGRATION =
    "a migration 20260929_valeria_botoes.sql ainda não foi aplicada neste banco — " +
    "aplique-a no Supabase antes de editar ou ativar";

  it("mostra o 503 da migration pendente exatamente como o backend escreveu", async () => {
    instalarFetch([corpo([CANAL_SOZINHO], true)], () =>
      Promise.resolve(resposta({ detail: MSG_MIGRATION }, false, 503)),
    );
    render(<ValeriaFlowChannels flowId={FLOW_ID} />);
    await waitFor(() => expect(screen.getByText("Suporte")).toBeTruthy());

    fireEvent.click(botao(linha("Suporte"), "Ativar"));
    fireEvent.click(botao(linha("Suporte"), "Confirmar ativação"));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(MSG_MIGRATION));
  });

  it("mostra o 400 do backend (não um 'Erro ao ativar' genérico)", async () => {
    const msg = "informe o canal que vai atender pelo fluxo de botões";
    instalarFetch([corpo([CANAL_SOZINHO], true)], () =>
      Promise.resolve(resposta({ detail: msg }, false, 400)),
    );
    render(<ValeriaFlowChannels flowId={FLOW_ID} />);
    await waitFor(() => expect(screen.getByText("Suporte")).toBeTruthy());

    fireEvent.click(botao(linha("Suporte"), "Ativar"));
    fireEvent.click(botao(linha("Suporte"), "Confirmar ativação"));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(msg));
  });

  it("mostra o `error` do proxy do Next quando é ELE que falha (401/502)", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(resposta({ error: "Não autenticado" }, false, 401)),
    ) as unknown as typeof fetch;
    render(<ValeriaFlowChannels flowId={FLOW_ID} />);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Não autenticado"));
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
describe("nomesIrmaos / listarNomes", () => {
  it("descarta nulos e vazios de `compartilhado_com`", () => {
    expect(
      nomesIrmaos({ ...CANAL_SOZINHO, compartilhado_com: ["João", null, "  ", "ValerIA"] }),
    ).toEqual(["João", "ValerIA"]);
  });

  it("lista em português: 'A', 'A e B', 'A, B e C'", () => {
    expect(listarNomes([])).toBe("");
    expect(listarNomes(["A"])).toBe("A");
    expect(listarNomes(["A", "B"])).toBe("A e B");
    expect(listarNomes(["A", "B", "C"])).toBe("A, B e C");
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
describe("ValeriaFlowChannels — versão do fluxo", () => {
  const V2 = "valeria_botoes_v2";
  const NA_V1: CanalDoFluxo = {
    ...CANAL_SOZINHO,
    id: "c-v1",
    name: "Comercial",
    perfil: { id: "pb1", name: "Botões v1", kind: "button_flow", flow_id: FLOW_ID },
    atende_este_fluxo: true,
  };
  const NA_V2: CanalDoFluxo = {
    ...CANAL_SOZINHO,
    id: "c-v2",
    name: "Vitrine",
    perfil: { id: "pb2", name: "Botões v2", kind: "button_flow", flow_id: V2 },
    atende_este_fluxo: false,
  };

  it("mostra a versão de cada canal de botões como selo v1/v2, e nenhum no canal com IA", async () => {
    await montar(true, [NA_V1, NA_V2, CANAL_SOZINHO]);
    expect(within(linha("Comercial")).getByTitle("Versão do fluxo de botões deste canal").textContent).toBe("v1");
    expect(within(linha("Vitrine")).getByTitle("Versão do fluxo de botões deste canal").textContent).toBe("v2");
    expect(within(linha("Suporte")).queryByTitle("Versão do fluxo de botões deste canal")).toBeNull();
  });

  it("na v2, busca os canais com `?flow_id=` e ativa mandando o `flow_id` da v2", async () => {
    const chamadas = instalarFetch([{ flow_id: V2, ligado: true, canais: [{ ...NA_V1, atende_este_fluxo: false }, { ...NA_V2, atende_este_fluxo: true }] }]);
    render(<ValeriaFlowChannels flowId={V2} />);
    await waitFor(() => expect(screen.getByText("Comercial")).toBeTruthy());
    expect(chamadas[0].url).toBe("/api/valeria-flow/channels?flow_id=valeria_botoes_v2");

    fireEvent.click(botao(linha("Comercial"), "Ativar"));
    fireEvent.click(botao(linha("Comercial"), "Confirmar ativação"));
    await waitFor(() => expect(chamadas.filter((c) => c.method === "POST")).toHaveLength(1));
    expect(chamadas.find((c) => c.method === "POST")?.body).toEqual({ channel_id: "c-v1", flow_id: V2 });
  });

  it("se o backend responder pela v1, decide 'atende este fluxo' pelo flow_id do perfil", async () => {
    // Backend antigo: ignora `?flow_id=` e calcula `atende_este_fluxo` contra a v1.
    instalarFetch([corpo([NA_V1, NA_V2], true)]);
    render(<ValeriaFlowChannels flowId={V2} />);
    await waitFor(() => expect(screen.getByText("Comercial")).toBeTruthy());

    expect(within(linha("Vitrine")).getByText("Atende por este fluxo")).toBeTruthy();
    expect(within(linha("Comercial")).queryByText("Atende por este fluxo")).toBeNull();
    expect(botao(linha("Comercial"), "Ativar")).toBeTruthy();
  });
});
