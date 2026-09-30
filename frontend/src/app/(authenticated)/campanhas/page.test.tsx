/**
 * @vitest-environment jsdom
 *
 * A FIAÇÃO do botão "ValerIA de Botões" em `/campanhas`.
 *
 * Por que este arquivo existe: o modal, o editor e o painel de canais já eram
 * testados cada um por conta própria e todos verdes — enquanto a página não tinha
 * UMA linha que os abrisse. Feature completa e inalcançável passa por toda suíte de
 * componente que existir; só um teste da PÁGINA pega isso.
 *
 * O que ele trava, e o modo de falha de cada asserção:
 *
 *   • O botão existe no cabeçalho, ao lado do "Valeria Score". Sem ele não há
 *     caminho até o modal em produção.
 *   • O rótulo é o do modal ("ValerIA de Botões"), e não um segundo nome para a
 *     mesma coisa — dois nomes para uma tela é o que faz um operador procurar no
 *     lugar errado.
 *   • O modal nasce FECHADO. Um `useState(true)` por engano abriria a tela em cima
 *     de quem só quis ver campanhas — e dispararia o `GET /api/valeria-flow` em toda
 *     visita.
 *   • Clicar abre o modal DE VERDADE (o próprio `ValeriaFlowModal`, não um dublê), e
 *     o × devolve a página. É o par `open`/`onClose` que a página precisa acertar.
 *
 * Os dublês abaixo: só o que a página importa e não é o objeto deste teste. Os hooks
 * de realtime instanciam o cliente do Supabase no corpo (`createClient()`), que pede
 * `NEXT_PUBLIC_SUPABASE_URL` e sobe um Web Worker de heartbeat — nada disso existe em
 * jsdom. `ValeriaFlowModal` NÃO é dublado de propósito: é ele que está sendo fiado.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/hooks/use-realtime-broadcasts", () => ({
  useRealtimeBroadcasts: () => ({ broadcasts: [], loading: false }),
}));
vi.mock("@/hooks/use-realtime-campaigns", () => ({
  useRealtimeCampaigns: () => ({ campaigns: [], loading: false }),
}));

vi.mock("@/components/campaigns/campaigns-dashboard", () => ({
  CampaignsDashboard: () => null,
}));
vi.mock("@/components/campaigns/broadcast-list", () => ({ BroadcastList: () => null }));
vi.mock("@/components/campaigns/cadence-list", () => ({ CadenceList: () => null }));
vi.mock("@/components/campaigns/cadence-enrollments-table", () => ({
  CampaignEnrollmentsTable: () => null,
}));
vi.mock("@/components/campaigns/create-broadcast-modal", () => ({
  CreateBroadcastModal: () => null,
}));
vi.mock("@/components/campaigns/quick-send-modal", () => ({ QuickSendModal: () => null }));
vi.mock("@/components/campaigns/templates-tab", () => ({ TemplatesTab: () => null }));
vi.mock("@/components/campaigns/followup-board", () => ({ FollowupBoard: () => null }));
vi.mock("@/components/campaigns/valeria-score-modal", () => ({ ValeriaScoreModal: () => null }));

import CampanhasPage from "./page";

/** O fluxo mais magro que o modal aceita: uma tela, um desfecho, os dois reservados. */
const FLUXO = {
  flow_id: "valeria_botoes_v1",
  no_entrada: "N0",
  limites: { rotulo_botao: 20, titulo_lista: 24, desc_lista: 72, max_botoes: 3, max_linhas_lista: 10 },
  editaveis: { no: ["corpo", "rotulos"], terminal: ["corpo"] },
  nos: [
    {
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
    },
  ],
  terminais: [],
  nudge: {
    chave: "__nudge__",
    id: "__nudge__",
    tipo: "reservado",
    rotulo_interno: "Reoferecimento (nudge)",
    corpo: "Ainda por aqui?",
    corpo_default: "Ainda por aqui?",
    editaveis: ["corpo"],
    editado: false,
    teto: 3,
  },
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
  prazos: [],
};

/** A página busca visibilidade do espelho e canais no mount; o modal busca o fluxo. */
function rotear() {
  global.fetch = vi.fn(async (entrada: RequestInfo | URL) => {
    const url = String(entrada);
    const corpo =
      url === "/api/valeria-flow" ? FLUXO
        : url === "/api/cadence/mirror-visibility" ? { visible: false }
        : url === "/api/channels" ? []
        : {};
    return { ok: true, status: 200, statusText: "OK", json: async () => corpo } as Response;
  }) as typeof global.fetch;
}

const botao = () => screen.getByRole("button", { name: "ValerIA de Botões" });

beforeEach(() => {
  rotear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("/campanhas — o botão que abre a ValerIA de Botões", () => {
  it("põe o botão no cabeçalho, ao lado do 'Valeria Score'", async () => {
    render(<CampanhasPage />);

    const alvo = await waitFor(() => botao());
    expect(screen.getByRole("button", { name: "Valeria Score" })).toBeTruthy();
    // Irmãos no mesmo grupo de ações do cabeçalho.
    expect(alvo.parentElement).toBe(screen.getByRole("button", { name: "Valeria Score" }).parentElement);
    // E o `title` diz o que a tela edita — o rótulo é o nome da feature.
    expect(alvo.getAttribute("title")).toContain("rótulo de cada botão");
  });

  it("nasce fechado: nenhum modal na tela e nenhum GET do fluxo antes do clique", async () => {
    render(<CampanhasPage />);
    await waitFor(() => botao());

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(global.fetch).not.toHaveBeenCalledWith("/api/valeria-flow", expect.anything());
  });

  it("abre o modal de verdade no clique e o fecha no ×", async () => {
    render(<CampanhasPage />);
    await waitFor(() => botao());

    fireEvent.click(botao());

    // O diálogo é o `ValeriaFlowModal` real: título, e o `GET` que ele faz ao abrir.
    const dialogo = await waitFor(() => screen.getByRole("dialog"));
    expect(dialogo.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByRole("heading", { name: "ValerIA de Botões" })).toBeTruthy();
    expect(global.fetch).toHaveBeenCalledWith("/api/valeria-flow", expect.objectContaining({ cache: "no-store" }));
    // E o painel da aba "Fluxo" chegou até a tela, com os dados do servidor.
    await waitFor(() => expect(screen.getByRole("navigation", { name: "Ramos do fluxo" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Fechar ValerIA de Botões" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // A página continua lá, com o botão pronto para reabrir.
    expect(botao()).toBeTruthy();
  });
});
