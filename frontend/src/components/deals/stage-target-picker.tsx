"use client";

import { useEffect, useState } from "react";
import type { Pipeline, PipelineStage } from "@/lib/types";
import { selectableStages } from "@/lib/bulk-move-deals";
import { isLostStage, type LostReasonValue } from "@/lib/lost-reason";
import { LostReasonModal } from "@/components/deals/lost-reason-modal";

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
  /**
   * F4: se true, escolher uma etapa de perda (key perdido/fechado_perdido) abre o modal de
   * motivo, e a escolha só vale depois de confirmado — o motivo chega no 3º argumento do
   * onChange. Cancelar o modal mantém a etapa anterior. Qualquer outra escolha manda
   * `null` no 3º argumento (descarta um motivo dado antes). Opt-in porque só quem grava o
   * motivo junto pode pedir: o lote e a criação de lead ainda não gravam.
   */
  askLostReason?: boolean;
  onChange: (pipelineId: string, stageId: string, lost?: LostReasonValue | null) => void;
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
  askLostReason = false,
  onChange,
}: StageTargetPickerProps) {
  // Etapa de perda escolhida, esperando o motivo no modal.
  const [pendingLostStageId, setPendingLostStageId] = useState<string | null>(null);
  // As etapas carregadas viajam junto com o id do funil que as originou. Sem esse
  // par, trocar do funil remoto A para o remoto B deixava as etapas de A no estado
  // enquanto B carregava — e o auto-select gravava uma etapa de A junto com o
  // pipeline_id de B. O PATCH nao confere se a etapa pertence ao funil, entao o
  // par errado ia pro banco e o card sumia do board de destino.
  const [remote, setRemote] = useState<{ pipelineId: string; stages: PipelineStage[] } | null>(null);

  const isLocal = pipelineId === localPipelineId;
  // Só serve se for deste funil; de qualquer outro é sobra de uma troca anterior.
  const remoteStages = remote && remote.pipelineId === pipelineId ? remote.stages : null;
  // Derivado, nao estado: um `loading` proprio dessincroniza do fetch que esta
  // realmente em curso quando o usuario troca de funil no meio do carregamento.
  const loading = Boolean(pipelineId) && !isLocal && remoteStages === null;

  useEffect(() => {
    if (!pipelineId || isLocal) return;
    const controller = new AbortController();
    fetch(`/api/pipelines/${pipelineId}/stages`, { signal: controller.signal })
      .then((r) => r.json())
      .then((data: PipelineStage[]) => {
        setRemote({ pipelineId, stages: Array.isArray(data) ? data : [] });
      })
      .catch((e) => {
        // Erro de rede ou 500 (a rota devolve {error}, nao um array): registra lista
        // vazia PARA ESTE funil, senao o select fica "Carregando..." pra sempre.
        if (e?.name !== "AbortError") setRemote({ pipelineId, stages: [] });
      });
    return () => controller.abort();
  }, [pipelineId, isLocal]);

  const stages = isLocal ? localStages : (remoteStages ?? []);
  const options = selectableStages(stages, currentStageId);

  function handlePipelineChange(nextPipelineId: string) {
    if (nextPipelineId === localPipelineId) {
      const opts = selectableStages(localStages, currentStageId);
      // Voltar para o funil do proprio deal restaura a etapa dele, nao a primeira
      // da lista: senao "mudei de ideia" move o card de coluna sem ninguém pedir —
      // e ainda dispara a automação de deal_stage_enter da etapa nova.
      const restored = currentStageId && opts.some((s) => s.id === currentStageId)
        ? currentStageId
        : "";
      if (restored) {
        onChange(nextPipelineId, restored);
        return;
      }
      onChange(nextPipelineId, autoSelectFirstStage ? opts[0]?.id ?? "" : "");
    } else {
      // As etapas do novo funil ainda não chegaram; zera e deixa o efeito abaixo
      // preencher quando o fetch resolver.
      onChange(nextPipelineId, "");
    }
  }

  // Só dispara quando as etapas ja sao comprovadamente do funil escolhido
  // (`remoteStages !== null`), nunca com sobra do funil anterior.
  useEffect(() => {
    if (!autoSelectFirstStage || isLocal || remoteStages === null || stageId) return;
    const first = selectableStages(remoteStages, currentStageId)[0]?.id;
    if (first) onChange(pipelineId, first);
    // onChange vem do pai como arrow inline e muda de identidade a cada render;
    // inclui-lo nas deps redispararia o efeito a toa. O guarda real contra loop e
    // o `stageId` truthy, que ja esta nas deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remoteStages, isLocal, autoSelectFirstStage, stageId, pipelineId, currentStageId]);

  function handleStageChange(nextStageId: string) {
    const stage = options.find((s) => s.id === nextStageId);
    // A etapa ATUAL do deal não pede motivo de novo: o card já está perdido.
    if (askLostReason && isLostStage(stage) && nextStageId !== currentStageId) {
      setPendingLostStageId(nextStageId);
      return;
    }
    if (askLostReason) onChange(pipelineId, nextStageId, null);
    else onChange(pipelineId, nextStageId);
  }

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
          onChange={(e) => handleStageChange(e.target.value)}
          className={selectClass}
        >
          {loading && <option value="">Carregando...</option>}
          {!loading && <option value="">Selecionar etapa...</option>}
          {!loading && options.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
      </div>
      {pendingLostStageId && (
        <LostReasonModal
          onCancel={() => setPendingLostStageId(null)}
          onConfirm={(value) => {
            const stageId = pendingLostStageId;
            setPendingLostStageId(null);
            onChange(pipelineId, stageId, value);
          }}
        />
      )}
    </div>
  );
}
