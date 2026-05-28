"use client";

import { LP_ORIGINS } from "@/lib/constants";
import type { Lead } from "@/lib/types";

interface LeadSourcesChartProps {
  leads: Lead[];
}

const UNIDENTIFIED_COLOR = "#b3b3b0";

export function LeadSourcesChart({ leads }: LeadSourcesChartProps) {
  const knownKeys = new Set(LP_ORIGINS.map((o) => o.key));

  const counts: { key: string; label: string; color: string; count: number }[] = LP_ORIGINS.map((o) => ({
    key: o.key,
    label: o.label,
    color: o.color,
    count: leads.filter((l) => (l.metadata as Record<string, unknown> | null)?.["origem"] === o.key).length,
  }));

  const unidentifiedCount = leads.filter((l) => {
    const origem = (l.metadata as Record<string, unknown> | null)?.["origem"];
    return !origem || !knownKeys.has(origem as string);
  }).length;

  if (unidentifiedCount > 0) {
    counts.push({ key: "nao_identificado", label: "Não identificado", color: UNIDENTIFIED_COLOR, count: unidentifiedCount });
  }

  const total = counts.reduce((sum, c) => sum + c.count, 0);
  if (total === 0) {
    return (
      <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
        <h3
          className="text-[18px] font-medium text-[#111111] mb-4"
          style={{ letterSpacing: "-0.3px" }}
        >
          Origens de Lead
        </h3>
        <p className="text-[#7b7b78] text-sm text-center py-8">Sem dados</p>
      </div>
    );
  }

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
      const seg = { ...c, pct, dashLen, dashOffset: -offset };
      offset += dashLen;
      return seg;
    });

  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
      <h3
        className="text-[18px] font-medium text-[#111111] mb-4"
        style={{ letterSpacing: "-0.3px" }}
      >
        Origens de Lead
      </h3>
      <div className="flex flex-col md:flex-row items-center gap-4 md:gap-6">
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
          <text
            x={cx}
            y={cy - 6}
            textAnchor="middle"
            fontSize="24"
            fontWeight="400"
            fill="#111111"
            style={{ letterSpacing: "-0.96px" }}
          >
            {total}
          </text>
          <text x={cx} y={cy + 14} textAnchor="middle" fontSize="11" fill="#7b7b78">
            leads
          </text>
        </svg>
        <div className="space-y-2">
          {segments.map((seg) => (
            <div key={seg.key} className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: seg.color }} />
              <span className="text-[13px] text-[#111111]">{seg.label}</span>
              <span className="text-[13px] font-normal text-[#111111]">{seg.count}</span>
              <span className="text-[11px] text-[#7b7b78]">{Math.round(seg.pct * 100)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
