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
      className="w-full text-left bg-white rounded-xl p-[18px] border border-[#e5e5dc] cursor-pointer transition-all duration-150 hover:-translate-y-[2px] hover:shadow-[0_8px_24px_rgba(0,0,0,0.08)]"
      style={{ borderLeft: `4px solid ${tempConfig.borderColor}` }}
    >
      {/* Header: Avatar + Name + Temp Badge */}
      <div className="flex justify-between items-start mb-3">
        <div className="flex items-center gap-2.5">
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center font-semibold text-sm"
            style={{ background: stageInfo?.avatarColor || "#c8cc8e", color: "#1f1f1f" }}
          >
            {initials}
          </div>
          <div>
            <p className="text-[14px] font-semibold text-[#1f1f1f]">
              {lead.name || lead.phone}
            </p>
            <p className="text-[12px] text-[#9ca3af]">{lead.phone}</p>
          </div>
        </div>
        <span
          className="text-[10px] font-semibold px-2 py-0.5 rounded-xl"
          style={{ background: tempConfig.bg, color: tempConfig.color }}
        >
          {tempConfig.label.toUpperCase()}
        </span>
      </div>

      {/* Tags */}
      <div className="flex gap-1.5 flex-wrap mb-2.5">
        {stageInfo && (
          <span className="bg-[#f3f4f6] px-2 py-0.5 rounded-[10px] text-[11px] text-[#5f6368]">
            {stageInfo.label}
          </span>
        )}
        {tags.slice(0, 2).map((tag) => (
          <span
            key={tag.id}
            className="px-2 py-0.5 rounded-[10px] text-[11px] font-medium"
            style={{ backgroundColor: tag.color + "22", color: tag.color }}
          >
            {tag.name}
          </span>
        ))}
        {tags.length > 2 && (
          <span className="text-[11px] text-[#9ca3af]">+{tags.length - 2}</span>
        )}
      </div>

      {/* Company */}
      <div className="text-[12px] text-[#9ca3af]">
        <span>{lead.company || lead.razao_social || "\u2014"}</span>
      </div>

      {/* Footer */}
      <div className="flex justify-between text-[11px] text-[#b0b0b0] mt-2 pt-2 border-t border-[#f3f3f0]">
        <span>
          {stageInfo?.label || lead.stage}
        </span>
        <span>Ultima msg: {timeAgo(lead.last_msg_at)}</span>
      </div>
    </button>
  );
}
