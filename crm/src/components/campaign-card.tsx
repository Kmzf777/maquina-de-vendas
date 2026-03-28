"use client";

import Link from "next/link";
import type { Campaign } from "@/lib/types";
import { CAMPAIGN_STATUS_COLORS } from "@/lib/constants";

const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

interface CampaignCardProps {
  campaign: Campaign;
}

export function CampaignCard({ campaign: c }: CampaignCardProps) {
  const totalCadence = (c.cadence_responded || 0) + (c.cadence_exhausted || 0) + (c.cadence_cooled || 0);
  const activeCadence = c.sent - totalCadence;
  const total = c.total_leads || 1;

  const respondedPct = ((c.cadence_responded || 0) / total) * 100;
  const activePct = (Math.max(0, activeCadence) / total) * 100;
  const exhaustedPct = ((c.cadence_exhausted || 0) / total) * 100;
  const cooledPct = ((c.cadence_cooled || 0) / total) * 100;

  async function handleAction(action: "start" | "pause") {
    await fetch(`${FASTAPI_URL}/api/campaigns/${c.id}/${action}`, {
      method: "POST",
    });
  }

  return (
    <div className="card card-hover p-6">
      {/* Top row: name + status + actions */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <h3 className="text-[16px] font-semibold text-[#1f1f1f]">{c.name}</h3>
          <span
            className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-medium ${
              CAMPAIGN_STATUS_COLORS[c.status] || ""
            }`}
          >
            {c.status}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {(c.status === "draft" || c.status === "paused") && (
            <button
              onClick={() => handleAction("start")}
              className="btn-primary px-4 py-1.5 text-[12px] rounded-lg"
            >
              Iniciar
            </button>
          )}
          {c.status === "running" && (
            <button
              onClick={() => handleAction("pause")}
              className="btn-secondary px-4 py-1.5 text-[12px] rounded-lg"
            >
              Pausar
            </button>
          )}
          <Link
            href={`/campanhas/${c.id}`}
            className="btn-secondary px-4 py-1.5 text-[12px] rounded-lg inline-flex items-center gap-1"
          >
            Abrir <span aria-hidden>&rarr;</span>
          </Link>
        </div>
      </div>

      {/* Meta row */}
      <div className="flex items-center gap-4 mb-5 text-[12px] text-[#5f6368]">
        <span>Template: <strong className="text-[#1f1f1f]">{c.template_name}</strong></span>
        <span>Criada em: {new Date(c.created_at).toLocaleDateString("pt-BR")}</span>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-6 gap-4 mb-5">
        <MetricCell label="Total Leads" value={c.total_leads} />
        <MetricCell label="Templates Enviados" value={c.sent} />
        <MetricCell label="Responderam" value={c.cadence_responded || 0} valueColor="#4ade80" />
        <MetricCell label="Em Cadencia" value={Math.max(0, activeCadence)} valueColor="#f59e0b" />
        <MetricCell label="Esgotados" value={c.cadence_exhausted || 0} valueColor="#f87171" />
        <MetricCell label="Esfriados" value={c.cadence_cooled || 0} valueColor="#9ca3af" />
      </div>

      {/* Segmented progress bar */}
      <div className="w-full h-2.5 bg-[#e5e5dc] rounded-full overflow-hidden flex mb-3">
        {respondedPct > 0 && (
          <div className="h-full bg-[#4ade80]" style={{ width: `${respondedPct}%` }} />
        )}
        {activePct > 0 && (
          <div className="h-full bg-[#f59e0b]" style={{ width: `${activePct}%` }} />
        )}
        {exhaustedPct > 0 && (
          <div className="h-full bg-[#f87171]" style={{ width: `${exhaustedPct}%` }} />
        )}
        {cooledPct > 0 && (
          <div className="h-full bg-[#9ca3af]" style={{ width: `${cooledPct}%` }} />
        )}
      </div>

      {/* Config tags */}
      <div className="flex items-center gap-2 text-[11px] text-[#5f6368]">
        <span className="px-2 py-0.5 rounded-md bg-[#f4f4f0]">
          Intervalo: {c.cadence_interval_hours || 24}h
        </span>
        <span className="px-2 py-0.5 rounded-md bg-[#f4f4f0]">
          Janela: {c.cadence_send_start_hour || 7}h-{c.cadence_send_end_hour || 18}h
        </span>
        <span className="px-2 py-0.5 rounded-md bg-[#f4f4f0]">
          Max: {c.cadence_max_messages || 8} msgs
        </span>
      </div>
    </div>
  );
}

function MetricCell({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: number;
  valueColor?: string;
}) {
  return (
    <div>
      <p className="text-[10px] font-medium uppercase tracking-wider text-[#9ca3af] mb-1">
        {label}
      </p>
      <p
        className="text-[20px] font-bold"
        style={{ color: valueColor || "#1f1f1f" }}
      >
        {value}
      </p>
    </div>
  );
}
