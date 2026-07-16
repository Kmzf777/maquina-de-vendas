"use client";

import { fmtInt } from "./format";

export interface FunnelStage {
  label: string;
  count: number;
  /** Texto da taxa de conversão a partir do estágio anterior (exibido entre as barras). */
  rateFromPrev?: string;
}

/**
 * Funil horizontal de estágios: barra única (tom de tinta do design system)
 * proporcional ao maior estágio, com contagem direta ao lado do rótulo e a
 * taxa de conversão entre estágios. Tailwind puro — sem Recharts.
 */
export function FunnelBars({ stages }: { stages: FunnelStage[] }) {
  const max = Math.max(...stages.map((s) => s.count), 1);

  return (
    <div>
      {stages.map((stage, i) => {
        const pctWidth = (stage.count / max) * 100;
        // Barra some por completo só quando o valor é zero; valores pequenos
        // mantêm uma lasca visível para não parecer dado ausente.
        const width = stage.count > 0 ? Math.max(pctWidth, 1.5) : 0;
        return (
          <div key={stage.label}>
            {i > 0 && (
              <div className="flex items-center gap-1.5 py-2 pl-0.5 text-[12px] text-[#7b7b78]">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                  <path
                    d="M6 1.5v9M2.5 7.5L6 10.5l3.5-3"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <span>{stage.rateFromPrev ?? "—"}</span>
              </div>
            )}
            <div
              className="flex items-baseline justify-between gap-3"
              title={`${stage.label}: ${fmtInt(stage.count)}`}
            >
              <span className="text-[13px] text-[#111111]">{stage.label}</span>
              <span
                className="text-[22px] font-normal leading-none text-[#111111]"
                style={{ letterSpacing: "-0.5px" }}
              >
                {fmtInt(stage.count)}
              </span>
            </div>
            <div className="mt-1.5 h-[10px] rounded-[4px] bg-[#f0ede8] overflow-hidden">
              <div
                className="h-full rounded-[4px] bg-[#111111] transition-[width] duration-300"
                style={{ width: `${width}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
