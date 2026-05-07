"use client";

import { useState, useRef, useEffect } from "react";
import type { Deal, PipelineStage } from "@/lib/types";

interface BulkMoveDealsModalProps {
  deals: Deal[];
  stages: PipelineStage[];
  sourceStageId: string;
  sourceStageName: string;
  onClose: () => void;
  onMove: (dealIds: string[], targetStageId: string) => Promise<void>;
}

export function BulkMoveDealsModal({
  deals,
  stages,
  sourceStageId,
  sourceStageName,
  onClose,
  onMove,
}: BulkMoveDealsModalProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [targetStageId, setTargetStageId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const selectAllRef = useRef<HTMLInputElement>(null);

  const availableStages = stages.filter(
    (s) => s.id !== sourceStageId && !s.is_protected
  );

  const fmt = (v: number) =>
    `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  const allSelected = selected.size === deals.length && deals.length > 0;
  const someSelected = selected.size > 0 && selected.size < deals.length;

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someSelected;
    }
  }, [someSelected]);

  function toggleSelectAll() {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(deals.map((d) => d.id)));
    }
  }

  function toggleDeal(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function handleConfirm() {
    if (!targetStageId || selected.size === 0 || loading) return;
    setLoading(true);
    await onMove([...selected], targetStageId);
    setLoading(false);
    onClose();
  }

  return (
    <div
      className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-[520px] flex flex-col max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-[#dedbd6] flex items-center justify-between flex-shrink-0">
          <div>
            <h3
              className="text-[16px] font-normal text-[#111111]"
              style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}
            >
              Mover deals
            </h3>
            <p className="text-[12px] text-[#7b7b78] mt-0.5">
              De: <span className="text-[#111111]">{sourceStageName}</span>
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-[#7b7b78] hover:text-[#111111] transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="3" x2="13" y2="13" />
              <line x1="13" y1="3" x2="3" y2="13" />
            </svg>
          </button>
        </div>

        {/* Select all bar */}
        <div className="px-6 py-2.5 border-b border-[#dedbd6] flex items-center gap-3 bg-[#faf9f6] flex-shrink-0">
          <input
            ref={selectAllRef}
            type="checkbox"
            checked={allSelected}
            onChange={toggleSelectAll}
            className="w-4 h-4 accent-[#111111] cursor-pointer"
          />
          <span className="text-[13px] text-[#7b7b78]">
            {allSelected ? "Desmarcar todos" : "Selecionar todos"}
          </span>
        </div>

        {/* Deal list */}
        <div className="overflow-y-auto flex-1 py-1">
          {deals.length === 0 && (
            <div className="flex items-center justify-center py-12">
              <p className="text-[13px] text-[#7b7b78]">Nenhum deal nesta coluna</p>
            </div>
          )}
          {deals.map((deal) => (
            <label
              key={deal.id}
              className="flex items-center gap-3 px-6 py-2.5 hover:bg-[#faf9f6] cursor-pointer border-b border-[#dedbd6]/50 last:border-0"
            >
              <input
                type="checkbox"
                checked={selected.has(deal.id)}
                onChange={() => toggleDeal(deal.id)}
                className="w-4 h-4 accent-[#111111] cursor-pointer flex-shrink-0"
              />
              <span className="text-[13px] text-[#111111] flex-1 truncate">
                {deal.title}
              </span>
              {deal.leads?.name && (
                <span className="text-[12px] text-[#7b7b78] truncate max-w-[120px]">
                  {deal.leads.name}
                </span>
              )}
              {deal.value > 0 && (
                <span className="text-[12px] text-[#7b7b78] flex-shrink-0 font-mono">
                  {fmt(deal.value)}
                </span>
              )}
            </label>
          ))}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[#dedbd6] flex-shrink-0 bg-[#faf9f6]">
          <div className="flex items-center gap-3">
            <span className="text-[13px] text-[#7b7b78] flex-shrink-0">
              {selected.size} deal{selected.size !== 1 ? "s" : ""} selecionado{selected.size !== 1 ? "s" : ""}
            </span>
            <select
              value={targetStageId ?? ""}
              onChange={(e) => setTargetStageId(e.target.value || null)}
              className="flex-1 bg-white border border-[#dedbd6] rounded-[4px] px-3 py-1.5 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
            >
              <option value="">Selecionar destino...</option>
              {availableStages.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2 mt-3 justify-end">
            <button
              onClick={onClose}
              className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors"
            >
              Cancelar
            </button>
            <button
              onClick={handleConfirm}
              disabled={selected.size === 0 || !targetStageId || loading}
              className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[13px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
            >
              {loading ? "Movendo..." : "Mover deals"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
