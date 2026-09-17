"use client";

import { useMemo, useState } from "react";
import type { Lead, Pipeline } from "@/lib/types";
import { DealStageRow } from "@/components/conversas/deal-stage-row";
import { DealCreateModal } from "@/components/deals/deal-create-modal";
import { LeadCardMoveRow } from "@/components/leads/lead-card-move-row";
import { buildDealRows } from "@/lib/deal-rows";
import { findOpenDealInPipeline } from "@/lib/lead-funnel-actions";
import { useLeadDeals } from "@/hooks/use-lead-deals";

interface LeadFunisTabProps {
  /** Lead aberto no modal. `id` alimenta o fetch; `name || phone` o título do card. */
  lead: Lead;
  /** Funis visíveis ao usuário. Array vazio = /api/pipelines falhou ou não há funil. */
  pipelines: Pipeline[];
}

/**
 * Aba "Funis" do modal de lead: em quais funis o lead está, em que etapa, e as
 * três ações — trocar etapa (DealStageRow), mover para outro funil
 * (LeadCardMoveRow) e criar card (DealCreateModal).
 *
 * É composição: nenhum controle novo é desenhado aqui. O bloco "Oportunidades"
 * que existia em "Dados Gerais" lia a coluna legada `deals.stage` via Supabase
 * no cliente e rotulava por um array fixo — uma etapa customizada de funil
 * aparecia como o texto cru "novo", e não dava para mover nada.
 */
export function LeadFunisTab({ lead, pipelines }: LeadFunisTabProps) {
  const { deals, stagesByPipeline, refetch, updateDeal } = useLeadDeals(lead.id);
  const rows = useMemo(() => buildDealRows(deals, stagesByPipeline), [deals, stagesByPipeline]);

  // Um painel de "Mover" por vez: dois abertos disputariam a mesma decisão e o
  // vendedor perderia de vista qual card está movendo.
  const [movingDealId, setMovingDealId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  // Sem funis não há destino para escolher nem funil para criar card: o
  // StageTargetPicker e o DealCreateModal ficariam com o select vazio.
  const semFunis = pipelines.length === 0;

  async function handleCreateDeal(data: {
    lead_id: string;
    title: string;
    value: number;
    category: string;
    expected_close_date: string;
    pipeline_id?: string;
    stage_id?: string;
  }) {
    const res = await fetch("/api/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    // Lança de propósito: o modal mostra a mensagem e NÃO fecha. Engolir o erro
    // fecharia o modal anunciando um card que não existe.
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `Erro ao criar card (${res.status}).`);
    }
    // O card já foi criado. Deixar o refetch estourar aqui faria o modal exibir
    // "erro ao criar card" para uma criação que deu certo.
    await refetch().catch(() => {});
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
          Funis do lead ({rows.length})
        </p>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          disabled={semFunis}
          title={semFunis ? "Não foi possível carregar os funis." : undefined}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[4px] border border-[#dedbd6] text-[#111111] text-[12px] font-medium hover:border-[#111111] hover:bg-[#faf9f6] transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:border-[#dedbd6] disabled:hover:bg-transparent"
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
          </svg>
          Novo card
        </button>
      </div>

      {/* Falha do /api/pipelines é independente da lista de cards (vêm de rotas
          diferentes): o lead pode ter cards para editar e ainda assim não haver
          funil para escolher como destino. Por isso o aviso soma à lista em vez
          de substituí-la. */}
      {semFunis && (
        <div role="status" className="bg-[#fff8e0] border border-[#eadfb4] rounded-[6px] px-3 py-2.5">
          <p className="text-[12px] text-[#7a5a00] leading-[1.5]">
            Não foi possível carregar os funis. Criar card e mover ficam indisponíveis;
            trocar a etapa continua funcionando.
          </p>
        </div>
      )}

      {rows.length === 0 ? (
        <p className="text-[13px] text-[#7b7b78]">Este lead não está em nenhum funil.</p>
      ) : (
        <div className="space-y-2">
          {rows.map((row) => {
            const aberto = movingDealId === row.deal.id;
            return (
              <div key={row.deal.id} className="space-y-2">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <DealStageRow row={row} onDealUpdate={updateDeal} />
                  </div>
                  {/* Card fechado não é movido, é reaberto: o PATCH grava
                      closed_at ao entrar em etapa protegida e nunca limpa ao
                      sair, então mover um ganho/perdido para um funil aberto
                      deixaria closed_at e lost_reason velhos no card. O
                      "Reabrir" do DealStageRow é o caminho certo. */}
                  {!row.isClosed && (
                    <button
                      type="button"
                      onClick={() => setMovingDealId(aberto ? null : row.deal.id)}
                      disabled={semFunis}
                      aria-expanded={aberto}
                      aria-label={`Mover ${row.deal.title}`}
                      title={semFunis ? "Não foi possível carregar os funis." : undefined}
                      className={`text-[12px] px-2 py-1 rounded-[4px] border transition-colors flex-shrink-0 mt-2 disabled:opacity-40 disabled:cursor-not-allowed ${
                        aberto
                          ? "border-[#111111] text-[#111111] bg-[#faf9f6]"
                          : "border-[#dedbd6] text-[#111111] hover:border-[#111111]"
                      }`}
                    >
                      Mover
                    </button>
                  )}
                </div>
                {aberto && (
                  <LeadCardMoveRow
                    row={row}
                    pipelines={pipelines}
                    // Fechar o painel em sucesso é DAQUI: `movingDealId` é
                    // estado deste componente, e a LeadCardMoveRow não o
                    // alcança. Sem o `await` antes do fecha, uma falha do
                    // PATCH fecharia o painel e engoliria o erro que a linha
                    // precisa mostrar — o throw de `updateDeal` tem que subir
                    // para o catch de lá.
                    onMove={async (pipelineId, stageId) => {
                      await updateDeal(row.deal.id, {
                        pipeline_id: pipelineId,
                        stage_id: stageId,
                      });
                      setMovingDealId(null);
                    }}
                    onCancel={() => setMovingDealId(null)}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      {showCreate && (
        <DealCreateModal
          leads={[lead]}
          pipelines={pipelines}
          preselectedLead={lead}
          // O funil selecionado mora dentro do modal, então o aviso de duplicata
          // não pode ser um valor fixo: passamos a consulta e o modal a chama com
          // o funil da vez. Card FECHADO naquele funil não avisa — criar um novo
          // ali é o fluxo normal de recompra/reposição.
          existingDealLookup={(pipelineId) => {
            const abertoNoFunil = findOpenDealInPipeline(deals, pipelineId);
            if (!abertoNoFunil) return null;
            return {
              title: abertoNoFunil.title,
              stageLabel: abertoNoFunil.pipeline_stages?.label ?? "etapa sem nome",
            };
          }}
          onClose={() => setShowCreate(false)}
          onCreate={handleCreateDeal}
        />
      )}
    </div>
  );
}
