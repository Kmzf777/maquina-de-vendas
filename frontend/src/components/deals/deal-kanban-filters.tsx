"use client";

import { DEAL_CATEGORIES } from "@/lib/constants";

interface DealKanbanFiltersProps {
  search: string;
  onSearchChange: (val: string) => void;
  category: string;
  onCategoryChange: (val: string) => void;
  showActive: boolean;
  onToggleActive: () => void;
}

export function DealKanbanFilters({
  search, onSearchChange, category, onCategoryChange, showActive, onToggleActive,
}: DealKanbanFiltersProps) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <div className="relative w-72">
        <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9ca3af]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Buscar por titulo, lead ou empresa..."
          className="w-full text-[13px] rounded-[10px] pl-9 pr-4 py-2.5 bg-white border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] transition-colors text-[#1f1f1f] placeholder:text-[#9ca3af]"
        />
      </div>
      <select
        value={category}
        onChange={(e) => onCategoryChange(e.target.value)}
        className="py-2.5 px-3 rounded-[10px] border border-[#e5e5dc] text-[12px] text-[#5f6368] bg-white cursor-pointer"
      >
        <option value="">Todas categorias</option>
        {DEAL_CATEGORIES.map((c) => (
          <option key={c.key} value={c.key}>{c.label}</option>
        ))}
      </select>
      <button
        onClick={onToggleActive}
        className={`px-4 py-2.5 rounded-[10px] text-[12px] font-medium transition-colors ${
          showActive
            ? "bg-[#1f1f1f] text-white"
            : "bg-white text-[#5f6368] border border-[#e5e5dc] hover:bg-[#f6f7ed]"
        }`}
      >
        Deals ativos
      </button>
    </div>
  );
}
