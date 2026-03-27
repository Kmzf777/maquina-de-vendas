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

function daysInStage(enteredAt: string | null): number | null {
  if (!enteredAt) return null;
  const diff = Date.now() - new Date(enteredAt).getTime();
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

function formatCurrency(value: number): string {
  if (value === 0) return "";
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
}

interface LeadCardProps {
  lead: Lead;
  onClick: (lead: Lead) => void;
  showAgentStage?: boolean;
  unreadCount?: number;
  tags?: Tag[];
  lastMessage?: string | null;
}

export function LeadCard({ lead, onClick, showAgentStage, unreadCount, tags, lastMessage }: LeadCardProps) {
  const days = daysInStage(lead.entered_stage_at);
  const isStale = days !== null && days > 30;
  const currencyStr = formatCurrency(lead.sale_value);

  return (
    <button
      onClick={() => onClick(lead)}
      className="card card-hover w-full text-left rounded-xl border border-[#e5e5dc] bg-white p-3.5 transition-all duration-200 hover:-translate-y-[1px] hover:shadow-md"
    >
      {/* Row 1: Name + unread badge */}
      <div className="flex items-center justify-between mb-1">
        <span className="text-[13px] font-semibold text-[#1f1f1f] truncate">
          {lead.name || lead.phone}
        </span>
        {unreadCount && unreadCount > 0 ? (
          <span className="bg-[#e8d44d] text-[#1f1f1f] text-[10px] font-semibold rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
            {unreadCount}
          </span>
        ) : null}
      </div>

      {/* Row 2: Company / nome fantasia */}
      {(lead.nome_fantasia || lead.company) && (
        <p className="text-[11px] text-[#5f6368] truncate mb-1.5">
          {lead.nome_fantasia || lead.company}
        </p>
      )}

      {/* Row 3: Value badge + days in stage */}
      <div className="flex items-center gap-2 mb-2">
        {currencyStr && (
          <span className="text-[11px] font-medium text-[#2d6a3f] bg-[#d8f0dc] px-2 py-0.5 rounded-full">
            {currencyStr}
          </span>
        )}
        {days !== null && (
          <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${
            isStale
              ? "text-[#a33] bg-[#f0d8d8]"
              : "text-[#5f6368] bg-[#f4f4f0]"
          }`}>
            {days}d
          </span>
        )}
        {showAgentStage && (
          <span className="text-[11px] text-[#5f6368] bg-[#f4f4f0] px-2 py-0.5 rounded-full">
            {lead.stage}
          </span>
        )}
      </div>

      {/* Row 4: Tags */}
      {tags && tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {tags.slice(0, 3).map((tag) => (
            <span
              key={tag.id}
              className="text-[10px] font-medium text-white px-1.5 py-0.5 rounded-full"
              style={{ backgroundColor: tag.color }}
            >
              {tag.name}
            </span>
          ))}
          {tags.length > 3 && (
            <span className="text-[10px] text-[#9ca3af]">+{tags.length - 3}</span>
          )}
        </div>
      )}

      {/* Row 5: Last message preview */}
      {lastMessage && (
        <p className="text-[11px] text-[#9ca3af] truncate mb-2 italic">
          {lastMessage}
        </p>
      )}

      {/* Row 6: Time info */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-[#9ca3af]">
          {lead.phone}
        </span>
        <span className="text-[10px] text-[#9ca3af]">
          {timeAgo(lead.last_msg_at)}
        </span>
      </div>
    </button>
  );
}
