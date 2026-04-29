import { formatDayLabel } from "@/lib/datetime";

interface DaySeparatorProps {
  date: Date;
}

export function DaySeparator({ date }: DaySeparatorProps) {
  return (
    <div className="flex items-center gap-3 my-4 px-2">
      <div className="flex-1 h-px bg-[#dedbd6]" />
      <span className="text-[11px] text-[#9b9b98] px-2 py-0.5 rounded-full bg-[#f0ede8] whitespace-nowrap">
        {formatDayLabel(date.toISOString())}
      </span>
      <div className="flex-1 h-px bg-[#dedbd6]" />
    </div>
  );
}
