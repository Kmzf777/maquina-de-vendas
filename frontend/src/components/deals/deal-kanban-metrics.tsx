import type { Deal } from "@/lib/types";

interface DealKanbanMetricsProps {
  deals: Deal[];
}

export function DealKanbanMetrics({ deals }: DealKanbanMetricsProps) {
  const activeDeals = deals.filter(
    (d) => d.stage !== "fechado_ganho" && d.stage !== "fechado_perdido"
  );
  const pipelineValue = activeDeals.reduce((sum, d) => sum + (d.value || 0), 0);

  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const wonThisMonth = deals.filter(
    (d) => d.stage === "fechado_ganho" && d.closed_at && new Date(d.closed_at) >= monthStart
  );
  const wonValue = wonThisMonth.reduce((sum, d) => sum + (d.value || 0), 0);

  const totalClosed = deals.filter(
    (d) => d.stage === "fechado_ganho" || d.stage === "fechado_perdido"
  ).length;
  const totalWon = deals.filter((d) => d.stage === "fechado_ganho").length;
  const conversionRate = totalClosed > 0 ? Math.round((totalWon / totalClosed) * 100) : 0;

  const fmt = (v: number) =>
    `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  return (
    <div className="flex gap-3.5 mb-5">
      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">Pipeline ativo</p>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="text-[24px] font-bold text-white leading-none">{activeDeals.length}</span>
          <span className="text-[12px] text-[#9ca3af]">deals</span>
        </div>
        <p className="text-[11px] text-[#c8cc8e] mt-1.5">{fmt(pipelineValue)}</p>
      </div>
      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">Ganho no mes</p>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="text-[24px] font-bold text-[#5aad65] leading-none">{fmt(wonValue)}</span>
        </div>
        <p className="text-[11px] text-[#9ca3af] mt-1.5">{wonThisMonth.length} deals</p>
      </div>
      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">Taxa de conversao</p>
        <div className="mt-1">
          <span className="text-[24px] font-bold text-white leading-none">{conversionRate}%</span>
        </div>
        <p className="text-[11px] text-[#9ca3af] mt-1.5">{totalWon} de {totalClosed} fechados</p>
      </div>
      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">Total de deals</p>
        <div className="mt-1">
          <span className="text-[24px] font-bold text-white leading-none">{deals.length}</span>
        </div>
        <p className="text-[11px] text-[#c8cc8e] mt-1.5">
          {fmt(deals.reduce((sum, d) => sum + (d.value || 0), 0))} total
        </p>
      </div>
    </div>
  );
}
