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
    <div className="flex gap-3.5 mb-5">
      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Total no funil
        </p>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {leads.length}
          </span>
          <span className="text-[12px] text-[#9ca3af]">leads</span>
        </div>
      </div>

      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Novos hoje / ontem
        </p>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {leadsToday}
          </span>
          <span className="text-[12px] text-[#9ca3af]">/ {leadsYesterday}</span>
        </div>
        {leadsToday > leadsYesterday && (
          <p className="text-[11px] text-[#5aad65] mt-1.5">{"\u2191"} crescendo</p>
        )}
        {leadsToday <= leadsYesterday && leadsToday > 0 && (
          <p className="text-[11px] text-[#9ca3af] mt-1.5">{"\u2192"} estavel</p>
        )}
        {leadsToday === 0 && (
          <p className="text-[11px] text-[#9ca3af] mt-1.5">nenhum hoje</p>
        )}
      </div>

      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Tempo medio resp.
        </p>
        <div className="mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {responseStr}
          </span>
        </div>
        <p className="text-[11px] text-[#c8cc8e] mt-1.5">agente IA</p>
      </div>
    </div>
  );
}
