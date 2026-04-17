import type { Lead } from "@/lib/types";

interface KanbanMetricsBarProps {
  leads: Lead[];
}

export function KanbanMetricsBar({ leads }: KanbanMetricsBarProps) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const leadsToday = leads.filter((l) => new Date(l.created_at) >= today).length;
  const leadsYesterday = leads.filter((l) => {
    const d = new Date(l.created_at);
    return d >= yesterday && d < today;
  }).length;

  const withResponse = leads.filter((l) => l.first_response_at);
  const avgResponseMs =
    withResponse.length > 0
      ? withResponse.reduce(
          (sum, l) =>
            sum + (new Date(l.first_response_at!).getTime() - new Date(l.created_at).getTime()),
          0
        ) / withResponse.length
      : 0;
  const avgResponseMin = Math.round(avgResponseMs / 60000);
  const responseStr = avgResponseMin > 0 ? `${avgResponseMin}m` : "\u2014";

  return (
    <div className="bg-[#f7f5f1] border-b border-[#dedbd6] px-6 py-3 flex gap-8 flex-shrink-0">
      <div className="flex flex-col">
        <span style={{ letterSpacing: '-0.3px' }} className="text-[20px] font-normal text-[#111111]">
          {leads.length}
        </span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Total no funil</span>
      </div>

      <div className="flex flex-col">
        <span style={{ letterSpacing: '-0.3px' }} className="text-[20px] font-normal text-[#111111]">
          {leadsToday} / {leadsYesterday}
        </span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Novos hoje / ontem</span>
      </div>

      <div className="flex flex-col">
        <span style={{ letterSpacing: '-0.3px' }} className="text-[20px] font-normal text-[#111111]">
          {responseStr}
        </span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Tempo medio resp.</span>
      </div>
    </div>
  );
}
