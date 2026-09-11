"use client";

import { useState } from "react";
import { reopenPatch, type DealRow } from "@/lib/deal-rows";

interface DealStageRowProps {
  row: DealRow;
  /** Resolve em sucesso; LANÇA Error com mensagem legível em falha. */
  onDealUpdate: (dealId: string, patch: Record<string, unknown>) => Promise<void>;
}

export function DealStageRow({ row, onDealUpdate }: DealStageRowProps) {
  const { deal, isClosed, stageOptions, stageLabel, dotColor, pipelineName, reopenStageId, canEditStage } = row;

  // `pending` é o stage escolhido enquanto o PATCH está no ar. Em sucesso, o pai
  // refaz o fetch e deal.stage_id já vem novo; em falha, limpar `pending` reverte
  // sozinho para a verdade do servidor. Sem estado espelhado para dessincronizar.
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = pending !== null;
  const selectedStageId = pending ?? deal.stage_id ?? "";

  async function apply(patch: Record<string, unknown>, optimisticStageId: string) {
    setPending(optimisticStageId);
    setError(null);
    try {
      await onDealUpdate(deal.id, patch);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao atualizar oportunidade.");
    } finally {
      setPending(null);
    }
  }

  return (
    <div
      className={`flex items-start gap-2 p-2 rounded-[6px] border border-[#dedbd6] bg-white ${isClosed ? "opacity-60" : ""}`}
    >
      <span
        className="w-2 h-2 rounded-full flex-shrink-0 mt-1.5"
        style={
          isClosed
            ? { border: `1.5px solid ${dotColor}`, backgroundColor: "transparent" }
            : { backgroundColor: dotColor }
        }
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-[13px] text-[#111111] truncate">{deal.title}</p>
          {deal.value > 0 && (
            <p className="text-[12px] text-[#111111] flex-shrink-0">
              R$ {deal.value.toLocaleString("pt-BR")}
            </p>
          )}
        </div>
        <p className="text-[11px] text-[#7b7b78] truncate">{pipelineName}</p>

        {canEditStage ? (
          <select
            value={selectedStageId}
            disabled={busy}
            aria-label={`Estágio de ${deal.title}`}
            onChange={(e) => apply({ stage_id: e.target.value }, e.target.value)}
            className="mt-1.5 bg-white border border-[#dedbd6] rounded-[6px] px-2 py-1 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none w-full disabled:opacity-60"
          >
            {stageOptions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        ) : (
          <div className="mt-1 flex items-center justify-between gap-2">
            <span className="text-[12px] text-[#7b7b78] truncate">{stageLabel}</span>
            {isClosed && reopenStageId && (
              <button
                type="button"
                disabled={busy}
                onClick={() => apply(reopenPatch(reopenStageId), reopenStageId)}
                className="text-[12px] text-[#111111] border border-[#dedbd6] rounded-[4px] px-2 py-0.5 hover:border-[#111111] transition-colors flex-shrink-0 disabled:opacity-60"
              >
                {busy ? "..." : "Reabrir"}
              </button>
            )}
          </div>
        )}

        {isClosed && deal.lost_reason && (
          <p className="text-[11px] text-[#7b7b78] mt-1">⤷ motivo: {deal.lost_reason}</p>
        )}

        {/* Erro por linha, nunca global: com N deals de funis diferentes, um 403
            de permissão num funil não pode borrar o painel inteiro. */}
        {error && <p className="text-[11px] text-[#e53e3e] mt-1">{error}</p>}
      </div>
    </div>
  );
}
