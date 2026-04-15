"use client";

import { LEAD_CHANNELS } from "@/lib/constants";
import type { Lead } from "@/lib/types";

interface LeadSourcesChartProps {
  leads: Lead[];
}

export function LeadSourcesChart({ leads }: LeadSourcesChartProps) {
  const counts: { key: string; label: string; color: string; count: number }[] = LEAD_CHANNELS.map((ch) => ({
    ...ch,
    count: leads.filter((l) => l.channel === ch.key).length,
  }));

  // Add "Outros" for unmatched channels
  const knownKeys: Set<string> = new Set(LEAD_CHANNELS.map((c) => c.key));
  const othersCount = leads.filter((l) => !knownKeys.has(l.channel as string)).length;
  if (othersCount > 0) {
    counts.push({ key: "outros", label: "Outros", color: "#8a8a80", count: othersCount });
  }

  const total = counts.reduce((sum, c) => sum + c.count, 0);
  if (total === 0) {
    return (
      <div className="card p-5">
        <h3 className="text-[13px] font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
          Fontes de Lead
        </h3>
        <p className="text-[#9ca3af] text-sm text-center py-8">Sem dados</p>
      </div>
    );
  }

  // Build SVG donut segments
  const radius = 70;
  const cx = 90;
  const cy = 90;
  const strokeWidth = 28;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  const segments = counts
    .filter((c) => c.count > 0)
    .map((c) => {
      const pct = c.count / total;
      const dashLen = pct * circumference;
      const seg = {
        ...c,
        pct,
        dashLen,
        dashOffset: -offset,
      };
      offset += dashLen;
      return seg;
    });

  return (
    <div className="card p-5">
      <h3 className="text-[13px] font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
        Fontes de Lead
      </h3>
      <div className="flex items-center gap-6">
        <svg width={180} height={180} viewBox="0 0 180 180">
          {segments.map((seg) => (
            <circle
              key={seg.key}
              cx={cx}
              cy={cy}
              r={radius}
              fill="none"
              stroke={seg.color}
              strokeWidth={strokeWidth}
              strokeDasharray={`${seg.dashLen} ${circumference - seg.dashLen}`}
              strokeDashoffset={seg.dashOffset}
              transform={`rotate(-90 ${cx} ${cy})`}
            />
          ))}
          <text x={cx} y={cy - 6} textAnchor="middle" className="text-[24px] font-bold" fill="#1f1f1f">
            {total}
          </text>
          <text x={cx} y={cy + 14} textAnchor="middle" className="text-[11px]" fill="#9ca3af">
            leads
          </text>
        </svg>
        <div className="space-y-2">
          {segments.map((seg) => (
            <div key={seg.key} className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: seg.color }} />
              <span className="text-[13px] text-[#1f1f1f]">{seg.label}</span>
              <span className="text-[13px] font-bold text-[#1f1f1f]">{seg.count}</span>
              <span className="text-[11px] text-[#9ca3af]">{Math.round(seg.pct * 100)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
