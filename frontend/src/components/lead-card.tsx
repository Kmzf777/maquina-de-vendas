import type { Lead, Tag } from "@/lib/types";
import { getTemperature } from "@/lib/temperature";

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "agora";
  if (mins < 60) return `${mins}min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

interface LeadCardProps {
  lead: Lead;
  onClick: (lead: Lead) => void;
  showAgentStage?: boolean;
  unreadCount?: number;
  tags?: Tag[];
  lastMessage?: string | null;
  avatarColor?: string;
}

export function LeadCard({
  lead,
  onClick,
  showAgentStage,
  unreadCount,
  tags,
  lastMessage,
}: LeadCardProps) {
  const initial = (lead.name || lead.phone)?.[0]?.toUpperCase() || "?";
  const temp = getTemperature(lead.last_msg_at);
  const tempDotColor = temp === "quente" ? "#0bdf50" : temp === "morno" ? "#ff5600" : "#65b5ff";

  return (
    <button
      onClick={() => onClick(lead)}
      className="w-full text-left bg-white border border-[#dedbd6] rounded-[8px] p-4 hover:border-[#111111] transition-colors cursor-pointer"
    >
      {/* Row 1: Avatar + Name + Time */}
      <div className="flex items-center gap-2.5 mb-2">
        <div className="w-[34px] h-[34px] rounded-full bg-[#111111] flex items-center justify-center text-[13px] font-semibold text-white flex-shrink-0">
          {initial}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 min-w-0">
              <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: tempDotColor }} />
              <span className="text-[15px] font-medium text-[#111111] truncate">
                {lead.name || lead.phone}
              </span>
            </div>
            <div className="flex items-center gap-1.5 flex-shrink-0 ml-2">
              {unreadCount && unreadCount > 0 ? (
                <span className="bg-[#111111] text-white text-[10px] font-semibold rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
                  {unreadCount}
                </span>
              ) : null}
              <span className="text-[10px] text-[#7b7b78]">
                {timeAgo(lead.last_msg_at)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Row 2: Tags */}
      {tags && tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          {tags.slice(0, 3).map((tag) => (
            <span
              key={tag.id}
              className="text-[9px] font-medium px-2 py-0.5 rounded-[4px] border"
              style={{ borderColor: tag.color + "44", color: tag.color, backgroundColor: tag.color + "15" }}
            >
              {tag.name}
            </span>
          ))}
          {showAgentStage && (
            <span className="text-[9px] font-medium text-[#7b7b78] bg-[#faf9f6] border border-[#dedbd6] px-2 py-0.5 rounded-[4px]">
              {lead.stage}
            </span>
          )}
          {tags.length > 3 && (
            <span className="text-[9px] text-[#7b7b78]">+{tags.length - 3}</span>
          )}
        </div>
      )}
      {/* Show agent stage even without tags */}
      {showAgentStage && (!tags || tags.length === 0) && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          <span className="text-[9px] font-medium text-[#7b7b78] bg-[#faf9f6] border border-[#dedbd6] px-2 py-0.5 rounded-[4px]">
            {lead.stage}
          </span>
        </div>
      )}

      {/* Row 3: Last message preview */}
      {lastMessage && (
        <p className="text-[11px] text-[#7b7b78] truncate">
          &ldquo;{lastMessage}&rdquo;
        </p>
      )}
    </button>
  );
}
