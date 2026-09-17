"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { distinctPipelineIds, type LeadDeal, type StagesByPipeline } from "@/lib/deal-rows";
import { useStagesByPipeline } from "@/hooks/use-stages-by-pipeline";

// Constantes de módulo, não literais inline: `deals` entra em useMemo do
// consumidor (buildDealRows), e um [] novo a cada render recalcularia tudo.
const EMPTY_DEALS: LeadDeal[] = [];
const EMPTY_STAGES: StagesByPipeline = {};

/**
 * Camada de dados das oportunidades de um lead: os cards, os stages dos funis
 * onde eles estão, e as duas mutações (recarregar e alterar um card).
 *
 * Extraído do que hoje vive inline em `components/conversas/contact-detail.tsx`
 * (fetchDeals/handleDealUpdate). Aquele painel NÃO foi migrado nesta entrega —
 * é produção de uso diário e o ganho seria cosmético —, então as duas
 * implementações convivem de propósito. Cada regra abaixo existe por um bug
 * real já corrigido lá; mudar uma aqui pede mudar a de lá.
 *
 * Não busca os stages de um funil de DESTINO que o usuário abra no "Mover":
 * o `StageTargetPicker` busca os seus próprios.
 */
export function useLeadDeals(leadId: string | undefined): {
  deals: LeadDeal[];
  stagesByPipeline: StagesByPipeline;
  /** LANÇA em falha. */
  refetch: () => Promise<void>;
  /** LANÇA em falha. */
  updateDeal: (dealId: string, patch: Record<string, unknown>) => Promise<void>;
} {
  const [loadedDeals, setLoadedDeals] = useState<LeadDeal[]>([]);

  // Contador monotônico de requisição. Ver o descarte dentro de `refetch`.
  const reqRef = useRef(0);

  const refetch = useCallback(async () => {
    // Sem lead não há o que buscar; o vazio é derivado mais abaixo.
    if (!leadId) return;
    const reqId = ++reqRef.current;
    const res = await fetch(`/api/leads/${leadId}/deals`);
    // Lança em vez de sair calado: se o PATCH deu certo e só o refetch falhou,
    // o select voltaria ao valor antigo sem erro — dizendo ao vendedor que a
    // mudança não pegou quando ela pegou.
    if (!res.ok) throw new Error("Não foi possível recarregar as oportunidades.");
    const data = await res.json();
    // Descarta resposta obsoleta: com N linhas editáveis, dois PATCH quase
    // simultâneos disparam dois refetch, e o mais antigo chegando por último
    // reverteria a linha mais nova sem erro nenhum.
    if (reqId !== reqRef.current) return;
    setLoadedDeals(Array.isArray(data) ? data : []);
  }, [leadId]);

  useEffect(() => {
    // Carga inicial não tem ação a reverter nem linha onde mostrar o erro; a
    // aba só fica sem oportunidades. Quem precisa do erro é o PATCH.
    refetch().catch(() => {});
  }, [refetch]);

  // Lança de propósito: engolir o 403 do guard de funil (ou um 422/500) fazia o
  // select voltar sozinho sem dizer por quê. Quem chama (DealStageRow,
  // LeadCardMoveRow) captura e mostra o erro na própria linha.
  const updateDeal = useCallback(
    async (dealId: string, patch: Record<string, unknown>) => {
      const res = await fetch(`/api/deals/${dealId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `Erro ao atualizar oportunidade (${res.status}).`);
      }
      await refetch();
    },
    [refetch]
  );

  // Sem lead o vazio é DERIVADO, não um setState de limpeza dentro do efeito:
  // limpar por state custaria um render em cascata (é o que a regra
  // react-hooks/set-state-in-effect aponta) e ainda deixaria uma janela em que
  // os cards do lead anterior aparecem sob o lead novo.
  const deals = leadId ? loadedDeals : EMPTY_DEALS;

  const pipelineIds = useMemo(() => distinctPipelineIds(deals), [deals]);
  // useStagesByPipeline é a única fonte de stages aqui porque ele já respeita a
  // regra de que `buildDealRows` depende: funil cujo fetch falhou fica AUSENTE
  // do record, nunca gravado como []. `stagesUnknown` é decidido por
  // `pipelineId in stagesByPipeline`, então um [] faria toda linha aberta
  // daquele funil virar read-only em silêncio em vez de esperar os stages.
  const { stagesByPipeline } = useStagesByPipeline(pipelineIds);

  return {
    deals,
    // O cache interno de useStagesByPipeline sobrevive à troca de lead; sem
    // lead o contrato é devolver vazio, não o resto do cache.
    stagesByPipeline: leadId ? stagesByPipeline : EMPTY_STAGES,
    refetch,
    updateDeal,
  };
}
