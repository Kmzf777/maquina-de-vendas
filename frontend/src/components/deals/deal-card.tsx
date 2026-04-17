import type { Deal } from "@/lib/types";
import { DEAL_CATEGORIES } from "@/lib/constants";

function formatCurrency(value: number): string {
  if (value === 0) return "";
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
}

function daysInStage(updatedAt: string): number {
  return Math.floor((Date.now() - new Date(updatedAt).getTime()) / (1000 * 60 * 60 * 24));
}

interface DealCardProps {
  deal: Deal;
  onClick: (deal: Deal) => void;
}

export function DealCard({ deal, onClick }: DealCardProps) {
  const lead = deal.leads;
  const displayName = lead?.name || lead?.company || lead?.nome_fantasia || lead?.phone || "—";
  const initial = displayName[0]?.toUpperCase() || "?";
  const categoryInfo = DEAL_CATEGORIES.find((c) => c.key === deal.category);
  const days = daysInStage(deal.updated_at);
  const assignedInitial = deal.assigned_to?.[0]?.toUpperCase();

  return (
    <button
      onClick={() => onClick(deal)}
      className="bg-white border border-[#dedbd6] rounded-[8px] p-3 mx-2 mb-2 cursor-pointer hover:border-[#111111] transition-colors w-[calc(100%-16px)] text-left"
    >
      <div className="flex items-start justify-between mb-2">
        <p className="text-[13px] font-normal text-[#111111] truncate flex-1">{deal.title}</p>
        {deal.value > 0 && (
          <span className="text-[12px] text-[#7b7b78] ml-2 flex-shrink-0">
            {formatCurrency(deal.value)}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 mb-2">
        <div className="w-6 h-6 rounded-full bg-[#dedbd6] flex items-center justify-center text-[10px] font-normal text-[#111111] flex-shrink-0">
          {initial}
        </div>
        <span className="text-[12px] text-[#7b7b78] truncate">{displayName}</span>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
        {categoryInfo && (
          <span
            className="text-[9px] px-2 py-0.5 rounded-[4px] uppercase tracking-[0.4px]"
            style={{ backgroundColor: categoryInfo.color + "22", color: categoryInfo.color }}
          >
            {categoryInfo.label}
          </span>
        )}
        {days > 0 && (
          <span className={`text-[9px] px-2 py-0.5 rounded-[4px] ${days > 7 ? "bg-[#fee2e2] text-[#991b1b]" : "bg-[#faf9f6] text-[#7b7b78] border border-[#dedbd6]"}`}>
            {days}d
          </span>
        )}
        {assignedInitial && (
          <span className="ml-auto w-5 h-5 rounded-[4px] bg-[#faf9f6] border border-[#dedbd6] flex items-center justify-center text-[9px] text-[#111111]">
            {assignedInitial}
          </span>
        )}
      </div>
    </button>
  );
}
