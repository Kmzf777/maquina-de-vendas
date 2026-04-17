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
    <div className="bg-[#f7f5f1] border border-[#dedbd6] rounded-[8px] flex flex-col min-h-[200px] w-72 flex-shrink-0">
      {/* Column header */}
      <div className="px-4 py-3 bg-[#f0ede8] border-b border-[#dedbd6] rounded-t-[8px] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: dotColor }}
          />
          <h3 className="text-[13px] font-medium text-[#111111] uppercase tracking-[0.6px]">{title}</h3>
        </div>
        <span className="text-[12px] text-[#7b7b78] bg-white border border-[#dedbd6] rounded-full px-2 py-0.5">
          {leads.length}
        </span>
      </div>

      {/* Column body */}
      <div className="flex-1 py-2 overflow-y-auto">
        {children}
        {!children && leads.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <p className="text-[12px] text-[#7b7b78] mb-3">Nenhum lead</p>
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
