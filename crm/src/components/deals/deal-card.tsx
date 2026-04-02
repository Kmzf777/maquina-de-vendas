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
      className="w-full text-left bg-white rounded-[10px] border border-[#e5e5dc] p-3 transition-all duration-150 hover:-translate-y-[1px] hover:shadow-[0_4px_12px_rgba(0,0,0,0.08)]"
      style={{ boxShadow: "0 2px 8px rgba(0,0,0,0.05)" }}
    >
      <div className="flex items-start justify-between mb-2">
        <p className="text-[13px] font-semibold text-[#1f1f1f] truncate flex-1">{deal.title}</p>
        {deal.value > 0 && (
          <span className="text-[12px] font-bold text-[#2d6a3f] ml-2 flex-shrink-0">
            {formatCurrency(deal.value)}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 mb-2">
        <div className="w-6 h-6 rounded-full bg-[#1f1f1f] flex items-center justify-center text-[10px] font-bold text-[#c8cc8e] flex-shrink-0">
          {initial}
        </div>
        <span className="text-[12px] text-[#5f6368] truncate">{displayName}</span>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
        {categoryInfo && (
          <span
            className="text-[9px] font-medium px-2 py-0.5 rounded-md"
            style={{ backgroundColor: categoryInfo.color + "22", color: categoryInfo.color }}
          >
            {categoryInfo.label}
          </span>
        )}
        {days > 0 && (
          <span className={`text-[9px] px-2 py-0.5 rounded-md ${days > 7 ? "bg-[#fee2e2] text-[#991b1b]" : "bg-[#f4f4f0] text-[#5f6368]"}`}>
            {days}d
          </span>
        )}
        {assignedInitial && (
          <span className="ml-auto w-5 h-5 rounded-full bg-[#c8cc8e] flex items-center justify-center text-[9px] font-bold text-[#1f1f1f]">
            {assignedInitial}
          </span>
        )}
      </div>
    </button>
  );
}
