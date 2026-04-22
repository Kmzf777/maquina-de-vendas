"use client";

import { useState, useMemo, useEffect } from "react";
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { getTemperature } from "@/lib/temperature";
import { LeadGridCard } from "@/components/leads/lead-grid-card";
import { LeadsFilterBar, type LeadFilters } from "@/components/leads/leads-filter-bar";
import { LeadDetailModal } from "@/components/leads/lead-detail-modal";
import { LeadCreateModal } from "@/components/leads/lead-create-modal";
import { LeadImportModal } from "@/components/leads/lead-import-modal";
import type { Lead, Tag } from "@/lib/types";
import { createClient } from "@/lib/supabase/client";

const LEADS_PER_PAGE = 30;

export default function LeadsPage() {
  const { leads, loading } = useRealtimeLeads();
  const [tags, setTags] = useState<Tag[]>([]);
  const [leadTagsMap, setLeadTagsMap] = useState<Record<string, string[]>>({});
  const [filters, setFilters] = useState<LeadFilters>({
    search: "", temperature: "", stage: "", tagId: "", channel: "",
  });
  const [page, setPage] = useState(1);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);

  const supabase = createClient();

  // Fetch tags and lead_tags
  useEffect(() => {
    async function fetchTags() {
      const { data: tagsData } = await supabase.from("tags").select("*");
      if (tagsData) setTags(tagsData);

      const { data: ltData } = await supabase.from("lead_tags").select("lead_id, tag_id");
      if (ltData) {
        const map: Record<string, string[]> = {};
        for (const lt of ltData) {
          if (!map[lt.lead_id]) map[lt.lead_id] = [];
          map[lt.lead_id].push(lt.tag_id);
        }
        setLeadTagsMap(map);
      }
    }
    fetchTags();
  }, []);

  // Apply filters
  const filtered = useMemo(() => {
    return leads.filter((lead) => {
      if (filters.search) {
        const q = filters.search.toLowerCase();
        const match =
          (lead.name || "").toLowerCase().includes(q) ||
          lead.phone.includes(q) ||
          (lead.company || "").toLowerCase().includes(q) ||
          (lead.razao_social || "").toLowerCase().includes(q);
        if (!match) return false;
      }
      if (filters.temperature && getTemperature(lead.last_msg_at) !== filters.temperature) return false;
      if (filters.stage && lead.stage !== filters.stage) return false;
      if (filters.channel && lead.channel !== filters.channel) return false;
      if (filters.tagId) {
        const leadTags = leadTagsMap[lead.id] || [];
        if (!leadTags.includes(filters.tagId)) return false;
      }
      return true;
    });
  }, [leads, filters, leadTagsMap]);

  // Pagination
  const totalPages = Math.ceil(filtered.length / LEADS_PER_PAGE);
  const paginated = filtered.slice((page - 1) * LEADS_PER_PAGE, page * LEADS_PER_PAGE);

  // Reset page when filters change
  useEffect(() => { setPage(1); }, [filters]);

  // KPIs
  const kpis = useMemo(() => {
    const total = leads.length;
    let quentes = 0, mornos = 0, frios = 0;
    for (const lead of leads) {
      const temp = getTemperature(lead.last_msg_at);
      if (temp === "quente") quentes++;
      else if (temp === "morno") mornos++;
      else frios++;
    }
    return { total, quentes, mornos, frios };
  }, [leads]);

  function getLeadTags(leadId: string): Tag[] {
    const tagIds = leadTagsMap[leadId] || [];
    return tags.filter((t) => tagIds.includes(t.id));
  }

  async function handleSaveLead(leadId: string, data: Partial<Lead>) {
    await fetch(`/api/leads/${leadId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  }

  async function handleTagsChange(leadId: string, tagIds: string[]) {
    await fetch(`/api/leads/${leadId}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tagIds }),
    });
    setLeadTagsMap((prev) => ({ ...prev, [leadId]: tagIds }));
  }

  async function handleCreateLead(data: Record<string, string>): Promise<{ error?: string }> {
    const res = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json();
      return { error: err.error || "Erro ao criar lead" };
    }
    return {};
  }

  async function handleExport() {
    const res = await fetch("/api/leads/export");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `leads-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0">
          <div className="h-8 w-32 rounded-[8px] animate-pulse bg-[#dedbd6]" />
          <div className="h-4 w-64 rounded-[8px] animate-pulse mt-2 bg-[#dedbd6]" />
        </div>
        <div className="flex-1 overflow-auto bg-[#faf9f6] px-8 py-6 space-y-6">
          <div className="grid grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="bg-white border border-[#dedbd6] rounded-[8px] p-5 h-24 animate-pulse" />
            ))}
          </div>
          <div className="grid grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="bg-white border border-[#dedbd6] rounded-[8px] p-5 h-40 animate-pulse" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Page Header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex items-center justify-between flex-shrink-0">
        <div>
          <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111]">
            Leads
          </h1>
          <p className="text-[14px] text-[#7b7b78] mt-0.5">{leads.length} contatos no CRM</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowImport(true)}
            className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] flex items-center gap-1.5"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
            Importar
          </button>
          <button
            onClick={handleExport}
            className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] flex items-center gap-1.5"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12M12 16.5V3" />
            </svg>
            Exportar
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] flex items-center gap-1.5"
          >
            <span className="text-[16px] leading-none">+</span>
            Novo Lead
          </button>
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-auto bg-[#faf9f6]">
        {/* Filter bar */}
        <LeadsFilterBar
          filters={filters}
          onChange={setFilters}
          tags={tags}
          totalCount={leads.length}
          filteredCount={filtered.length}
        />

        <div className="px-8 py-6">
          {/* KPI Bar */}
          <div className="grid grid-cols-4 gap-4 mb-6">
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
              <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Total de Leads</p>
              <p className="text-[28px] font-normal text-[#111111] mt-1" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>{kpis.total}</p>
            </div>
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
              <div className="flex justify-between items-start">
                <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Quentes</p>
                <span className="w-2.5 h-2.5 rounded-full bg-[#c41c1c]" />
              </div>
              <p className="text-[28px] font-normal text-[#c41c1c] mt-1" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>{kpis.quentes}</p>
              <p className="text-[11px] text-[#7b7b78]">Ultima msg &lt; 48h</p>
            </div>
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
              <div className="flex justify-between items-start">
                <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Mornos</p>
                <span className="w-2.5 h-2.5 rounded-full bg-[#ff5600]" />
              </div>
              <p className="text-[28px] font-normal text-[#ff5600] mt-1" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>{kpis.mornos}</p>
              <p className="text-[11px] text-[#7b7b78]">Ultima msg 48h-7d</p>
            </div>
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
              <div className="flex justify-between items-start">
                <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Frios</p>
                <span className="w-2.5 h-2.5 rounded-full bg-[#7b7b78]" />
              </div>
              <p className="text-[28px] font-normal text-[#7b7b78] mt-1" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>{kpis.frios}</p>
              <p className="text-[11px] text-[#7b7b78]">Ultima msg &gt; 7d</p>
            </div>
          </div>

          {/* Cards Grid */}
          {paginated.length > 0 ? (
            <div className="grid grid-cols-3 gap-4">
              {paginated.map((lead) => (
                <LeadGridCard
                  key={lead.id}
                  lead={lead}
                  tags={getLeadTags(lead.id)}
                  onClick={setSelectedLead}
                />
              ))}
            </div>
          ) : (
            <div className="text-center py-12">
              <p className="text-[14px] text-[#7b7b78]">Nenhum lead encontrado.</p>
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex justify-center items-center gap-2 mt-6">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 rounded-[4px] border border-[#dedbd6] bg-white text-[13px] text-[#7b7b78] disabled:opacity-40 hover:border-[#111111] transition-colors"
              >
                &larr;
              </button>
              {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                let pageNum: number;
                if (totalPages <= 7) {
                  pageNum = i + 1;
                } else if (page <= 4) {
                  pageNum = i + 1;
                } else if (page >= totalPages - 3) {
                  pageNum = totalPages - 6 + i;
                } else {
                  pageNum = page - 3 + i;
                }
                return (
                  <button
                    key={pageNum}
                    onClick={() => setPage(pageNum)}
                    className={`px-3 py-1.5 rounded-[4px] text-[13px] transition-colors ${
                      page === pageNum
                        ? "bg-[#111111] text-white"
                        : "border border-[#dedbd6] bg-white text-[#7b7b78] hover:border-[#111111]"
                    }`}
                  >
                    {pageNum}
                  </button>
                );
              })}
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-1.5 rounded-[4px] border border-[#dedbd6] bg-white text-[13px] text-[#7b7b78] disabled:opacity-40 hover:border-[#111111] transition-colors"
              >
                &rarr;
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Modals */}
      {selectedLead && (
        <LeadDetailModal
          lead={selectedLead}
          tags={tags}
          leadTagIds={leadTagsMap[selectedLead.id] || []}
          onClose={() => setSelectedLead(null)}
          onSave={handleSaveLead}
          onTagsChange={handleTagsChange}
        />
      )}
      {showCreate && (
        <LeadCreateModal
          onClose={() => setShowCreate(false)}
          onCreate={handleCreateLead}
        />
      )}
      {showImport && (
        <LeadImportModal
          onClose={() => setShowImport(false)}
          onImportDone={() => {}}
        />
      )}
    </div>
  );
}
