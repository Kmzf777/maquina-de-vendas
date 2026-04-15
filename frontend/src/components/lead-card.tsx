import type { Lead, Tag } from "@/lib/types";

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
  avatarColor = "#c8cc8e",
}: LeadCardProps) {
  const initial = (lead.name || lead.phone)?.[0]?.toUpperCase() || "?";

  return (
    <button
      onClick={() => onClick(lead)}
      className="w-full text-left bg-white rounded-[10px] border border-[#e5e5dc] p-3 transition-all duration-150 hover:-translate-y-[1px] hover:shadow-[0_4px_12px_rgba(0,0,0,0.08)]"
      style={{ boxShadow: "0 2px 8px rgba(0,0,0,0.05)" }}
    >
      {/* Row 1: Avatar + Name + Time */}
      <div className="flex items-center gap-2.5 mb-2">
        <div
          className="w-[34px] h-[34px] rounded-full bg-[#1f1f1f] flex items-center justify-center text-[13px] font-bold flex-shrink-0"
          style={{ color: avatarColor }}
        >
          {initial}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-semibold text-[#1f1f1f] truncate">
              {lead.name || lead.phone}
            </span>
            <div className="flex items-center gap-1.5 flex-shrink-0 ml-2">
              {unreadCount && unreadCount > 0 ? (
                <span className="bg-[#e8d44d] text-[#1f1f1f] text-[10px] font-semibold rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
                  {unreadCount}
                </span>
              ) : null}
              <span className="text-[10px] text-[#9ca3af]">
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
              className="text-[9px] font-medium px-2 py-0.5 rounded-md"
              style={{ backgroundColor: tag.color + "22", color: tag.color }}
            >
              {tag.name}
            </span>
          ))}
          {showAgentStage && (
            <span className="text-[9px] font-medium text-[#5f6368] bg-[#f4f4f0] px-2 py-0.5 rounded-md">
              {lead.stage}
            </span>
          )}
          {tags.length > 3 && (
            <span className="text-[9px] text-[#9ca3af]">+{tags.length - 3}</span>
          )}
        </div>
      )}
      {/* Show agent stage even without tags */}
      {showAgentStage && (!tags || tags.length === 0) && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          <span className="text-[9px] font-medium text-[#5f6368] bg-[#f4f4f0] px-2 py-0.5 rounded-md">
            {lead.stage}
          </span>
        </div>
      )}

      {/* Row 3: Last message preview */}
      {lastMessage && (
        <p className="text-[11px] text-[#9ca3af] truncate italic">
          &ldquo;{lastMessage}&rdquo;
        </p>
      )}
    </button>
  );
}
