"use client";

import { useState } from "react";
import {
  DndContext, DragOverlay, closestCorners, PointerSensor, useSensor, useSensors,
  type DragStartEvent, type DragEndEvent,
} from "@dnd-kit/core";
import { useDroppable, useDraggable } from "@dnd-kit/core";
import { useRealtimeDeals } from "@/hooks/use-realtime-deals";
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { DEAL_STAGES } from "@/lib/constants";
import { DealCard } from "@/components/deals/deal-card";
import { DealKanbanMetrics } from "@/components/deals/deal-kanban-metrics";
import { DealKanbanFilters } from "@/components/deals/deal-kanban-filters";
import { DealCreateModal } from "@/components/deals/deal-create-modal";
import { DealDetailSidebar } from "@/components/deals/deal-detail-sidebar";
import { LostReasonModal } from "@/components/deals/lost-reason-modal";
import type { Deal } from "@/lib/types";

function DroppableColumn({
  id, title, dotColor, tintColor, deals, onDealClick,
}: {
  id: string; title: string; dotColor: string; tintColor: string; deals: Deal[]; onDealClick: (deal: Deal) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  const columnValue = deals.reduce((sum, d) => sum + (d.value || 0), 0);
  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  return (
    <div className="flex-shrink-0 w-[270px]">
      <div className="bg-[#1f1f1f] rounded-t-xl px-3.5 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: dotColor }} />
          <h3 className="text-[12px] font-semibold text-white">{title}</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-[#9ca3af]">{fmt(columnValue)}</span>
          <span className="text-[10px] font-semibold text-white bg-white/15 rounded-full px-2 py-0.5">{deals.length}</span>
        </div>
      </div>
      <div
        ref={setNodeRef}
        className={`rounded-b-xl p-2.5 min-h-[calc(100vh-280px)] space-y-2.5 overflow-y-auto transition-all duration-200 ${isOver ? "ring-2 ring-[#c8cc8e] ring-inset" : ""}`}
        style={{ backgroundColor: tintColor }}
      >
        {deals.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <p className="text-[12px] text-[#b0adb5]">Nenhum deal</p>
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
  const { deals, loading } = useRealtimeDeals();
  const { leads } = useRealtimeLeads();
  const [selectedDeal, setSelectedDeal] = useState<Deal | null>(null);
  const [activeDrag, setActiveDrag] = useState<Deal | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [showActive, setShowActive] = useState(true);
  const [lostDeal, setLostDeal] = useState<Deal | null>(null);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  function handleDragStart(event: DragStartEvent) { setActiveDrag(event.active.data.current as Deal); }

  async function handleDragEnd(event: DragEndEvent) {
    setActiveDrag(null);
    const { active, over } = event;
    if (!over) return;
    const deal = active.data.current as Deal;
    const newStage = over.id as string;
    if (deal.stage === newStage) return;
    if (newStage === "fechado_perdido") { setLostDeal({ ...deal, stage: newStage }); return; }
    await fetch(`/api/deals/${deal.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stage: newStage }) });
  }

  async function handleLostConfirm(reason: string) {
    if (!lostDeal) return;
    await fetch(`/api/deals/${lostDeal.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stage: "fechado_perdido", lost_reason: reason }) });
    setLostDeal(null);
  }

  async function handleCreateDeal(data: { lead_id: string; title: string; value: number; category: string; expected_close_date: string }) {
    await fetch("/api/deals", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  }

  async function handleUpdateDeal(dealId: string, data: Record<string, unknown>) {
    await fetch(`/api/deals/${dealId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
    setSelectedDeal(null);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
          <span className="text-[14px] text-[#5f6368]">Carregando...</span>
        </div>
      </div>
    );
  }

  const filteredDeals = deals.filter((d) => {
    if (showActive && (d.stage === "fechado_ganho" || d.stage === "fechado_perdido")) return false;
    if (category && d.category !== category) return false;
    if (search) {
      const q = search.toLowerCase();
      const lead = d.leads;
      const match = d.title.toLowerCase().includes(q) || (lead?.name || "").toLowerCase().includes(q) || (lead?.company || "").toLowerCase().includes(q) || (lead?.phone || "").includes(q);
      if (!match) return false;
    }
    return true;
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-[28px] font-bold text-[#1f1f1f]">Oportunidades</h1>
          <p className="text-[14px] text-[#5f6368] mt-1">Pipeline de vendas</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary flex items-center gap-2 px-5 py-2.5 rounded-xl text-[13px] font-medium">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="8" y1="3" x2="8" y2="13" />
            <line x1="3" y1="8" x2="13" y2="8" />
          </svg>
          Nova Oportunidade
        </button>
      </div>

      <DealKanbanMetrics deals={deals} />
      <DealKanbanFilters search={search} onSearchChange={setSearch} category={category} onCategoryChange={setCategory} showActive={showActive} onToggleActive={() => setShowActive(!showActive)} />

      <DndContext sensors={sensors} collisionDetection={closestCorners} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <div className="flex gap-3 overflow-x-auto pb-4">
          {DEAL_STAGES.map((stage) => {
            const stageDeals = filteredDeals.filter((d) => d.stage === stage.key);
            return (<DroppableColumn key={stage.key} id={stage.key} title={stage.label} dotColor={stage.dotColor} tintColor={stage.tintColor} deals={stageDeals} onDealClick={setSelectedDeal} />);
          })}
        </div>
        <DragOverlay>
          {activeDrag ? (
            <div className="w-[270px] opacity-90 rotate-[2deg] shadow-xl">
              <DealCard deal={activeDrag} onClick={() => {}} />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>

      {selectedDeal && <DealDetailSidebar deal={selectedDeal} onClose={() => setSelectedDeal(null)} onUpdate={handleUpdateDeal} />}
      {showCreate && <DealCreateModal leads={leads} onClose={() => setShowCreate(false)} onCreate={handleCreateDeal} />}
      {lostDeal && <LostReasonModal onConfirm={handleLostConfirm} onCancel={() => setLostDeal(null)} />}
    </div>
  );
}
