interface DaySeparatorProps {
  date: Date;
}

function formatDayLabel(date: Date): string {
  const now = new Date();
  const isToday =
    date.getDate() === now.getDate() &&
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear();
  if (isToday) return "Hoje";

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday =
    date.getDate() === yesterday.getDate() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getFullYear() === yesterday.getFullYear();
  if (isYesterday) return "Ontem";

  if (date.getFullYear() === now.getFullYear()) {
    return date.toLocaleDateString("pt-BR", { day: "numeric", month: "long" });
  }
  return date.toLocaleDateString("pt-BR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function DaySeparator({ date }: DaySeparatorProps) {
  return (
    <div className="flex items-center gap-3 my-4 px-2">
      <div className="flex-1 h-px bg-[#dedbd6]" />
      <span className="text-[11px] text-[#9b9b98] px-2 py-0.5 rounded-full bg-[#f0ede8] whitespace-nowrap">
        {formatDayLabel(date)}
      </span>
      <div className="flex-1 h-px bg-[#dedbd6]" />
    </div>
  );
}
