"use client";

import { AGENT_STAGES, LEAD_CHANNELS } from "@/lib/constants";
import type { Temperature } from "@/lib/temperature";
import { TEMPERATURE_CONFIG } from "@/lib/temperature";
import type { Tag } from "@/lib/types";

export interface LeadFilters {
  search: string;
  temperature: Temperature | "";
  stage: string;
  tagId: string;
  channel: string;
}

interface LeadsFilterBarProps {
  filters: LeadFilters;
  onChange: (filters: LeadFilters) => void;
  tags: Tag[];
  totalCount: number;
  filteredCount: number;
}

export function LeadsFilterBar({
  filters,
  onChange,
  tags,
  totalCount,
  filteredCount,
}: LeadsFilterBarProps) {
  function update(partial: Partial<LeadFilters>) {
    onChange({ ...filters, ...partial });
  }

  function clearAll() {
    onChange({ search: "", temperature: "", stage: "", tagId: "", channel: "" });
  }

  const activeFilters: { label: string; key: keyof LeadFilters }[] = [];
  if (filters.temperature) {
    activeFilters.push({ label: TEMPERATURE_CONFIG[filters.temperature].label, key: "temperature" });
  }
  if (filters.stage) {
    const s = AGENT_STAGES.find((a) => a.key === filters.stage);
    activeFilters.push({ label: s?.label || filters.stage, key: "stage" });
  }
  if (filters.tagId) {
    const t = tags.find((tag) => tag.id === filters.tagId);
    activeFilters.push({ label: t?.name || "Tag", key: "tagId" });
  }
  if (filters.channel) {
    const c = LEAD_CHANNELS.find((ch) => ch.key === filters.channel);
    activeFilters.push({ label: c?.label || filters.channel, key: "channel" });
  }

  return (
    <div className="bg-white rounded-xl p-4 border border-[#e5e5dc] mb-5">
      <div className="flex gap-2.5 items-center flex-wrap">
        {/* Search */}
        <div className="flex-1 min-w-[220px] relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9ca3af]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input
            type="text"
            value={filters.search}
            onChange={(e) => update({ search: e.target.value })}
            placeholder="Buscar por nome, telefone, empresa..."
            className="w-full py-2 pl-9 pr-3 rounded-lg border border-[#e5e5dc] text-[13px] outline-none focus:border-[#c8cc8e] transition-colors"
          />
        </div>

        {/* Temperature */}
        <select
          value={filters.temperature}
          onChange={(e) => update({ temperature: e.target.value as Temperature | "" })}
          className="py-2 px-3 rounded-lg border border-[#e5e5dc] text-[13px] text-[#5f6368] bg-white cursor-pointer"
        >
          <option value="">Temperatura</option>
          <option value="quente">Quente</option>
          <option value="morno">Morno</option>
          <option value="frio">Frio</option>
        </select>

        {/* Stage */}
        <select
          value={filters.stage}
          onChange={(e) => update({ stage: e.target.value })}
          className="py-2 px-3 rounded-lg border border-[#e5e5dc] text-[13px] text-[#5f6368] bg-white cursor-pointer"
        >
          <option value="">Stage</option>
          {AGENT_STAGES.map((s) => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>

        {/* Tags */}
        <select
          value={filters.tagId}
          onChange={(e) => update({ tagId: e.target.value })}
          className="py-2 px-3 rounded-lg border border-[#e5e5dc] text-[13px] text-[#5f6368] bg-white cursor-pointer"
        >
          <option value="">Tags</option>
          {tags.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>

        {/* Channel */}
        <select
          value={filters.channel}
          onChange={(e) => update({ channel: e.target.value })}
          className="py-2 px-3 rounded-lg border border-[#e5e5dc] text-[13px] text-[#5f6368] bg-white cursor-pointer"
        >
          <option value="">Canal</option>
          {LEAD_CHANNELS.map((c) => (
            <option key={c.key} value={c.key}>{c.label}</option>
          ))}
        </select>

        {/* Clear */}
        {activeFilters.length > 0 && (
          <button
            onClick={clearAll}
            className="py-2 px-3.5 rounded-lg border border-[#e5e5dc] bg-white text-[#9ca3af] text-[13px] cursor-pointer hover:bg-[#f6f7ed] transition-colors"
          >
            Limpar
          </button>
        )}
      </div>

      {/* Active filter chips */}
      {activeFilters.length > 0 && (
        <div className="flex gap-2 mt-3 flex-wrap items-center">
          {activeFilters.map((f) => (
            <span
              key={f.key}
              className="bg-[#f6f7ed] text-[#5f6368] px-3 py-1 rounded-full text-[12px] flex items-center gap-1.5"
            >
              {f.label}
              <button
                onClick={() => update({ [f.key]: "" })}
                className="text-[#9ca3af] hover:text-[#5f6368] ml-0.5"
              >
                x
              </button>
            </span>
          ))}
          <span className="text-[12px] text-[#9ca3af]">
            Mostrando {filteredCount} de {totalCount} leads
          </span>
        </div>
      )}
    </div>
  );
}
