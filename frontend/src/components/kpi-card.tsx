import type { ReactNode } from "react";

interface KpiCardProps {
  label: string;
  value: string | number;
  subtitle?: string;
  icon?: ReactNode;
  trend?: string;
  trendPositive?: boolean;
  /** Explicação do número: ícone "i" ao lado do rótulo, com o texto no tooltip (title). */
  hint?: string;
}

export function KpiCard({ label, value, subtitle, icon, trend, trendPositive, hint }: KpiCardProps) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
      <div className="flex items-start justify-between mb-3">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] inline-flex items-center gap-1">
          {label}
          {hint && (
            <span
              className="inline-flex cursor-help normal-case tracking-normal"
              title={hint}
              aria-label={hint}
              role="img"
            >
              <svg width="13" height="13" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.5" />
                <path d="M10 9.2v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <circle cx="10" cy="6.4" r="0.9" fill="currentColor" />
              </svg>
            </span>
          )}
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
