"use client";

import { useId, useState } from "react";
import type { Pipeline } from "@/lib/types";
import type { DealRow } from "@/lib/deal-rows";
import { StageTargetPicker } from "@/components/deals/stage-target-picker";
import { isSameTarget } from "@/lib/lead-funnel-actions";

interface LeadCardMoveRowProps {
  row: DealRow;
  pipelines: Pipeline[];
  /** Resolve em sucesso; LANÇA Error com mensagem legível em falha. */
  onMove: (pipelineId: string, stageId: string) => Promise<void>;
  /** Fecha o painel sem mover. O pai é quem guarda qual linha está aberta. */
  onCancel: () => void;
}

/**
 * Painel de "Mover" que abre dentro da própria linha do card, na aba "Funis"
 * do modal de lead. Escolhe funil + etapa de destino e confirma.
 *
 * Não espelha o estado do card: o que está aqui é um DESTINO escolhido, e a
 * verdade do servidor continua sendo renderizada pelo `DealStageRow` logo
 * acima. Por isso uma falha não precisa "reverter" nada — basta mostrar o erro
 * na linha e manter a escolha para o vendedor tentar de novo.
 */
export function LeadCardMoveRow({ row, pipelines, onMove, onCancel }: LeadCardMoveRowProps) {
  const { deal } = row;
  // Começa no funil e na etapa atuais do card: o painel abre mostrando onde o
  // card está, e não um destino que ninguém escolheu.
  const [pipelineId, setPipelineId] = useState(deal.pipeline_id ?? "");
  const [stageId, setStageId] = useState(deal.stage_id ?? "");
  const [moving, setMoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorId = useId();
  const hintId = useId();

  const mesmoDestino = isSameTarget(deal, pipelineId, stageId);
  const semEtapa = stageId === "";
  const podeMover = !moving && !semEtapa && !mesmoDestino;

  async function handleMove() {
    setError(null);
    setMoving(true);
    try {
      // O par funil+etapa vai junto num único PATCH: mandar só o stage_id
      // deixaria o card com pipeline_id do funil antigo e etapa do novo — é
      // exatamente a forma de bug que faz o card desaparecer do board.
      await onMove(pipelineId, stageId);
      // Sucesso não fecha nada aqui: `movingDealId` é estado do pai, que fecha
      // o painel quando este `onMove` resolve. Uma falha faz `onMove` lançar,
      // cai no catch abaixo e o painel FICA aberto com o erro à vista.
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao mover o card.");
    } finally {
      setMoving(false);
    }
  }

  return (
    <div className="rounded-[6px] border border-[#dedbd6] bg-[#faf9f6] p-3 space-y-3">
      <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Mover card</p>

      <StageTargetPicker
        pipelines={pipelines}
        pipelineId={pipelineId}
        stageId={stageId}
        // Nenhuma etapa vem pré-carregada: `row.stageOptions` já filtrou as
        // etapas de fechamento e não tem o tipo completo de PipelineStage.
        // Deixar o picker buscar a lista do próprio funil do card garante que a
        // etapa atual apareça mesmo sendo protegida (via `currentStageId`).
        localPipelineId={null}
        localStages={[]}
        currentStageId={deal.stage_id}
        // Trocar de funil zera a etapa em vez de adivinhar a primeira: mover é
        // decisão explícita, e a etapa de destino dispara `deal_stage_enter`.
        autoSelectFirstStage={false}
        disabled={moving}
        onChange={(nextPipelineId, nextStageId) => {
          setPipelineId(nextPipelineId);
          setStageId(nextStageId);
        }}
      />

      {/* Diz por que o botão está desligado. Sem isto, trocar de funil apaga a
          etapa e o "Mover" fica cinza sem explicação. */}
      {(semEtapa || mesmoDestino) && !error && (
        <p id={hintId} className="text-[11px] text-[#7b7b78]">
          {semEtapa ? "Escolha a etapa de destino." : "O card já está neste funil e etapa."}
        </p>
      )}

      {/* Erro na própria linha, nunca global: um 403 do guard de funil num card
          não pode borrar a aba inteira. role=alert porque o ponto é o vendedor
          FICAR SABENDO por que o card não moveu. */}
      {error && (
        <p id={errorId} role="alert" className="text-[11px] text-[#e53e3e]">
          {error}
        </p>
      )}

      <div className="flex gap-2 justify-end">
        <button
          type="button"
          onClick={onCancel}
          disabled={moving}
          className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors disabled:opacity-40"
        >
          Cancelar
        </button>
        <button
          type="button"
          onClick={handleMove}
          disabled={!podeMover}
          aria-busy={moving}
          aria-describedby={error ? errorId : semEtapa || mesmoDestino ? hintId : undefined}
          className="bg-[#111111] text-white px-[14px] py-1.5 rounded-[4px] text-[13px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
        >
          {moving ? "Movendo..." : "Mover"}
        </button>
      </div>
    </div>
  );
}
