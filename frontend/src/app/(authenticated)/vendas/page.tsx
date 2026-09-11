"use client";

import { useState, useEffect, useRef, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  DndContext, DragOverlay, closestCorners, PointerSensor, useSensor, useSensors,
  type DragStartEvent, type DragEndEvent,
} from "@dnd-kit/core";
import { useDroppable, useDraggable } from "@dnd-kit/core";
import { useRealtimeDeals } from "@/hooks/use-realtime-deals";
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { usePipelines, usePipelineStages } from "@/hooks/use-pipelines";
import { useDragScroll } from "@/hooks/use-drag-scroll";
import { DealCard } from "@/components/deals/deal-card";
import { DealKanbanMetrics } from "@/components/deals/deal-kanban-metrics";
import { DealKanbanFilters } from "@/components/deals/deal-kanban-filters";
import { DealCreateModal } from "@/components/deals/deal-create-modal";
import { DealDetailSidebar } from "@/components/deals/deal-detail-sidebar";
import { LostReasonModal } from "@/components/deals/lost-reason-modal";
import { PipelineSwitcher } from "@/components/deals/pipeline-switcher";
import { PipelineCreateModal } from "@/components/deals/pipeline-create-modal";
import { PipelineEditModal } from "@/components/deals/pipeline-edit-modal";
import { BulkMoveModal } from "@/components/deals/bulk-move-modal";
import { chunk, summarizeMoveResults, MOVE_BATCH_SIZE, type MoveResult } from "@/lib/bulk-move-deals";
import { useCurrentRole } from "@/hooks/use-current-role";
import type { Deal, Pipeline } from "@/lib/types";
import { dealMatchesSearch } from "@/lib/search";

function DroppableColumn({
  id, title, dotColor, deals, onDealClick, selectionMode, selectedIds, onToggleAll,
}: {
  id: string; title: string; dotColor: string; deals: Deal[];
  onDealClick: (deal: Deal) => void;
  selectionMode: boolean;
  selectedIds: Set<string>;
  onToggleAll: (dealIds: string[], selectAll: boolean) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  const columnValue = deals.reduce((sum, d) => sum + (d.value || 0), 0);
  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  const selectedHere = deals.filter((d) => selectedIds.has(d.id)).length;
  const allSelected = deals.length > 0 && selectedHere === deals.length;
  const someSelected = selectedHere > 0 && !allSelected;

  return (
    <div className="bg-[#f7f5f1] border border-[#dedbd6] rounded-[8px] flex flex-col min-h-[200px] w-72 flex-shrink-0">
      <div className="px-4 py-3 bg-[#f0ede8] border-b border-[#dedbd6] rounded-t-[8px] flex items-center justify-between">
        <div className="flex items-center gap-2">
          {selectionMode && deals.length > 0 && (
            <button
              onClick={() => onToggleAll(deals.map((d) => d.id), !allSelected)}
              role="checkbox"
              aria-checked={allSelected ? true : someSelected ? "mixed" : false}
              title={allSelected ? "Desmarcar coluna" : "Selecionar coluna"}
              className={`w-4 h-4 rounded-[3px] border flex items-center justify-center flex-shrink-0 ${
                allSelected || someSelected ? "bg-[#111111] border-[#111111]" : "bg-white border-[#dedbd6]"
              }`}
            >
              {allSelected && (
                <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 6L9 17l-5-5" />
                </svg>
              )}
              {someSelected && <span className="w-2 h-[2px] bg-white rounded-full" />}
            </button>
          )}
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: dotColor }} />
          <h3 className="text-[13px] font-medium text-[#111111] uppercase tracking-[0.6px]">{title}</h3>
        </div>
        <div className="flex items-center gap-2">
          {columnValue > 0 && <span className="text-[11px] text-[#7b7b78]">{fmt(columnValue)}</span>}
          <span className="text-[12px] text-[#7b7b78] bg-white border border-[#dedbd6] rounded-full px-2 py-0.5">{deals.length}</span>
        </div>
      </div>
      <div
        ref={setNodeRef}
        className={`flex-1 py-2 overflow-y-auto transition-all duration-200 ${isOver ? "ring-2 ring-[#111111] ring-inset rounded-b-[8px]" : ""}`}
      >
        {deals.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <p className="text-[12px] text-[#7b7b78]">Nenhum deal</p>
          </div>
        )}
        {deals.map((deal) => (
          <DraggableDealCard
            key={deal.id}
            deal={deal}
            onClick={onDealClick}
            selectionMode={selectionMode}
            selected={selectedIds.has(deal.id)}
          />
        ))}
      </div>
    </div>
  );
}

function DraggableDealCard({
  deal, onClick, selectionMode, selected,
}: {
  deal: Deal; onClick: (deal: Deal) => void; selectionMode: boolean; selected: boolean;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: deal.id,
    data: deal,
    // Em modo selecao o PointerSensor competiria com o clique de marcar, e um
    // arrasto acidental moveria um card no meio da selecao.
    disabled: selectionMode,
  });
  return (
    <div
      ref={setNodeRef}
      {...(selectionMode ? {} : listeners)}
      {...attributes}
      className={isDragging ? "opacity-30" : ""}
    >
      <DealCard deal={deal} onClick={onClick} selectable={selectionMode} selected={selected} />
    </div>
  );
}

function VendasPageInner() {
  const { role } = useCurrentRole();
  const isAdmin = role === "admin";
  const { pipelines, loading: pipelinesLoading, refetch: refetchPipelines } = usePipelines();
  const [selectedPipelineId, setSelectedPipelineId] = useState<string | null>(null);
  const { stages, refetch: refetchStages } = usePipelineStages(selectedPipelineId);
  const { deals, loading: dealsLoading } = useRealtimeDeals(selectedPipelineId);
  const { leads } = useRealtimeLeads();

  const [selectedDealId, setSelectedDealId] = useState<string | null>(null);
  const selectedDeal = deals.find((d) => d.id === selectedDealId) ?? null;
  const [activeDrag, setActiveDrag] = useState<Deal | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showPipelineCreate, setShowPipelineCreate] = useState(false);
  const [showPipelineEdit, setShowPipelineEdit] = useState(false);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [showActive, setShowActive] = useState(true);
  const [lostDeal, setLostDeal] = useState<{ deal: Deal; stageId: string } | null>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showBulkMove, setShowBulkMove] = useState(false);
  const [moveProgress, setMoveProgress] = useState<{ done: number; total: number } | null>(null);

  // Trocar de funil zera a selecao: os ids marcados sao de outro board e mover as
  // cegas seria surpresa. Ajuste no corpo do render — padrao oficial do React para
  // "resetar estado quando algo muda" — e nao useEffect: com o efeito, a tela
  // renderizava uma vez com a selecao antiga ainda valendo, e nessa janela o botao
  // "Mover (N)" mostrava a contagem do funil anterior.
  const [selectionPipelineId, setSelectionPipelineId] = useState(selectedPipelineId);
  if (selectionPipelineId !== selectedPipelineId) {
    setSelectionPipelineId(selectedPipelineId);
    setSelectionMode(false);
    setSelectedIds(new Set());
    setShowBulkMove(false);
  }

  function exitSelection() {
    setSelectionMode(false);
    setSelectedIds(new Set());
    setShowBulkMove(false);
  }

  function toggleDealSelection(dealId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(dealId)) next.delete(dealId);
      else next.add(dealId);
      return next;
    });
  }

  function toggleColumnSelection(dealIds: string[], selectAll: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const id of dealIds) {
        if (selectAll) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }

  const searchParams = useSearchParams();
  const router = useRouter();
  const deepLinkDealId = useRef<string | null>(null);
  const deepLinkApplied = useRef(false);

  // Deep-link: /busca?deal_id= pode apontar pra um deal fora do funil aberto.
  // 1o efeito: descobre o funil do deal e troca o funil selecionado.
  useEffect(() => {
    const dealId = searchParams.get("deal_id");
    if (!dealId || deepLinkApplied.current || deepLinkDealId.current) return;
    deepLinkDealId.current = dealId;

    // 404 = deal inexistente OU fora do escopo de funis do usuario (a rota nao
    // confirma existencia por enumeracao). Nos dois casos desiste em silencio,
    // sem alerta e sem deixar a pagina esperando: so limpa a URL.
    const giveUp = () => {
      deepLinkDealId.current = null;
      deepLinkApplied.current = true;
      router.replace("/vendas");
    };

    fetch(`/api/deals/${dealId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((deal) => {
        if (deal?.pipeline_id) setSelectedPipelineId(deal.pipeline_id);
        else giveUp();
      })
      .catch(giveUp);
  }, [searchParams, router]);

  // 2o efeito: quando o funil certo estiver selecionado e `deals` (ja filtrado
  // por ele) tiver carregado, abre o deal e limpa a URL.
  useEffect(() => {
    if (deepLinkApplied.current || !deepLinkDealId.current || dealsLoading) return;
    const match = deals.find((d) => d.id === deepLinkDealId.current);
    if (match) {
      setSelectedDealId(match.id);
      deepLinkApplied.current = true;
      router.replace("/vendas");
    }
  }, [deals, dealsLoading, router]);

  // Auto-selecionar primeiro pipeline
  useEffect(() => {
    if (pipelines.length > 0 && !selectedPipelineId) {
      setSelectedPipelineId(pipelines[0].id);
    }
  }, [pipelines, selectedPipelineId]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  const { ref: kanbanRef, isDraggingScroll, onMouseDown: kanbanMouseDown, onMouseMove: kanbanMouseMove, onMouseUp: kanbanMouseUp, onMouseLeave: kanbanMouseLeave } = useDragScroll();

  function handleDragStart(event: DragStartEvent) { setActiveDrag(event.active.data.current as Deal); }

  async function handleDragEnd(event: DragEndEvent) {
    setActiveDrag(null);
    const { active, over } = event;
    if (!over) return;
    const deal = active.data.current as Deal;
    const newStageId = over.id as string;
    if (deal.stage_id === newStageId) return;
    const newStage = stages.find((s) => s.id === newStageId);
    if (newStage?.key === "fechado_perdido") {
      setLostDeal({ deal, stageId: newStageId });
      return;
    }
    const res = await fetch(`/api/deals/${deal.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage_id: newStageId }),
    });
    if (!res.ok) alert("Erro ao mover deal. Tente novamente.");
  }

  async function handleLostConfirm(reason: string) {
    if (!lostDeal) return;
    const res = await fetch(`/api/deals/${lostDeal.deal.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage_id: lostDeal.stageId, lost_reason: reason }),
    });
    if (!res.ok) { alert("Erro ao registrar perda. Tente novamente."); return; }
    setLostDeal(null);
  }

  async function handleCreateDeal(data: {
    lead_id: string; title: string; value: number; category: string; expected_close_date: string; pipeline_id?: string;
  }) {
    if (!selectedPipelineId) throw new Error("Nenhum funil selecionado.");
    const res = await fetch("/api/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...data, pipeline_id: selectedPipelineId }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || "Erro ao criar deal.");
    }
  }

  async function handleUpdateDeal(dealId: string, data: Record<string, unknown>) {
    const res = await fetch(`/api/deals/${dealId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      // A rota devolve mensagens úteis (ex.: "Permissão insuficiente para este funil.")
      // ao mover para um funil de outro vendedor — jogar fora vira erro genérico na tela.
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || "Erro ao atualizar deal");
    }
    setSelectedDealId(null);
  }

  async function handleCreatePipeline(name: string, ownerUserId: string | null) {
    const res = await fetch("/api/pipelines", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, owner_user_id: ownerUserId }),
    });
    if (!res.ok) {
      const { error } = await res.json().catch(() => ({}));
      throw new Error(error || "Erro ao criar funil.");
    }
    const pipeline = await res.json();
    await refetchPipelines();
    if (pipeline?.id) setSelectedPipelineId(pipeline.id);
  }

  async function handleDeletePipeline(pipeline: Pipeline) {
    if (!window.confirm(`Excluir o funil "${pipeline.name}"? Esta ação não pode ser desfeita.`)) return;
    const res = await fetch(`/api/pipelines/${pipeline.id}`, { method: "DELETE" });
    if (!res.ok) {
      const { error } = await res.json();
      alert(error);
      return;
    }
    setSelectedPipelineId(pipelines.find((p) => p.id !== pipeline.id)?.id ?? null);
  }

  async function handleBulkMove(targetPipelineId: string, targetStageId: string) {
    const ids = [...selectedIds];
    setMoveProgress({ done: 0, total: ids.length });
    let done = 0;

    const results: MoveResult[] = [];
    try {
      // Em lotes: cada PATCH faz 3 round-trips no Supabase e dispara um webhook de
      // automacao. Mandar tudo de uma vez martela o backend sem ganho nenhum.
      for (const batch of chunk(ids, MOVE_BATCH_SIZE)) {
        const batchResults = await Promise.all(
          batch.map(async (id): Promise<MoveResult> => {
            try {
              const res = await fetch(`/api/deals/${id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                // Manda sempre os dois campos. Os lotes levam segundos, e decidir
                // "o funil nao mudou" pelo estado que a tela tinha no inicio grava
                // stage_id novo com pipeline_id velho se outra pessoa mover o mesmo
                // deal no meio — e o card some do board. A rota compara com a linha
                // fresca do banco, entao mandar valor igual nao custa guarda extra.
                body: JSON.stringify({ pipeline_id: targetPipelineId, stage_id: targetStageId }),
              });
              if (res.ok) return { id, ok: true };
              const body = await res.json().catch(() => ({}));
              return { id, ok: false, error: body.error || `HTTP ${res.status}` };
            } catch {
              return { id, ok: false, error: "Falha de rede" };
            } finally {
              done += 1;
              setMoveProgress({ done, total: ids.length });
            }
          })
        );
        results.push(...batchResults);
      }
    } finally {
      // Sem isto, um throw inesperado deixaria progress != null para sempre — e o
      // dialogo trava o X e o backdrop nesse estado, exigindo reload da pagina.
      setMoveProgress(null);
    }

    const summary = summarizeMoveResults(results);
    setShowBulkMove(false);

    if (summary.failed === 0) {
      exitSelection();
      return;
    }
    // Mantem os que falharam marcados: o usuario ve quais sao e pode tentar de novo.
    setSelectedIds(new Set(summary.failedIds));
    alert(summary.message);
  }

  async function handleDeleteDeal(dealId: string) {
    if (!window.confirm("Excluir esta oportunidade? Esta ação não pode ser desfeita.")) return;
    const res = await fetch(`/api/deals/${dealId}`, { method: "DELETE" });
    if (!res.ok) { alert("Erro ao excluir deal. Tente novamente."); return; }
    setSelectedDealId(null);
  }

  const loading = pipelinesLoading || dealsLoading;

  if (loading && pipelines.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin" />
          <span className="text-[14px] text-[#7b7b78]">Carregando...</span>
        </div>
      </div>
    );
  }

  const filteredDeals = deals.filter((d) => {
    const stage = stages.find((s) => s.id === d.stage_id);
    if (showActive && stage?.is_protected) return false;
    if (category && d.category !== category) return false;
    if (search && !dealMatchesSearch(search, d)) return false;
    return true;
  });

  const activePipeline = pipelines.find((p) => p.id === selectedPipelineId) ?? null;

  return (
    <div className="flex flex-col h-full">
      {/* Page Header */}
      <div className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-3 md:py-5 flex items-center justify-between flex-shrink-0">
        <PipelineSwitcher
          pipelines={pipelines}
          activePipelineId={selectedPipelineId}
          isAdmin={isAdmin}
          onSelect={setSelectedPipelineId}
          onCreateNew={() => setShowPipelineCreate(true)}
          onEdit={() => setShowPipelineEdit(true)}
          onDelete={handleDeletePipeline}
        />
        <div className="flex items-center gap-2">
          {selectionMode ? (
            <>
              <button
                onClick={exitSelection}
                className="border border-[#dedbd6] text-[#313130] px-3 py-2 rounded-[4px] text-[14px] hover:border-[#111111] transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={() => setShowBulkMove(true)}
                disabled={selectedIds.size === 0}
                title={selectedIds.size === 0 ? "Selecione ao menos 1 deal" : undefined}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
              >
                Mover ({selectedIds.size})
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setSelectionMode(true)}
                className="border border-[#dedbd6] text-[#313130] px-3 py-2 rounded-[4px] text-[14px] hover:border-[#111111] transition-colors"
              >
                Editar Deals
              </button>
              <button
                onClick={() => setShowCreate(true)}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] flex items-center gap-2"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
                </svg>
                Novo Card
              </button>
            </>
          )}
        </div>
      </div>

      {/* Kanban content area */}
      <div className="flex-1 overflow-auto bg-[#faf9f6]">
        <DealKanbanMetrics deals={deals} />
        <div className="px-6 pt-4">
          <DealKanbanFilters
            search={search} onSearchChange={setSearch}
            category={category} onCategoryChange={setCategory}
            showActive={showActive} onToggleActive={() => setShowActive(!showActive)}
          />
        </div>

        <DndContext sensors={sensors} collisionDetection={closestCorners} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div
            ref={kanbanRef}
            className={`flex gap-3 overflow-x-auto p-4 md:p-6 pt-2 touch-pan-x ${isDraggingScroll ? "cursor-grabbing select-none" : "cursor-grab"}`}
            onMouseDown={kanbanMouseDown}
            onMouseMove={kanbanMouseMove}
            onMouseUp={kanbanMouseUp}
            onMouseLeave={kanbanMouseLeave}
          >
            {stages.map((stage) => {
              const stageDeals = filteredDeals.filter((d) => d.stage_id === stage.id);
              return (
                <DroppableColumn
                  key={stage.id}
                  id={stage.id}
                  title={stage.label}
                  dotColor={stage.dot_color}
                  deals={stageDeals}
                  onDealClick={(deal) => {
                    if (selectionMode) toggleDealSelection(deal.id);
                    else setSelectedDealId(deal.id);
                  }}
                  selectionMode={selectionMode}
                  selectedIds={selectedIds}
                  onToggleAll={toggleColumnSelection}
                />
              );
            })}
          </div>
          <DragOverlay>
            {activeDrag ? (
              <div className="w-[270px] opacity-90 rotate-[2deg]">
                <DealCard deal={activeDrag} onClick={() => {}} />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      </div>

      {selectedDeal && (
        <DealDetailSidebar deal={selectedDeal} stages={stages} pipelines={pipelines} onClose={() => setSelectedDealId(null)} onUpdate={handleUpdateDeal} onDelete={handleDeleteDeal} />
      )}
      {showCreate && selectedPipelineId && (
        <DealCreateModal leads={leads} pipelines={pipelines} onClose={() => setShowCreate(false)} onCreate={handleCreateDeal} />
      )}
      {lostDeal && (
        <LostReasonModal onConfirm={handleLostConfirm} onCancel={() => setLostDeal(null)} />
      )}
      {showPipelineCreate && (
        <PipelineCreateModal onClose={() => setShowPipelineCreate(false)} onCreate={handleCreatePipeline} />
      )}
      {showPipelineEdit && activePipeline && (
        <PipelineEditModal
          pipelineId={activePipeline.id}
          pipelineName={activePipeline.name}
          ownerUserId={activePipeline.owner_user_id}
          isUniversal={activePipeline.is_universal}
          stages={stages}
          onClose={() => setShowPipelineEdit(false)}
          onSaved={refetchStages}
        />
      )}
      {showBulkMove && selectedPipelineId && (
        <BulkMoveModal
          count={selectedIds.size}
          deals={deals.filter((d) => selectedIds.has(d.id))}
          pipelines={pipelines}
          currentPipelineId={selectedPipelineId}
          currentStages={stages}
          progress={moveProgress}
          onClose={() => setShowBulkMove(false)}
          onMove={handleBulkMove}
        />
      )}
    </div>
  );
}

export default function VendasPage() {
  return (
    <Suspense>
      <VendasPageInner />
    </Suspense>
  );
}
