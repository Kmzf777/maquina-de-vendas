import type { Lead, Tag } from "@/lib/types";
import { LeadCard } from "./lead-card";

interface KanbanColumnProps {
  title: string;
  leads: Lead[];
  dotColor: string;
  tintColor: string;
  avatarColor: string;
  onLeadClick: (lead: Lead) => void;
  showAgentStage?: boolean;
  leadTagsMap?: Record<string, Tag[]>;
  lastMessagesMap?: Record<string, string>;
  children?: React.ReactNode;
  footer?: React.ReactNode;
}

export function KanbanColumn({
  title,
  leads,
  dotColor,
  tintColor,
  avatarColor,
  onLeadClick,
  showAgentStage,
  leadTagsMap,
  lastMessagesMap,
  children,
  footer,
}: KanbanColumnProps) {
  return (
    <div className="flex-shrink-0 w-[270px]">
      {/* Dark header */}
      <div className="bg-[#1f1f1f] rounded-t-xl px-3.5 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: dotColor }}
          />
          <h3 className="text-[12px] font-semibold text-white">{title}</h3>
        </div>
        <span className="text-[10px] font-semibold text-white bg-white/15 rounded-full px-2 py-0.5">
          {leads.length}
        </span>
      </div>

      {/* Tinted body */}
      <div
        className="rounded-b-xl p-2.5 min-h-[calc(100vh-280px)] space-y-2.5 overflow-y-auto"
        style={{ backgroundColor: tintColor }}
      >
        {children}
        {!children && leads.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <p className="text-[12px] text-[#b0adb5] mb-3">Nenhum lead</p>
          </div>
        )}
        {!children &&
          leads.map((lead) => (
            <LeadCard
              key={lead.id}
              lead={lead}
              onClick={onLeadClick}
              showAgentStage={showAgentStage}
              tags={leadTagsMap?.[lead.id]}
              lastMessage={lastMessagesMap?.[lead.id]}
              avatarColor={avatarColor}
            />
          ))}
        {footer}
      </div>
    </div>
  );
}
