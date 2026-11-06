/**
 * @vitest-environment jsdom
 *
 * F4: o modal exige o motivo (e o concorrente em "comprou_outro"), e o StageTargetPicker
 * com `askLostReason` só aplica uma etapa de perda depois do modal confirmado.
 */
import { useState } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, fireEvent, screen } from "@testing-library/react";
import { LostReasonModal } from "./lost-reason-modal";
import { StageTargetPicker } from "./stage-target-picker";
import type { Pipeline, PipelineStage } from "@/lib/types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const PIPE: Pipeline = {
  id: "L", name: "Atacado", order_index: 0, owner_user_id: null, is_universal: false,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

function stage(id: string, label: string, key: string | null = null): PipelineStage {
  return {
    id, pipeline_id: "L", label, key, dot_color: "#000", order_index: 0,
    is_protected: false, created_at: "2026-01-01T00:00:00Z",
  };
}

const STAGES = [stage("s1", "Novo"), stage("s2", "Em contato"), stage("sp", "Perdido", "perdido")];

// O picker usa <label> sem htmlFor: a 2ª <select> da tela é a de etapa.
function etapa() {
  return document.querySelectorAll("select")[1] as HTMLSelectElement;
}

function selectByLabel(label: string) {
  return screen.getByLabelText(label) as HTMLSelectElement;
}

describe("LostReasonModal", () => {
  it("não confirma sem motivo", () => {
    const onConfirm = vi.fn();
    render(<LostReasonModal onConfirm={onConfirm} onCancel={() => {}} />);
    fireEvent.click(screen.getByText("Confirmar"));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toMatch(/motivo/);
  });

  it("comprou_outro pede o concorrente", () => {
    const onConfirm = vi.fn();
    render(<LostReasonModal onConfirm={onConfirm} onCancel={() => {}} />);
    fireEvent.change(selectByLabel("Motivo *"), { target: { value: "comprou_outro" } });
    fireEvent.click(screen.getByText("Confirmar"));
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Comprou de quem? *"), { target: { value: "Orfeu" } });
    fireEvent.click(screen.getByText("Confirmar"));
    expect(onConfirm).toHaveBeenCalledWith({
      lost_reason_code: "comprou_outro", lost_competitor: "Orfeu", lost_reason: null,
    });
  });

  it("motivo + observação", () => {
    const onConfirm = vi.fn();
    render(<LostReasonModal onConfirm={onConfirm} onCancel={() => {}} />);
    fireEvent.change(selectByLabel("Motivo *"), { target: { value: "frete" } });
    fireEvent.change(screen.getByLabelText("Observação"), { target: { value: "frete p/ BA" } });
    fireEvent.click(screen.getByText("Confirmar"));
    expect(onConfirm).toHaveBeenCalledWith({
      lost_reason_code: "frete", lost_competitor: null, lost_reason: "frete p/ BA",
    });
  });
});

function Harness({ ask, spy }: { ask: boolean; spy: (...a: unknown[]) => void }) {
  const [stageId, setStageId] = useState("s1");
  return (
    <StageTargetPicker
      pipelines={[PIPE]}
      pipelineId="L"
      stageId={stageId}
      localPipelineId="L"
      localStages={STAGES}
      currentStageId="s1"
      autoSelectFirstStage
      askLostReason={ask}
      onChange={(p, s, lost) => { spy(p, s, lost); setStageId(s); }}
    />
  );
}

describe("StageTargetPicker + motivo de perda", () => {
  it("etapa de perda abre o modal e só aplica depois de confirmar", () => {
    const spy = vi.fn();
    render(<Harness ask spy={spy} />);
    fireEvent.change(etapa(), { target: { value: "sp" } });
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.change(selectByLabel("Motivo *"), { target: { value: "pedido_minimo" } });
    fireEvent.click(screen.getByText("Confirmar"));
    expect(spy).toHaveBeenCalledWith("L", "sp", {
      lost_reason_code: "pedido_minimo", lost_competitor: null, lost_reason: null,
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cancelar mantém a etapa anterior", () => {
    const spy = vi.fn();
    render(<Harness ask spy={spy} />);
    fireEvent.change(etapa(), { target: { value: "sp" } });
    fireEvent.click(screen.getByText("Cancelar"));
    expect(spy).not.toHaveBeenCalled();
    expect(etapa().value).toBe("s1");
  });

  it("etapa aberta passa direto e zera o motivo", () => {
    const spy = vi.fn();
    render(<Harness ask spy={spy} />);
    fireEvent.change(etapa(), { target: { value: "s2" } });
    expect(spy).toHaveBeenCalledWith("L", "s2", null);
  });

  it("sem askLostReason o comportamento antigo não muda", () => {
    const spy = vi.fn();
    render(<Harness ask={false} spy={spy} />);
    fireEvent.change(etapa(), { target: { value: "sp" } });
    expect(spy).toHaveBeenCalledWith("L", "sp", undefined);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
