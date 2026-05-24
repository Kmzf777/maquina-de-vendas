"use client";

import { useState, useEffect, useRef } from "react";
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
import { BulkMoveDealsModal } from "@/components/deals/bulk-move-deals-modal";
import type { Deal, Pipeline, PipelineStage } from "@/lib/types";

function DroppableColumn({
  id, title, dotColor, deals, onDealClick, onBulkMove,
}: {
  id: string; title: string; dotColor: string; deals: Deal[]; onDealClick: (deal: Deal) => void; onBulkMove?: () => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  const columnValue = deals.reduce((sum, d) => sum + (d.value || 0), 0);
  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
  const [showMenu, setShowMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showMenu) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showMenu]);

  return (
    <div className="bg-[#f7f5f1] border border-[#dedbd6] rounded-[8px] flex flex-col min-h-[200px] w-72 flex-shrink-0">
      <div className="px-4 py-3 bg-[#f0ede8] border-b border-[#dedbd6] rounded-t-[8px] flex items-center justify-between group">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: dotColor }} />
          <h3 className="text-[13px] font-medium text-[#111111] uppercase tracking-[0.6px]">{title}</h3>
        </div>
        <div className="flex items-center gap-2">
          {columnValue > 0 && <span className="text-[11px] text-[#7b7b78]">{fmt(columnValue)}</span>}
          <span className="text-[12px] text-[#7b7b78] bg-white border border-[#dedbd6] rounded-full px-2 py-0.5">{deals.length}</span>
          {deals.length > 0 && (
            <div ref={menuRef} className="relative">
              <button
                onClick={() => setShowMenu((v) => !v)}
                className="opacity-0 group-hover:opacity-100 transition-opacity text-[#7b7b78] hover:text-[#111111] px-1 leading-none text-[16px]"
                title="Opções da coluna"
              >
                ···
              </button>
              {showMenu && (
                <div className="absolute right-0 top-full mt-1 bg-white border border-[#dedbd6] rounded-[6px] shadow-none z-20 min-w-[140px]">
                  <button
                    onClick={() => { setShowMenu(false); onBulkMove?.(); }}
                    className="w-full text-left px-3 py-2 text-[13px] text-[#111111] hover:bg-[#faf9f6] rounded-[6px] transition-colors"
                  >
                    Mover deals...
                  </button>
                </div>
              )}
            </div>
          )}
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
          <DraggableDealCard key={deal.id} deal={deal} onClick={onDealClick} />
        ))}
      </div>
    </div>
  );
}

function DraggableDealCard({ deal, onClick }: { deal: Deal; onClick: (deal: Deal) => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: deal.id, data: deal });
  return (
    <div ref={setNodeRef} {...listeners} {...attributes} className={isDragging ? "opacity-30" : ""}>
      <DealCard deal={deal} onClick={onClick} />
    </div>
  );
}

export default function VendasPage() {
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
  const [bulkMoveStage, setBulkMoveStage] = useState<PipelineStage | null>(null);

  // Auto-selecionar primeiro pipeline
  useEffect(() => {
    if (pipelines.length > 0 && !selectedPipelineId) {
      setSelectedPipelineId(pipelines[0].id);
    }
  }, [pipelines, selectedPipelineId]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  const { ref: kanbanRef, onMouseDown: kanbanMouseDown, onMouseMove: kanbanMouseMove, onMouseUp: kanbanMouseUp, onMouseLeave: kanbanMouseLeave } = useDragScroll();

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
    if (!res.ok) throw new Error("Erro ao atualizar deal");
    setSelectedDealId(null);
  }

  async function handleCreatePipeline(name: string) {
    const res = await fetch("/api/pipelines", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
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

  async function handleBulkMove(dealIds: string[], targetStageId: string) {
    const results = await Promise.all(
      dealIds.map((id) =>
        fetch(`/api/deals/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ stage_id: targetStageId }),
        })
      )
    );
    if (results.some((r) => !r.ok)) {
      alert("Erro ao mover alguns deals. Tente novamente.");
    }
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
    if (search) {
      const q = search.toLowerCase();
      const lead = d.leads;
      const match =
        d.title.toLowerCase().includes(q) ||
        (lead?.name || "").toLowerCase().includes(q) ||
        (lead?.company || "").toLowerCase().includes(q) ||
        (lead?.phone || "").includes(q);
      if (!match) return false;
    }
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
          onSelect={setSelectedPipelineId}
          onCreateNew={() => setShowPipelineCreate(true)}
          onEdit={() => setShowPipelineEdit(true)}
          onDelete={handleDeletePipeline}
        />
        <button
          onClick={() => setShowCreate(true)}
          className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] flex items-center gap-2"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
          </svg>
          Novo Card
        </button>
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
            className="flex gap-3 overflow-x-auto p-4 md:p-6 pt-2 touch-pan-x"
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
                  onDealClick={(deal) => setSelectedDealId(deal.id)}
                  onBulkMove={() => setBulkMoveStage(stage)}
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
        <DealDetailSidebar deal={selectedDeal} stages={stages} onClose={() => setSelectedDealId(null)} onUpdate={handleUpdateDeal} onDelete={handleDeleteDeal} />
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
          stages={stages}
          onClose={() => setShowPipelineEdit(false)}
          onSaved={refetchStages}
        />
      )}
      {bulkMoveStage && (
        <BulkMoveDealsModal
          deals={filteredDeals.filter((d) => d.stage_id === bulkMoveStage.id)}
          stages={stages}
          sourceStageId={bulkMoveStage.id}
          sourceStageName={bulkMoveStage.label}
          onClose={() => setBulkMoveStage(null)}
          onMove={handleBulkMove}
        />
      )}
    </div>
  );
}
