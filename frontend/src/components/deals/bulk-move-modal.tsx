"use client";

import { useState } from "react";
import type { Pipeline, PipelineStage } from "@/lib/types";
import { StageTargetPicker } from "@/components/deals/stage-target-picker";

interface BulkMoveModalProps {
  count: number;
  pipelines: Pipeline[];
  currentPipelineId: string;
  currentStages: PipelineStage[];
  /** Progresso do lote em andamento; null quando parado. */
  progress: { done: number; total: number } | null;
  onClose: () => void;
  onMove: (pipelineId: string, stageId: string) => Promise<void>;
}

export function BulkMoveModal({
  count,
  pipelines,
  currentPipelineId,
  currentStages,
  progress,
  onClose,
  onMove,
}: BulkMoveModalProps) {
  const [targetPipelineId, setTargetPipelineId] = useState(currentPipelineId);
  const [targetStageId, setTargetStageId] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  const moving = progress !== null;
  // Trava dupla de proposito: a etapa nao vem pre-selecionada e o checkbox exige
  // um ato explicito. Mover em massa nao tem desfazer e dispara automacao por deal.
  const canMove = Boolean(targetStageId) && confirmed && !moving;

  async function handleMove() {
    if (!canMove) return;
    await onMove(targetPipelineId, targetStageId);
  }

  return (
    <div
      className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4"
      onClick={() => { if (!moving) onClose(); }}
    >
      <div
        className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-[460px] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-[#dedbd6] flex items-center justify-between">
          <div>
            <h3 className="text-[16px] font-normal text-[#111111]" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>
              Mover deals
            </h3>
            <p className="text-[12px] text-[#7b7b78] mt-0.5">
              {count} deal{count !== 1 ? "s" : ""} selecionado{count !== 1 ? "s" : ""}
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={moving}
            className="text-[#7b7b78] hover:text-[#111111] transition-colors disabled:opacity-40"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="3" x2="13" y2="13" />
              <line x1="13" y1="3" x2="3" y2="13" />
            </svg>
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          <StageTargetPicker
            pipelines={pipelines}
            pipelineId={targetPipelineId}
            stageId={targetStageId}
            localPipelineId={currentPipelineId}
            localStages={currentStages}
            currentStageId={null}
            autoSelectFirstStage={false}
            disabled={moving}
            onChange={(pipelineId, stageId) => {
              setTargetPipelineId(pipelineId);
              setTargetStageId(stageId);
            }}
          />

          {/* Trio de aviso ja estabelecido no projeto (esteiras-tab, templates-tab). */}
          <div className="bg-[#fff8e0] border border-[#eadfb4] rounded-[6px] px-3 py-2.5">
            <p className="text-[12px] text-[#7a5a00] leading-[1.5]">
              Esta ação move {count} deal{count !== 1 ? "s" : ""} e não pode ser desfeita.
              As automações da etapa de destino serão disparadas para cada lead.
            </p>
          </div>

          <label className="flex items-center gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={moving}
              onChange={(e) => setConfirmed(e.target.checked)}
              className="w-4 h-4 accent-[#111111] cursor-pointer"
            />
            <span className="text-[13px] text-[#111111]">Confirmo que quero mover estes deals</span>
          </label>
        </div>

        <div className="px-6 py-4 border-t border-[#dedbd6] bg-[#faf9f6] flex gap-2 justify-end rounded-b-[8px]">
          <button
            onClick={onClose}
            disabled={moving}
            className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors disabled:opacity-40"
          >
            Cancelar
          </button>
          <button
            onClick={handleMove}
            disabled={!canMove}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[13px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
          >
            {progress
              ? `Movendo ${progress.done}/${progress.total}...`
              : `Mover ${count} deal${count !== 1 ? "s" : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}
