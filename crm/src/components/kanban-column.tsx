import type { Lead } from "@/lib/types";
import { LeadCard } from "./lead-card";
import type { Tag } from "@/lib/types";

interface KanbanColumnProps {
  title: string;
  leads: Lead[];
  colorClass: string;
  onLeadClick: (lead: Lead) => void;
  showAgentStage?: boolean;
  id?: string;
  tags?: Tag[];
  leadTagsMap?: Record<string, Tag[]>;
  lastMessagesMap?: Record<string, string>;
  children?: React.ReactNode;
  footer?: React.ReactNode;
}

export function KanbanColumn({
  title,
  leads,
  colorClass,
  onLeadClick,
  showAgentStage,
  tags,
  leadTagsMap,
  lastMessagesMap,
  children,
  footer,
}: KanbanColumnProps) {
  const totalValue = leads.reduce((sum, l) => sum + (l.sale_value || 0), 0);
  const valueStr = totalValue > 0
    ? `R$ ${totalValue.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`
    : null;

  return (
    <div className="flex-shrink-0 w-[280px]">
      <div className="px-3 py-3 mb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`w-2.5 h-2.5 rounded-full ${colorClass}`} />
            <h3 className="text-[14px] font-semibold text-[#1f1f1f]">
              {title}
            </h3>
          </div>
          <span className="text-[12px] font-medium text-[#5f6368] border border-[#e5e5dc] rounded-full px-2.5 py-0.5">
            {leads.length}
          </span>
        </div>
        {valueStr && (
          <p className="text-[11px] text-[#2d6a3f] font-medium mt-1 pl-4">
            {valueStr}
          </p>
        )}
      </div>
      <div className="rounded-xl p-2 min-h-[calc(100vh-260px)] space-y-2.5 overflow-y-auto">
        {children}
        {!children &&
          leads.map((lead) => (
            <LeadCard
              key={lead.id}
              lead={lead}
              onClick={onLeadClick}
              showAgentStage={showAgentStage}
              tags={leadTagsMap?.[lead.id]}
              lastMessage={lastMessagesMap?.[lead.id]}
            />
          ))}
        {footer}
      </div>
    </div>
  );
}
