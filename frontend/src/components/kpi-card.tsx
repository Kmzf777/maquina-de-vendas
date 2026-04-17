import type { ReactNode } from "react";

interface KpiCardProps {
  label: string;
  value: string | number;
  subtitle?: string;
  icon?: ReactNode;
  trend?: string;
  trendPositive?: boolean;
}

export function KpiCard({ label, value, subtitle, icon, trend, trendPositive }: KpiCardProps) {
  return (
    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4">
      <div className="flex items-start justify-between">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
          {label}
        </p>
        {icon && (
          <span className="text-[18px] text-[#7b7b78] opacity-60">
            {icon}
          </span>
        )}
      </div>
      <div className="flex items-end gap-2 mt-1">
        <p
          className="text-[32px] font-normal leading-none text-[#111111]"
          style={{ letterSpacing: "-0.96px" }}
        >
          {value}
        </p>
        {trend && (
          <span
            className={`text-[13px] font-medium mb-1 ${trendPositive === false ? "text-[#c41c1c]" : "text-[#0bdf50]"}`}
          >
            {trend}
          </span>
        )}
      </div>
      {subtitle && (
        <p className="text-[13px] mt-1 text-[#7b7b78]">
          {subtitle}
        </p>
      )}
    </div>
  );
}
