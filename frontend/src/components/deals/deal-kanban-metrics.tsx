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
    <div className="bg-[#faf9f6] border-b border-[#dedbd6] px-6 py-3 flex gap-8 mb-5">
      <div className="flex flex-col">
        <span style={{ letterSpacing: '-0.2px' }} className="text-[20px] font-normal text-[#111111]">{activeDeals.length}</span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Pipeline ativo</span>
        <span className="text-[11px] text-[#7b7b78] mt-0.5">{fmt(pipelineValue)}</span>
      </div>
      <div className="flex flex-col">
        <span style={{ letterSpacing: '-0.2px' }} className="text-[20px] font-normal text-[#111111]">{fmt(wonValue)}</span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Ganho no mes</span>
        <span className="text-[11px] text-[#7b7b78] mt-0.5">{wonThisMonth.length} deals</span>
      </div>
      <div className="flex flex-col">
        <span style={{ letterSpacing: '-0.2px' }} className="text-[20px] font-normal text-[#111111]">{conversionRate}%</span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Taxa de conversao</span>
        <span className="text-[11px] text-[#7b7b78] mt-0.5">{totalWon} de {totalClosed} fechados</span>
      </div>
      <div className="flex flex-col">
        <span style={{ letterSpacing: '-0.2px' }} className="text-[20px] font-normal text-[#111111]">{deals.length}</span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Total de deals</span>
        <span className="text-[11px] text-[#7b7b78] mt-0.5">{fmt(deals.reduce((sum, d) => sum + (d.value || 0), 0))}</span>
      </div>
    </div>
  );
}
