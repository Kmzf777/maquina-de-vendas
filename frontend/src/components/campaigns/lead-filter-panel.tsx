// frontend/src/components/campaigns/lead-filter-panel.tsx
"use client";

import { useState, useEffect, useRef } from "react";
import { DEAL_CATEGORIES } from "@/lib/constants";

interface Pipeline { id: string; name: string; }
interface PipelineStage { id: string; label: string; dot_color: string; }
interface Tag { id: string; name: string; color: string; }

export interface LeadFilters {
  pipelineId: string;
  stageId: string;
  dealCategory: string;
  tagIds: string[];
  noDeal: boolean;
  createdAfter: string;
  createdBefore: string;
  search: string;
}

const EMPTY_FILTERS: LeadFilters = {
  pipelineId: "", stageId: "", dealCategory: "",
  tagIds: [], noDeal: false, createdAfter: "", createdBefore: "", search: "",
};

interface LeadFilterPanelProps {
  onApply: (filters: LeadFilters) => void;
  loading?: boolean;
}

export function LeadFilterPanel({ onApply }: LeadFilterPanelProps) {
  const [filters, setFilters] = useState<LeadFilters>(EMPTY_FILTERS);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    fetch("/api/pipelines").then((r) => r.json()).then((d) => setPipelines(Array.isArray(d) ? d : []));
    fetch("/api/tags").then((r) => r.json()).then((d) => setTags(Array.isArray(d) ? d : []));
  }, []);

  useEffect(() => {
    if (!filters.pipelineId) { setStages([]); setFilters((f) => ({ ...f, stageId: "" })); return; }
    fetch(`/api/pipelines/${filters.pipelineId}/stages`)
      .then((r) => r.json())
      .then((d) => setStages(Array.isArray(d) ? d : []));
  }, [filters.pipelineId]);

  useEffect(() => {
    onApply(filters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.pipelineId, filters.stageId, filters.dealCategory, filters.noDeal, filters.tagIds]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onApply(filters);
    }, 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.search, filters.createdAfter, filters.createdBefore]);

  const set = (key: keyof LeadFilters, value: unknown) =>
    setFilters((f) => ({ ...f, [key]: value }));

  const toggleTag = (id: string) =>
    setFilters((f) => ({
      ...f,
      tagIds: f.tagIds.includes(id) ? f.tagIds.filter((t) => t !== id) : [...f.tagIds, id],
    }));

  const reset = () => setFilters(EMPTY_FILTERS);

  const labelClass = "block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1";
  const selectClass = "w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none";
  const inputClass = "w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] placeholder:text-[#b0aca6] focus:border-[#111111] focus:outline-none";

  return (
    <div className="space-y-4">
      <div>
        <label className={labelClass}>Busca</label>
        <input
          value={filters.search}
          onChange={(e) => set("search", e.target.value)}
          placeholder="Nome, telefone ou empresa"
          className={inputClass}
        />
      </div>

      <div>
        <label className={labelClass}>Funil</label>
        <select value={filters.pipelineId} onChange={(e) => set("pipelineId", e.target.value)} className={selectClass}>
          <option value="">Todos os funis</option>
          {pipelines.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>

      {stages.length > 0 && (
        <div>
          <label className={labelClass}>Etapa do deal</label>
          <select value={filters.stageId} onChange={(e) => set("stageId", e.target.value)} className={selectClass}>
            <option value="">Todas as etapas</option>
            {stages.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
      )}

      <div>
        <label className={labelClass}>Categoria do deal</label>
        <select value={filters.dealCategory} onChange={(e) => set("dealCategory", e.target.value)} className={selectClass}>
          <option value="">Todas as categorias</option>
          {DEAL_CATEGORIES.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="no-deal"
          checked={filters.noDeal}
          onChange={(e) => {
            set("noDeal", e.target.checked);
            if (e.target.checked) setFilters((f) => ({ ...f, pipelineId: "", stageId: "", dealCategory: "" }));
          }}
          className="w-4 h-4 rounded border-[#dedbd6] accent-[#111111]"
        />
        <label htmlFor="no-deal" className="text-[13px] text-[#111111]">Apenas leads sem deal</label>
      </div>

      {tags.length > 0 && (
        <div>
          <label className={labelClass}>Tags</label>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {tags.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => toggleTag(t.id)}
                className={`text-[12px] px-2 py-0.5 rounded-[4px] border transition-colors ${
                  filters.tagIds.includes(t.id)
                    ? "bg-[#111111] text-white border-[#111111]"
                    : "bg-white text-[#111111] border-[#dedbd6] hover:border-[#111111]"
                }`}
              >
                {t.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <div>
        <label className={labelClass}>Criado entre</label>
        <div className="flex gap-2">
          <input type="date" value={filters.createdAfter} onChange={(e) => set("createdAfter", e.target.value)} className={inputClass} />
          <input type="date" value={filters.createdBefore} onChange={(e) => set("createdBefore", e.target.value)} className={inputClass} />
        </div>
      </div>

      <div className="pt-1">
        <button
          type="button"
          onClick={reset}
          className="w-full bg-transparent text-[#111111] border border-[#dedbd6] px-3 py-2 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors"
        >
          Limpar filtros
        </button>
      </div>
    </div>
  );
}
