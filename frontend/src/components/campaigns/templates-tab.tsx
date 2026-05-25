// frontend/src/components/campaigns/templates-tab.tsx
"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import type { MessageTemplate, Channel } from "@/lib/types";
import { CreateTemplateModal } from "@/components/canais/create-template-modal";
import { TemplateDetailSheet } from "@/components/campaigns/template-detail-sheet";

// ─── Config ────────────────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utility",        color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Authentication", color: "#6b27a8", bg: "#f2eafc" },
};

const STATUS_CONFIG: Record<string, { label: string; colorClass: string }> = {
  approved:                { label: "Aprovado",       colorClass: "bg-[#e6faf0] text-[#1a7a3a]" },
  pending:                 { label: "Pendente",       colorClass: "bg-[#fff8e0] text-[#7a5a00]" },
  pending_category_review: { label: "Rev. categoria", colorClass: "bg-[#fff8e0] text-[#7a5a00]" },
  cancelled:               { label: "Cancelado",      colorClass: "bg-[#f0ede8] text-[#7b7b78]" },
  rejected:                { label: "Rejeitado",      colorClass: "bg-[#fef0f0] text-[#c41c1c]" },
};

// ─── Sort ──────────────────────────────────────────────────────────────────────

type SortKey = "name" | "category" | "status" | "language" | "created_at";
type SortDirection = "asc" | "desc";

interface SortConfig {
  key: SortKey;
  direction: SortDirection;
}

function sortTemplates(templates: MessageTemplate[], config: SortConfig | null): MessageTemplate[] {
  if (!config) return templates;
  return [...templates].sort((a, b) => {
    let aVal: string;
    let bVal: string;
    if (config.key === "category") {
      aVal = (a.category ?? "").toLowerCase();
      bVal = (b.category ?? "").toLowerCase();
    } else if (config.key === "created_at") {
      aVal = a.created_at;
      bVal = b.created_at;
    } else {
      aVal = (a[config.key] ?? "").toString().toLowerCase();
      bVal = (b[config.key] ?? "").toString().toLowerCase();
    }
    const cmp = aVal.localeCompare(bVal);
    return config.direction === "asc" ? cmp : -cmp;
  });
}

// ─── SortableHeader ────────────────────────────────────────────────────────────

interface SortableHeaderProps {
  label: string;
  sortKey: SortKey;
  sortConfig: SortConfig | null;
  onSort: (key: SortKey) => void;
}

function SortableHeader({ label, sortKey, sortConfig, onSort }: SortableHeaderProps) {
  const isActive = sortConfig?.key === sortKey;
  const direction = isActive ? sortConfig!.direction : null;
  return (
    <th className="text-left px-4 py-3 font-normal">
      <button
        onClick={() => onSort(sortKey)}
        className="flex items-center gap-1 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] hover:text-[#111111] transition-colors"
      >
        {label}
        {!isActive && <ArrowUpDown size={12} className="opacity-40" />}
        {direction === "asc" && <ArrowUp size={12} />}
        {direction === "desc" && <ArrowDown size={12} />}
      </button>
    </th>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────────

export function TemplatesTab() {
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncToast, setSyncToast] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [sortConfig, setSortConfig] = useState<SortConfig | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<MessageTemplate | null>(null);
  const hasSyncedOnMount = useRef(false);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    const res = await fetch("/api/templates");
    if (res.ok) setTemplates(await res.json());
    setLoading(false);
  }, []);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  const syncTemplates = useCallback(async () => {
    setSyncing(true);
    try {
      const channelsRes = await fetch("/api/channels");
      if (!channelsRes.ok) throw new Error("Falha ao carregar canais");
      const channelsData: Channel[] = await channelsRes.json();
      const metaChannels = (Array.isArray(channelsData) ? channelsData : []).filter(
        (c) =>
          c.provider === "meta_cloud" &&
          c.is_active &&
          c.provider_config?.waba_id &&
          c.provider_config?.access_token
      );

      let errors = 0;
      for (const channel of metaChannels) {
        const res = await fetch(`/api/templates/sync?channel_id=${channel.id}`, { method: "POST" });
        if (!res.ok) errors++;
      }

      await loadTemplates();
      setSyncToast(
        errors === 0
          ? { type: "success", message: "Templates sincronizados com sucesso." }
          : { type: "error", message: `Sincronização concluída com ${errors} erro(s).` }
      );
    } catch {
      setSyncToast({ type: "error", message: "Erro ao sincronizar templates." });
    } finally {
      setSyncing(false);
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
      toastTimerRef.current = setTimeout(() => setSyncToast(null), 5000);
    }
  }, [loadTemplates]);

  useEffect(() => {
    if (hasSyncedOnMount.current) return;
    hasSyncedOnMount.current = true;
    syncTemplates();
  }, [syncTemplates]);

  useEffect(() => {
    return () => { if (toastTimerRef.current) clearTimeout(toastTimerRef.current); };
  }, []);

  const handleSort = (key: SortKey) => {
    setSortConfig((prev) => {
      if (!prev || prev.key !== key) return { key, direction: "asc" };
      if (prev.direction === "asc") return { key, direction: "desc" };
      return null;
    });
  };

  const cat = (c: string | null) => CATEGORY_CONFIG[(c ?? "").toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const st = (s: string) => STATUS_CONFIG[s] ?? STATUS_CONFIG.cancelled;

  const sorted = sortTemplates(templates, sortConfig);

  const SORT_COLUMNS: { label: string; key: SortKey }[] = [
    { label: "Nome", key: "name" },
    { label: "Categoria", key: "category" },
    { label: "Status", key: "status" },
    { label: "Idioma", key: "language" },
    { label: "Criado em", key: "created_at" },
  ];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 style={{ letterSpacing: "-0.3px" }} className="text-[20px] font-normal text-[#111111]">
          Templates
        </h2>
        <div className="flex gap-2">
          <button
            onClick={syncTemplates}
            disabled={syncing}
            className="flex items-center gap-2 bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="14" height="14" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round"
              className={syncing ? "animate-spin" : ""}
            >
              <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
              <path d="M21 3v5h-5" />
              <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
              <path d="M8 16H3v5" />
            </svg>
            {syncing ? "Sincronizando..." : "Sincronizar"}
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
          >
            + Novo Template
          </button>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-14 bg-[#dedbd6] rounded-[8px] animate-pulse" />
          ))}
        </div>
      )}

      {/* Empty */}
      {!loading && templates.length === 0 && (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] py-12 text-center">
          <p className="text-[14px] text-[#7b7b78]">Nenhum template cadastrado.</p>
          <button onClick={() => setShowCreate(true)} className="mt-3 text-[13px] text-[#111111] underline">
            Criar primeiro template
          </button>
        </div>
      )}

      {/* Table */}
      {!loading && templates.length > 0 && (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#f0ede8]">
                {SORT_COLUMNS.map((col) => (
                  <SortableHeader
                    key={col.key}
                    label={col.label}
                    sortKey={col.key}
                    sortConfig={sortConfig}
                    onSort={handleSort}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((t) => {
                const c = cat(t.category);
                const s = st(t.status);
                return (
                  <tr
                    key={t.id}
                    onClick={() => setSelectedTemplate(t)}
                    className="border-b border-[#f0ede8] last:border-0 hover:bg-[#faf9f6] cursor-pointer"
                  >
                    <td className="px-4 py-3">
                      <p className="text-[13px] text-[#111111] font-medium">{t.name}</p>
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        className="rounded-[4px] border-0 h-auto text-[11px] font-medium px-2 py-0.5"
                        style={{ color: c.color, backgroundColor: c.bg }}
                      >
                        {c.label}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge className={`rounded-[4px] border-0 h-auto text-[11px] font-medium px-2 py-0.5 ${s.colorClass}`}>
                        {s.label}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        variant="outline"
                        className="rounded-[4px] h-auto text-[11px] font-normal px-2 py-0.5 text-[#7b7b78]"
                      >
                        {t.language}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-[12px] text-[#7b7b78]">
                      {new Date(t.created_at).toLocaleDateString("pt-BR")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Sync toast */}
      {syncToast && (
        <div className={`fixed bottom-6 right-6 z-50 text-white text-[14px] px-4 py-3 rounded-[6px] shadow-lg flex items-center gap-3 ${syncToast.type === "success" ? "bg-[#111111]" : "bg-[#c41c1c]"}`}>
          <span>{syncToast.message}</span>
          <button onClick={() => setSyncToast(null)} className="text-white/60 hover:text-white transition-colors leading-none text-lg">&times;</button>
        </div>
      )}

      {/* Detail Sheet */}
      <TemplateDetailSheet
        template={selectedTemplate}
        onClose={() => setSelectedTemplate(null)}
      />

      <CreateTemplateModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => { setShowCreate(false); loadTemplates(); }}
      />
    </div>
  );
}
