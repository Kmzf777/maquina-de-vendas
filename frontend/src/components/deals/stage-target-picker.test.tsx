/**
 * @vitest-environment jsdom
 *
 * Trava a regressão corrigida no commit 02a6b54d: as etapas remotas viviam em estado
 * sem registrar de qual funil vieram, então trocar de um funil remoto A para um funil
 * remoto B deixava as etapas de A no estado enquanto B ainda carregava — e o efeito de
 * auto-seleção disparava com esse dado velho, mandando `onChange(B, <etapa de A>)`. O
 * PATCH de `/api/deals/[id]` não confere se a etapa pertence ao funil, então o card
 * sumia do board de destino. O fix guarda `{ pipelineId, stages }` juntos e só deriva
 * `remoteStages` quando `remote.pipelineId === pipelineId`.
 */
import { useState } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { StageTargetPicker } from "./stage-target-picker";
import type { Pipeline, PipelineStage } from "@/lib/types";

// ── Factories ──────────────────────────────────────────────────────────────────

function makePipeline(over: { id: string; name: string }): Pipeline {
  return {
    id: over.id,
    name: over.name,
    order_index: 0,
    owner_user_id: null,
    is_universal: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function makeStage(over: {
  id: string;
  pipeline_id: string;
  label: string;
  is_protected?: boolean;
}): PipelineStage {
  return {
    id: over.id,
    pipeline_id: over.pipeline_id,
    label: over.label,
    key: null,
    dot_color: "#000000",
    order_index: 0,
    is_protected: over.is_protected ?? false,
    created_at: "2026-01-01T00:00:00Z",
  };
}

// `Response` mínimo — só o que o componente usa (`.json()`).
const resposta = (corpo: unknown) => ({ ok: true, json: async () => corpo }) as Response;

// ── Fixtures ───────────────────────────────────────────────────────────────────

const PIPE_L = makePipeline({ id: "L", name: "Funil Local" });
const PIPE_A = makePipeline({ id: "A", name: "Funil Remoto A" });
const PIPE_B = makePipeline({ id: "B", name: "Funil Remoto B" });
const PIPE_C = makePipeline({ id: "C", name: "Funil com Falha" });

const LOCAL_STAGES = [
  makeStage({ id: "l1", pipeline_id: "L", label: "Novo" }),
  makeStage({ id: "l2", pipeline_id: "L", label: "Em contato" }),
];

const PROTECTED_STAGE = makeStage({
  id: "l3",
  pipeline_id: "L",
  label: "Fechado Ganho",
  is_protected: true,
});

const STAGES_A = [
  makeStage({ id: "a1", pipeline_id: "A", label: "Etapa A1" }),
  makeStage({ id: "a2", pipeline_id: "A", label: "Etapa A2" }),
];

const STAGES_B = [
  makeStage({ id: "b1", pipeline_id: "B", label: "Etapa B1" }),
  makeStage({ id: "b2", pipeline_id: "B", label: "Etapa B2" }),
];

// ── Harness ────────────────────────────────────────────────────────────────────

// O componente é controlado; o harness se comporta como o pai de verdade (a página do
// deal): guarda pipelineId/stageId e devolve pro componente a cada onChange, além de
// registrar toda chamada num spy para a sequência ser inspecionável.
function Harness({
  pipelines,
  initialPipelineId,
  localPipelineId,
  localStages,
  currentStageId,
  autoSelectFirstStage,
  onChangeSpy,
}: {
  pipelines: Pipeline[];
  initialPipelineId: string;
  localPipelineId: string | null;
  localStages: PipelineStage[];
  currentStageId: string | null;
  autoSelectFirstStage: boolean;
  onChangeSpy: (pipelineId: string, stageId: string) => void;
}) {
  const [pipelineId, setPipelineId] = useState(initialPipelineId);
  const [stageId, setStageId] = useState("");
  return (
    <StageTargetPicker
      pipelines={pipelines}
      pipelineId={pipelineId}
      stageId={stageId}
      localPipelineId={localPipelineId}
      localStages={localStages}
      currentStageId={currentStageId}
      autoSelectFirstStage={autoSelectFirstStage}
      onChange={(p, s) => {
        onChangeSpy(p, s);
        setPipelineId(p);
        setStageId(s);
      }}
    />
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("StageTargetPicker", () => {
  // ── Caso 1 — a regressão ────────────────────────────────────────────────────
  it("não deixa a etapa do funil remoto anterior escapar para o novo pipeline_id", async () => {
    const onChangeSpy = vi.fn();

    // O fetch de B fica pendente até `resolveB` ser chamado — é a janela exata em que
    // o bug vivia: `remote` continua sendo o de A enquanto B ainda não respondeu.
    let resolveB!: (r: Response) => void;
    const bPromise = new Promise<Response>((resolve) => {
      resolveB = resolve;
    });

    global.fetch = vi.fn((url: string) => {
      const u = String(url);
      if (u.includes("/api/pipelines/A/stages")) return Promise.resolve(resposta(STAGES_A));
      if (u.includes("/api/pipelines/B/stages")) return bPromise;
      return Promise.resolve(resposta([]));
    }) as unknown as typeof fetch;

    const { container } = render(
      <Harness
        pipelines={[PIPE_L, PIPE_A, PIPE_B]}
        initialPipelineId="L"
        localPipelineId="L"
        localStages={LOCAL_STAGES}
        currentStageId={null}
        autoSelectFirstStage
        onChangeSpy={onChangeSpy}
      />
    );
    const funilSelect = () => container.querySelectorAll("select")[0];

    // L → A: o fetch de A resolve e o auto-select preenche com a primeira etapa de A.
    fireEvent.change(funilSelect(), { target: { value: "A" } });
    await waitFor(() => expect(onChangeSpy).toHaveBeenCalledWith("A", "a1"));

    // A → B: troca enquanto o fetch de B ainda está pendente.
    fireEvent.change(funilSelect(), { target: { value: "B" } });

    await waitFor(() => {
      expect(onChangeSpy.mock.calls.some((c) => c[0] === "B")).toBe(true);
    });

    const chamadasParaB = onChangeSpy.mock.calls.filter((c) => c[0] === "B");
    // Nenhuma chamada para B pode levar consigo uma etapa que pertence a A — é
    // exatamente o par que ia pro PATCH e fazia o card sumir do board de destino.
    expect(chamadasParaB.some((c) => c[1] === "a1" || c[1] === "a2")).toBe(false);
    expect(chamadasParaB).toEqual([["B", ""]]);

    // Resolve o fetch de B: agora sim o auto-select tem dado de verdade para usar.
    resolveB(resposta(STAGES_B));
    await waitFor(() => expect(onChangeSpy).toHaveBeenCalledWith("B", "b1"));
  });

  // ── Caso 2 — autoSelectFirstStage=false ────────────────────────────────────
  it("com autoSelectFirstStage=false nunca preenche a etapa sozinho", async () => {
    const onChangeSpy = vi.fn();

    global.fetch = vi.fn((url: string) => {
      const u = String(url);
      if (u.includes("/api/pipelines/A/stages")) return Promise.resolve(resposta(STAGES_A));
      if (u.includes("/api/pipelines/B/stages")) return Promise.resolve(resposta(STAGES_B));
      return Promise.resolve(resposta([]));
    }) as unknown as typeof fetch;

    const { container } = render(
      <Harness
        pipelines={[PIPE_L, PIPE_A, PIPE_B]}
        initialPipelineId="L"
        localPipelineId="L"
        localStages={LOCAL_STAGES}
        currentStageId={null}
        autoSelectFirstStage={false}
        onChangeSpy={onChangeSpy}
      />
    );
    const selects = () => container.querySelectorAll("select");

    fireEvent.change(selects()[0], { target: { value: "A" } });
    await waitFor(() => expect((selects()[1] as HTMLSelectElement).disabled).toBe(false));

    fireEvent.change(selects()[0], { target: { value: "B" } });
    await waitFor(() => expect((selects()[1] as HTMLSelectElement).disabled).toBe(false));

    expect(onChangeSpy.mock.calls.some((c) => c[1] !== "")).toBe(false);

    // Só o usuário escolhendo explicitamente no select de Etapa deve produzir uma
    // etapa não vazia.
    fireEvent.change(selects()[1], { target: { value: "b1" } });
    expect(onChangeSpy).toHaveBeenCalledWith("B", "b1");
  });

  // ── Caso 3 — etapas protegidas ──────────────────────────────────────────────
  it("esconde etapa protegida da lista de Etapa quando ela não é a etapa atual", () => {
    const { container } = render(
      <Harness
        pipelines={[PIPE_L]}
        initialPipelineId="L"
        localPipelineId="L"
        localStages={[...LOCAL_STAGES, PROTECTED_STAGE]}
        currentStageId={null}
        autoSelectFirstStage={false}
        onChangeSpy={vi.fn()}
      />
    );
    const opcoes = Array.from(container.querySelectorAll("select")[1].querySelectorAll("option")).map(
      (o) => o.textContent
    );
    expect(opcoes).not.toContain("Fechado Ganho");
  });

  it("mantém a etapa protegida na lista quando ela é a etapa atual do deal", () => {
    const { container } = render(
      <Harness
        pipelines={[PIPE_L]}
        initialPipelineId="L"
        localPipelineId="L"
        localStages={[...LOCAL_STAGES, PROTECTED_STAGE]}
        currentStageId="l3"
        autoSelectFirstStage={false}
        onChangeSpy={vi.fn()}
      />
    );
    const opcoes = Array.from(container.querySelectorAll("select")[1].querySelectorAll("option")).map(
      (o) => o.textContent
    );
    expect(opcoes).toContain("Fechado Ganho");
  });

  // ── Caso 4 — falha no fetch não trava o select ──────────────────────────────
  it("corpo de erro não-array (500 real) não deixa o select travado em 'Carregando...'", async () => {
    global.fetch = vi.fn((url: string) => {
      const u = String(url);
      // A rota devolve `{error}` (não um array) em erro 500 — é o que
      // `Array.isArray(data) ? data : []` existe para tratar.
      if (u.includes("/api/pipelines/C/stages")) return Promise.resolve(resposta({ error: "boom" }));
      return Promise.resolve(resposta([]));
    }) as unknown as typeof fetch;

    const { container } = render(
      <Harness
        pipelines={[PIPE_L, PIPE_C]}
        initialPipelineId="L"
        localPipelineId="L"
        localStages={LOCAL_STAGES}
        currentStageId={null}
        autoSelectFirstStage
        onChangeSpy={vi.fn()}
      />
    );
    const selects = () => container.querySelectorAll("select");
    fireEvent.change(selects()[0], { target: { value: "C" } });

    await waitFor(() => expect((selects()[1] as HTMLSelectElement).disabled).toBe(false));
    expect(selects()[1].querySelector("option")?.textContent).toBe("Selecionar etapa...");
  });

  it("fetch rejeitado (erro de rede) também não deixa o select travado", async () => {
    global.fetch = vi.fn((url: string) => {
      const u = String(url);
      if (u.includes("/api/pipelines/C/stages")) return Promise.reject(new Error("network down"));
      return Promise.resolve(resposta([]));
    }) as unknown as typeof fetch;

    const { container } = render(
      <Harness
        pipelines={[PIPE_L, PIPE_C]}
        initialPipelineId="L"
        localPipelineId="L"
        localStages={LOCAL_STAGES}
        currentStageId={null}
        autoSelectFirstStage
        onChangeSpy={vi.fn()}
      />
    );
    const selects = () => container.querySelectorAll("select");
    fireEvent.change(selects()[0], { target: { value: "C" } });

    await waitFor(() => expect((selects()[1] as HTMLSelectElement).disabled).toBe(false));
    expect(selects()[1].querySelector("option")?.textContent).toBe("Selecionar etapa...");
  });
});
