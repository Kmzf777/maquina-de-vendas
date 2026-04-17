"use client";

import type { Lead, Tag } from "@/lib/types";
import { getTemperature, TEMPERATURE_CONFIG } from "@/lib/temperature";
import { AGENT_STAGES } from "@/lib/constants";

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "Nunca";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "agora";
  if (mins < 60) return `${mins}min atras`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h atras`;
  const days = Math.floor(hours / 24);
  return `${days}d atras`;
}

interface LeadGridCardProps {
  lead: Lead;
  tags: Tag[];
  onClick: (lead: Lead) => void;
}

export function LeadGridCard({ lead, tags, onClick }: LeadGridCardProps) {
  const temp = getTemperature(lead.last_msg_at);
  const tempConfig = TEMPERATURE_CONFIG[temp];
  const stageInfo = AGENT_STAGES.find((s) => s.key === lead.stage);
  const initials = (lead.name || lead.phone)
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("");

  return (
    <button
      onClick={() => onClick(lead)}
      className="w-full text-left bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 hover:border-[#111111] transition-colors cursor-pointer"
    >
      {/* Header: Avatar + Name + Temp Badge */}
      <div className="flex justify-between items-start mb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-10 h-10 rounded-full bg-[#111111] flex items-center justify-center font-semibold text-sm text-white">
            {initials}
          </div>
          <div>
            <p className="text-[14px] font-medium text-[#111111]">
              {lead.name || lead.phone}
            </p>
            <p className="text-[12px] text-[#7b7b78]">{lead.phone}</p>
          </div>
        </div>
        <span
          className="text-[10px] font-semibold px-2 py-0.5 rounded-[4px]"
          style={{ background: tempConfig.bg, color: tempConfig.color }}
        >
          {tempConfig.label.toUpperCase()}
        </span>
      </div>

      {/* Tags */}
      <div className="flex gap-1.5 flex-wrap mb-2.5">
        {stageInfo && (
          <span className="bg-white border border-[#dedbd6] px-2 py-0.5 rounded-[4px] text-[11px] text-[#7b7b78]">
            {stageInfo.label}
          </span>
        )}
        {tags.slice(0, 2).map((tag) => (
          <span
            key={tag.id}
            className="px-2 py-0.5 rounded-[4px] text-[11px] font-medium"
            style={{ backgroundColor: tag.color + "20", color: tag.color }}
          >
            {tag.name}
          </span>
        ))}
        {tags.length > 2 && (
          <span className="text-[11px] text-[#7b7b78]">+{tags.length - 2}</span>
        )}
      </div>

      {/* Company */}
      <div className="text-[12px] text-[#7b7b78]">
        <span>{lead.company || lead.razao_social || "\u2014"}</span>
      </div>

      {/* Footer */}
      <div className="flex justify-between text-[11px] text-[#7b7b78] mt-2 pt-2 border-t border-[#dedbd6]">
        <span>
          {stageInfo?.label || lead.stage}
        </span>
        <span>Ultima msg: {timeAgo(lead.last_msg_at)}</span>
      </div>
    </button>
  );
}
