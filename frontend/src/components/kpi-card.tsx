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
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
      <div className="flex items-start justify-between mb-3">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
          {label}
        </p>
        {icon && (
          <span className="text-[18px] text-[#7b7b78] opacity-60">
            {icon}
          </span>
        )}
      </div>
      <p
        className="text-[48px] font-normal leading-none text-[#111111]"
        style={{ letterSpacing: "-1.5px" }}
      >
        {value}
      </p>
      {trend && (
        <p
          className={`text-[13px] mt-2 ${trendPositive === false ? "text-[#c41c1c]" : "text-[#0bdf50]"}`}
        >
          {trend}
        </p>
      )}
      {subtitle && (
        <p className="text-[13px] mt-2 text-[#7b7b78]">
          {subtitle}
        </p>
      )}
    </div>
  );
}
