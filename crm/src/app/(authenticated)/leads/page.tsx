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
    search: "", temperature: "", stage: "", sellerStage: "", tagId: "", channel: "",
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
      if (filters.sellerStage && lead.seller_stage !== filters.sellerStage) return false;
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
    let quentes = 0, mornos = 0, frios = 0, totalValue = 0;
    for (const lead of leads) {
      const temp = getTemperature(lead.last_msg_at);
      if (temp === "quente") quentes++;
      else if (temp === "morno") mornos++;
      else frios++;
      totalValue += lead.sale_value || 0;
    }
    return { total, quentes, mornos, frios, totalValue };
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

  const fmt = (v: number) =>
    v >= 1000000
      ? `R$ ${(v / 1000000).toFixed(1)}M`
      : `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <div className="h-8 w-32 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
          <div className="h-4 w-64 rounded-lg animate-pulse mt-2" style={{ backgroundColor: "#e5e5dc" }} />
        </div>
        <div className="grid grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="card p-5 h-24 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
          ))}
        </div>
        <div className="grid grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card p-5 h-40 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-[28px] font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
            Leads
          </h1>
          <p className="text-[14px] mt-1" style={{ color: "var(--text-muted)" }}>
            Gestao completa dos seus contatos
          </p>
        </div>
        <div className="flex gap-2.5">
          <button
            onClick={() => setShowImport(true)}
            className="px-4 py-2 rounded-lg border border-[#e5e5dc] bg-white text-[#1f1f1f] text-[13px] font-medium hover:bg-[#f6f7ed] transition-colors flex items-center gap-1.5"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
            Importar
          </button>
          <button
            onClick={handleExport}
            className="px-4 py-2 rounded-lg border border-[#e5e5dc] bg-white text-[#1f1f1f] text-[13px] font-medium hover:bg-[#f6f7ed] transition-colors flex items-center gap-1.5"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12M12 16.5V3" />
            </svg>
            Exportar
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] transition-colors flex items-center gap-1.5"
          >
            <span className="text-[16px] leading-none">+</span>
            Novo Lead
          </button>
        </div>
      </div>

      {/* KPI Bar */}
      <div className="grid grid-cols-5 gap-4 mb-6">
        <div className="card p-4">
          <p className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Total de Leads</p>
          <p className="text-[28px] font-bold text-[#1f1f1f] mt-1">{kpis.total}</p>
        </div>
        <div className="card p-4">
          <div className="flex justify-between items-start">
            <p className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Quentes</p>
            <span className="w-2.5 h-2.5 rounded-full bg-[#f87171]" />
          </div>
          <p className="text-[28px] font-bold text-[#f87171] mt-1">{kpis.quentes}</p>
          <p className="text-[11px] text-[#9ca3af]">Ultima msg &lt; 48h</p>
        </div>
        <div className="card p-4">
          <div className="flex justify-between items-start">
            <p className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Mornos</p>
            <span className="w-2.5 h-2.5 rounded-full bg-[#e8d44d]" />
          </div>
          <p className="text-[28px] font-bold text-[#e8d44d] mt-1">{kpis.mornos}</p>
          <p className="text-[11px] text-[#9ca3af]">Ultima msg 48h-7d</p>
        </div>
        <div className="card p-4">
          <div className="flex justify-between items-start">
            <p className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Frios</p>
            <span className="w-2.5 h-2.5 rounded-full bg-[#60a5fa]" />
          </div>
          <p className="text-[28px] font-bold text-[#60a5fa] mt-1">{kpis.frios}</p>
          <p className="text-[11px] text-[#9ca3af]">Ultima msg &gt; 7d</p>
        </div>
        <div className="card p-4">
          <p className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Valor Total Pipeline</p>
          <p className="text-[28px] font-bold text-[#4ade80] mt-1">{fmt(kpis.totalValue)}</p>
        </div>
      </div>

      {/* Filters */}
      <LeadsFilterBar
        filters={filters}
        onChange={setFilters}
        tags={tags}
        totalCount={leads.length}
        filteredCount={filtered.length}
      />

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
          <p className="text-[14px] text-[#9ca3af]">Nenhum lead encontrado.</p>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center items-center gap-2 mt-6">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 rounded-md border border-[#e5e5dc] bg-white text-[13px] text-[#9ca3af] disabled:opacity-40"
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
                className={`px-3 py-1.5 rounded-md text-[13px] ${
                  page === pageNum
                    ? "bg-[#1f1f1f] text-white"
                    : "border border-[#e5e5dc] bg-white text-[#5f6368] hover:bg-[#f6f7ed]"
                }`}
              >
                {pageNum}
              </button>
            );
          })}
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-3 py-1.5 rounded-md border border-[#e5e5dc] bg-white text-[13px] text-[#9ca3af] disabled:opacity-40"
          >
            &rarr;
          </button>
        </div>
      )}

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
