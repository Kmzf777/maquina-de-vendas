"use client";

import { useState, useEffect } from "react";
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { useDragScroll } from "@/hooks/use-drag-scroll";
import { AGENT_STAGES } from "@/lib/constants";
import { KanbanColumn } from "@/components/kanban-column";
import { KanbanMetricsBar } from "@/components/kanban-metrics-bar";
import { KanbanFilters } from "@/components/kanban-filters";
import { QuickAddLead } from "@/components/quick-add-lead";
import { ChatPanel } from "@/components/chat-panel";
import { createClient } from "@/lib/supabase/client";
import type { Lead, Tag } from "@/lib/types";

export default function QualificacaoPage() {
  const { leads, loading } = useRealtimeLeads();
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [search, setSearch] = useState("");
  const [showActive, setShowActive] = useState(true);
  const [tags, setTags] = useState<Tag[]>([]);
  const [leadTagsMap, setLeadTagsMap] = useState<Record<string, Tag[]>>({});
  const [lastMessagesMap, setLastMessagesMap] = useState<Record<string, string>>({});
  const supabase = createClient();
  const { ref: kanbanRef, onMouseDown: kanbanMouseDown, onMouseMove: kanbanMouseMove, onMouseUp: kanbanMouseUp, onMouseLeave: kanbanMouseLeave } = useDragScroll();

  useEffect(() => {
    async function loadTags() {
      const { data: tagsData } = await supabase.from("tags").select("*");
      if (!tagsData) return;
      setTags(tagsData);

      const { data: ltData } = await supabase.from("lead_tags").select("lead_id, tag_id");
      if (!ltData) return;

      const map: Record<string, Tag[]> = {};
      ltData.forEach((row: { lead_id: string; tag_id: string }) => {
        const tag = tagsData.find((t: Tag) => t.id === row.tag_id);
        if (tag) {
          if (!map[row.lead_id]) map[row.lead_id] = [];
          map[row.lead_id].push(tag);
        }
      });
      setLeadTagsMap(map);
    }
    loadTags();
  }, []);

  useEffect(() => {
    if (leads.length === 0) return;
    async function loadLastMessages() {
      const leadIds = leads.map((l) => l.id);
      const { data } = await supabase
        .from("messages")
        .select("lead_id, content, role")
        .in("lead_id", leadIds)
        .neq("role", "system")
        .order("created_at", { ascending: false })
        .limit(leadIds.length * 5);

      if (!data) return;
      const map: Record<string, string> = {};
      data.forEach((msg: { lead_id: string; content: string }) => {
        if (!map[msg.lead_id]) map[msg.lead_id] = msg.content;
      });
      setLastMessagesMap(map);
    }
    loadLastMessages();
  }, [leads]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 border-2 border-[#dedbd6] border-t-transparent rounded-full animate-spin" />
          <span className="text-[14px] text-[#7b7b78]">Carregando...</span>
        </div>
      </div>
    );
  }

  const filteredLeads = leads.filter((l) => {
    if (search) {
      const q = search.toLowerCase();
      const match =
        (l.name || "").toLowerCase().includes(q) ||
        (l.company || "").toLowerCase().includes(q) ||
        (l.nome_fantasia || "").toLowerCase().includes(q) ||
        l.phone.includes(q);
      if (!match) return false;
    }
    return true;
  });

  return (
    <div className="flex flex-col h-full">
      {/* Page Header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0">
        <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111]">Visão Agent AI</h1>
        <p className="text-[14px] text-[#7b7b78] mt-0.5">Leads qualificados pelo agente</p>
      </div>

      <div className="px-4 md:px-8 py-4 md:py-8 overflow-auto flex-1 bg-[#faf9f6]">
        <KanbanMetricsBar leads={filteredLeads} />
        <KanbanFilters
          search={search}
          onSearchChange={setSearch}
          showActive={showActive}
          onToggleActive={() => setShowActive(!showActive)}
        />

        <div
          ref={kanbanRef}
          className="flex gap-3 overflow-x-auto pb-4"
          onMouseDown={kanbanMouseDown}
          onMouseMove={kanbanMouseMove}
          onMouseUp={kanbanMouseUp}
          onMouseLeave={kanbanMouseLeave}
        >
          {AGENT_STAGES.map((stage) => {
            const stageLeads = filteredLeads.filter((l) => l.stage === stage.key);
            return (
              <KanbanColumn
                key={stage.key}
                title={stage.label}
                leads={stageLeads}
                dotColor={stage.dotColor}
                tintColor={stage.tintColor}
                avatarColor={stage.avatarColor}
                onLeadClick={setSelectedLead}
                leadTagsMap={leadTagsMap}
                lastMessagesMap={lastMessagesMap}
                footer={<QuickAddLead stage={stage.key} />}
              />
            );
          })}
        </div>
      </div>

      {selectedLead && (
        <ChatPanel
          lead={selectedLead}
          onClose={() => setSelectedLead(null)}
        />
      )}
    </div>
  );
}
