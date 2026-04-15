import type { ReactNode } from "react";

interface KpiCardProps {
  label: string;
  value: string | number;
  subtitle?: string;
  icon?: ReactNode;
  trend?: string;
}

export function KpiCard({ label, value, subtitle, icon, trend }: KpiCardProps) {
  return (
    <div className="card group relative p-5 overflow-hidden">
      <div className="flex items-start justify-between">
        <p
          className="text-[13px] font-medium"
          style={{ color: "var(--text-secondary)" }}
        >
          {label}
        </p>
        {icon && (
          <span
            className="text-[18px] opacity-60"
            style={{ color: "var(--text-secondary)" }}
          >
            {icon}
          </span>
        )}
      </div>
      <div className="flex items-end gap-2 mt-2">
        <p
          className="text-[32px] font-bold tracking-tight leading-none"
          style={{ color: "var(--text-primary)" }}
        >
          {value}
        </p>
        {trend && (
          <span
            className="text-[13px] font-medium mb-1"
            style={{ color: "#6b8e5a" }}
          >
            {trend}
          </span>
        )}
      </div>
      {subtitle && (
        <p className="text-[13px] font-medium mt-1" style={{ color: "var(--text-secondary)" }}>
          {subtitle}
        </p>
      )}
      <div
        className="absolute bottom-0 left-4 right-4 h-[4px] rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300"
        style={{ backgroundColor: "var(--accent-olive)" }}
      />
    </div>
  );
}
