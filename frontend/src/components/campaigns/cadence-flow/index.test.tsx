/**
 * @vitest-environment jsdom
 *
 * Não há precedente de teste do builder (canvas React Flow) neste repositório — segue
 * a mesma convenção de `esteiras-tab.test.tsx` (fetch mockado com `global.fetch =
 * vi.fn()`, comentários em português explicando o porquê), com um ingrediente extra:
 * `@xyflow/react` some depende de APIs de browser que o jsdom não implementa
 * (ResizeObserver, matchMedia, o motor de pan/zoom do canvas), então o pacote é
 * mockado. O mock NÃO reimplementa o React Flow — ele usa o `nodeTypes.campaignNode`
 * de verdade (`CampaignFlowNode`, em `graph-elements.tsx`, arquivo não tocado por
 * esta task), então o destaque testado aqui (badge/anel de `testState`) é o código de
 * produção real, não uma simulação.
 *
 * Contrato exercitado: POST /api/campaigns/{id}/activate, proxy puro para
 * `backend/app/campaigns/router.py`, que valida 12 regras e recusa com 400 +
 * `{detail: {problemas: [{no_id, codigo, mensagem}]}}`.
 *
 * O bug fechado aqui: `toggleActivation` fazia só `if (data.error) alert(data.error)`
 * — nem olhava `res.ok`. Num 400 com `detail.problemas`, `data.error` é `undefined`:
 * nenhum alert, e pior, `setCampaign(prev => ({...prev, status: data.status}))` ainda
 * rodava com `data.status` undefined. A tela não dizia nada e o status podia corromper.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent, within } from "@testing-library/react";
import type { ReactNode } from "react";
import type { Campaign, CampaignNode, CampaignNodeType } from "@/lib/types";

// ─── jsdom não implementa matchMedia/ResizeObserver — framer-motion (usado pelo nó
// do canvas, CampaignFlowNode) e afins podem checar por eles. Stub mínimo, só pra não
// derrubar o render; nenhum teste aqui depende do comportamento real deles. ──────────
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
if (!(globalThis as unknown as { ResizeObserver?: unknown }).ResizeObserver) {
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// ─── Mock de @xyflow/react — só a casca (canvas/pan/zoom) que exige browser real.
// `ReactFlow` aqui renderiza cada nó com `nodeTypes.campaignNode` de verdade, então
// `data.testState` chega no MESMO componente que roda em produção. ──────────────────
vi.mock("@xyflow/react", async () => {
  const { useState } = await import("react");

  const Position = { Top: "top", Bottom: "bottom", Left: "left", Right: "right" };
  const MarkerType = { ArrowClosed: "arrowclosed" };
  const BackgroundVariant = { Dots: "dots" };
  const PanOnScrollMode = { Free: "free" };
  const ConnectionLineType = { SmoothStep: "smoothstep" };

  function ReactFlow(props: Record<string, unknown>) {
    const nodes = (props.nodes ?? []) as { id: string; type?: string; data: unknown }[];
    const nodeTypes = (props.nodeTypes ?? {}) as Record<string, (p: { id: string; data: unknown }) => ReactNode>;
    return (
      <div data-testid="mock-react-flow">
        {nodes.map((n) => {
          const NodeComp = nodeTypes[n.type ?? ""];
          return (
            <div key={n.id} data-testid={`node-${n.id}`}>
              {NodeComp ? <NodeComp id={n.id} data={n.data} /> : null}
            </div>
          );
        })}
        {(props.children ?? null) as never}
      </div>
    );
  }

  const PassThrough = (props: { children?: unknown }) => <>{(props.children ?? null) as never}</>;

  function useNodesState(initial: unknown) {
    const [nodes, setNodes] = useState(initial);
    return [nodes, setNodes, () => {}] as const;
  }
  function useEdgesState(initial: unknown) {
    const [edges, setEdges] = useState(initial);
    return [edges, setEdges, () => {}] as const;
  }

  return {
    ReactFlow,
    ReactFlowProvider: PassThrough,
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
    Panel: PassThrough,
    Handle: () => null,
    BaseEdge: () => null,
    EdgeLabelRenderer: PassThrough,
    Position,
    MarkerType,
    BackgroundVariant,
    PanOnScrollMode,
    ConnectionLineType,
    getSmoothStepPath: () => ["", 0, 0],
    addEdge: (_c: unknown, eds: unknown) => eds,
    useReactFlow: () => ({
      screenToFlowPosition: (p: unknown) => p,
      zoomIn: () => {},
      zoomOut: () => {},
      fitView: () => {},
    }),
    useNodesState,
    useEdgesState,
  };
});

// Painel de log de execução puxa Supabase realtime — irrelevante pro que este arquivo
// testa (a recusa de ativação) e cheio de efeito colateral de rede fora do escopo.
vi.mock("@/components/campaigns/cadence-execution-log", () => ({
  CadenceExecutionLog: () => null,
}));

// useRouter() exige o contexto do App Router — ausente fora de `next dev`/`next build`.
// Só o botão "←" usa `router.push`; nenhum teste aqui clica nele.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => {} }),
}));

// Import DEPOIS dos vi.mock (hoisted de qualquer forma, mas assim fica explícito que
// o módulo só carrega com os mocks já registrados).
import { CadenceFlowBuilder, parseActivationErrorMessages, activationProblemNodeIds } from "./index";

// ─── Fixtures ─────────────────────────────────────────────────────────────────────
function no(id: string, type: CampaignNodeType, next: string | null = null): CampaignNode {
  return {
    id,
    campaign_id: "camp-1",
    type,
    config: {},
    position_x: 100,
    position_y: 100,
    next_node_id: next,
    yes_node_id: null,
    no_node_id: null,
    created_at: "2026-09-16T12:00:00Z",
  };
}

const NODES: CampaignNode[] = [
  no("n1", "trigger", "n2"),
  no("n2", "send", "n3"),
  no("n3", "wait", "n4"),
  no("n4", "end", null),
];

const CAMPANHA: Campaign = {
  id: "camp-1",
  name: "Campanha de teste",
  description: null,
  status: "draft",
  channel_id: null,
  env_tag: "prod",
  start_date: null,
  created_at: "2026-09-16T12:00:00Z",
  updated_at: "2026-09-16T12:00:00Z",
  nodes: NODES,
};

type Corpo = Record<string, unknown> | unknown[];
const resposta = (corpo: Corpo, status = 200) =>
  ({ ok: status < 400, status, json: async () => corpo }) as Response;

/** Casa por sufixo/método; sem entrada específica devolve `[]` (templates, pipelines,
 *  tags, users, channels — todas as rotas auxiliares do Inspector, que este arquivo
 *  não exercita). */
function mockarFetch(opts: { ativar?: () => Response } = {}) {
  global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.endsWith("/activate") && init?.method === "POST") {
      return opts.ativar?.() ?? resposta({ status: "active" });
    }
    if (u.endsWith("/pause") && init?.method === "POST") {
      return resposta({ status: "paused" });
    }
    if (/\/api\/campaigns\/[^/]+$/.test(u)) {
      return resposta(CAMPANHA as unknown as Corpo);
    }
    return resposta([]);
  }) as unknown as typeof fetch;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const montarCanvas = async () => {
  render(<CadenceFlowBuilder campaignId="camp-1" />);
  await waitFor(() => expect(screen.getByTestId("node-n1")).toBeTruthy());
};

const clicarAtivar = () => fireEvent.click(screen.getByRole("button", { name: /Ativar campanha/i }));

describe("CadenceFlowBuilder — recusa de ativação aparece na tela", () => {
  it("resposta 400 com detail.problemas[] de 3 itens mostra as TRÊS mensagens", async () => {
    const problemas = [
      { no_id: "n1", codigo: "trigger_incompleto", mensagem: "O gatilho não tem palavra-chave configurada." },
      { no_id: "n2", codigo: "template_nao_aprovado", mensagem: "O toque 3 usa o template promo_v2, ainda em análise na Meta." },
      { no_id: "n4", codigo: "sem_final_actions", mensagem: "O nó de encerramento não define nenhuma ação final." },
    ];
    mockarFetch({ ativar: () => resposta({ detail: { problemas } }, 400) });
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    await montarCanvas();
    clicarAtivar();

    await waitFor(() => expect(alertSpy).toHaveBeenCalledTimes(1));
    const mensagem = String(alertSpy.mock.calls[0][0]);
    for (const p of problemas) expect(mensagem).toContain(p.mensagem);
  });

  it("resposta com {error} string (proxy quando o backend está fora do ar) continua mostrando", async () => {
    mockarFetch({ ativar: () => resposta({ error: "Backend indisponível" }, 502) });
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    await montarCanvas();
    clicarAtivar();

    await waitFor(() => expect(alertSpy).toHaveBeenCalledWith("Backend indisponível"));
  });

  it("200 ativa normalmente — sem alert, status muda pra Ativa", async () => {
    mockarFetch({ ativar: () => resposta({ status: "active" }, 200) });
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    await montarCanvas();
    clicarAtivar();

    await waitFor(() => expect(screen.getByRole("button", { name: /Pausar/i })).toBeTruthy());
    expect(screen.getByText("Ativa")).toBeTruthy();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("corpo inesperado (sem error e sem detail.problemas) não fica em silêncio", async () => {
    mockarFetch({ ativar: () => resposta({ algo_inesperado: true }, 400) });
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    await montarCanvas();
    clicarAtivar();

    await waitFor(() => expect(alertSpy).toHaveBeenCalledTimes(1));
    expect(String(alertSpy.mock.calls[0][0]).trim().length).toBeGreaterThan(0);
    // Sem no_id nenhum na resposta, nenhum nó deveria acender em vermelho.
    for (const n of NODES) {
      expect(within(screen.getByTestId(`node-${n.id}`)).queryByText("✗")).toBeNull();
    }
  });

  it("os no_id da recusa ficam destacados no canvas — e só eles", async () => {
    // n1 e n3 têm problema; n2 e n4 não. Reaproveita testNodeStates (o mesmo mapa que
    // o modo ⚡ Testar usa pra desenhar o anel/badge do nó) — por isso "failed" pinta
    // de vermelho com ✗, sem precisar de um segundo mecanismo visual.
    const problemas = [
      { no_id: "n1", codigo: "trigger_incompleto", mensagem: "O gatilho não tem palavra-chave configurada." },
      { no_id: "n3", codigo: "wait_invalido", mensagem: "A espera não pode ser negativa." },
    ];
    mockarFetch({ ativar: () => resposta({ detail: { problemas } }, 400) });
    vi.spyOn(window, "alert").mockImplementation(() => {});

    await montarCanvas();
    clicarAtivar();

    await waitFor(() =>
      expect(within(screen.getByTestId("node-n1")).queryByText("✗")).not.toBeNull()
    );
    expect(within(screen.getByTestId("node-n3")).queryByText("✗")).not.toBeNull();
    // Os que não vieram na lista não podem acender junto.
    expect(within(screen.getByTestId("node-n2")).queryByText("✗")).toBeNull();
    expect(within(screen.getByTestId("node-n4")).queryByText("✗")).toBeNull();
  });
});

// ── Helpers puros — é aqui que mora a lógica de verdade ──────────────────────────
describe("parseActivationErrorMessages (helper puro)", () => {
  it("detail.problemas[] vira uma mensagem por problema, na ordem", () => {
    const corpo = { detail: { problemas: [{ mensagem: "a" }, { mensagem: "b" }, { mensagem: "c" }] } };
    expect(parseActivationErrorMessages(corpo)).toEqual(["a", "b", "c"]);
  });

  it("{error: string} vira mensagem única", () => {
    expect(parseActivationErrorMessages({ error: "fora do ar" })).toEqual(["fora do ar"]);
  });

  it("corpo sem error e sem detail.problemas nunca devolve [] — sempre uma mensagem genérica", () => {
    expect(parseActivationErrorMessages({})).toHaveLength(1);
    expect(parseActivationErrorMessages(null)).toHaveLength(1);
    expect(parseActivationErrorMessages(undefined)).toHaveLength(1);
  });

  it("detail.problemas presente mas vazio conta como inesperado (não alerta em branco)", () => {
    expect(parseActivationErrorMessages({ detail: { problemas: [] } })).toHaveLength(1);
  });
});

describe("activationProblemNodeIds (helper puro)", () => {
  it("extrai só os no_id presentes, ignorando null/ausentes", () => {
    const corpo = { detail: { problemas: [{ no_id: "n1" }, { no_id: null }, { no_id: "n3" }, {}] } };
    expect(activationProblemNodeIds(corpo)).toEqual(["n1", "n3"]);
  });

  it("sem detail.problemas devolve [] (nada pra destacar)", () => {
    expect(activationProblemNodeIds({ error: "fora do ar" })).toEqual([]);
    expect(activationProblemNodeIds({})).toEqual([]);
  });
});
