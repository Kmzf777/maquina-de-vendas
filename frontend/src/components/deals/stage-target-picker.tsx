"use client";

import { useEffect, useState } from "react";
import type { Pipeline, PipelineStage } from "@/lib/types";
import { selectableStages } from "@/lib/bulk-move-deals";

interface StageTargetPickerProps {
  pipelines: Pipeline[];
  /** Funil escolhido no momento. */
  pipelineId: string;
  /** Etapa escolhida no momento. "" = nenhuma. */
  stageId: string;
  /** Etapas já carregadas do funil aberto no board — evita um fetch redundante. */
  localPipelineId: string | null;
  localStages: PipelineStage[];
  /** Etapa atual do deal; entra na lista mesmo se for protegida. null no modo massa. */
  currentStageId: string | null;
  /** Se true, seleciona a primeira etapa ao trocar de funil. Se false, zera a escolha. */
  autoSelectFirstStage: boolean;
  disabled?: boolean;
  onChange: (pipelineId: string, stageId: string) => void;
}

export function StageTargetPicker({
  pipelines,
  pipelineId,
  stageId,
  localPipelineId,
  localStages,
  currentStageId,
  autoSelectFirstStage,
  disabled = false,
  onChange,
}: StageTargetPickerProps) {
  const [remoteStages, setRemoteStages] = useState<PipelineStage[]>([]);
  const [loading, setLoading] = useState(false);

  const isLocal = pipelineId === localPipelineId;

  useEffect(() => {
    if (!pipelineId || isLocal) { setRemoteStages([]); return; }
    const controller = new AbortController();
    setLoading(true);
    fetch(`/api/pipelines/${pipelineId}/stages`, { signal: controller.signal })
      .then((r) => r.json())
      .then((data: PipelineStage[]) => {
        setRemoteStages(Array.isArray(data) ? data : []);
      })
      .catch((e) => { if (e?.name !== "AbortError") setRemoteStages([]); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [pipelineId, isLocal]);

  const stages = isLocal ? localStages : remoteStages;
  const options = selectableStages(stages, currentStageId);

  function handlePipelineChange(nextPipelineId: string) {
    if (nextPipelineId === localPipelineId) {
      const opts = selectableStages(localStages, currentStageId);
      onChange(nextPipelineId, autoSelectFirstStage ? opts[0]?.id ?? "" : "");
    } else {
      // As etapas do novo funil ainda não chegaram; zera e deixa o efeito abaixo
      // preencher quando o fetch resolver.
      onChange(nextPipelineId, "");
    }
  }

  // Depois que as etapas de um funil remoto chegam, preenche a escolha se pedido.
  useEffect(() => {
    if (!autoSelectFirstStage || isLocal || loading || stageId) return;
    const first = selectableStages(remoteStages, currentStageId)[0]?.id;
    if (first) onChange(pipelineId, first);
    // onChange vem do pai e pode mudar de identidade a cada render; depender dele
    // aqui causaria loop. As dependências abaixo bastam para o preenchimento único.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remoteStages, loading, isLocal, autoSelectFirstStage, stageId, pipelineId, currentStageId]);

  const selectClass =
    "bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full disabled:opacity-50";

  return (
    <div className="space-y-3">
      <div>
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Funil</label>
        <select
          value={pipelineId}
          disabled={disabled}
          onChange={(e) => handlePipelineChange(e.target.value)}
          className={selectClass}
        >
          {pipelines.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>
      <div>
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Etapa</label>
        <select
          value={stageId}
          disabled={disabled || loading}
          onChange={(e) => onChange(pipelineId, e.target.value)}
          className={selectClass}
        >
          {loading && <option value="">Carregando...</option>}
          {!loading && <option value="">Selecionar etapa...</option>}
          {!loading && options.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
      </div>
    </div>
  );
}
