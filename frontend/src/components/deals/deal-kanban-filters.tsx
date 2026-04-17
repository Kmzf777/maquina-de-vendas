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
        <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#7b7b78]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Buscar por titulo, lead ou empresa..."
          className="bg-white border border-[#dedbd6] rounded-[6px] pl-9 pr-4 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full transition-colors"
        />
      </div>
      <select
        value={category}
        onChange={(e) => onCategoryChange(e.target.value)}
        className="py-2 px-3 rounded-[6px] border border-[#dedbd6] text-[13px] text-[#313130] bg-white cursor-pointer focus:border-[#111111] focus:outline-none"
      >
        <option value="">Todas categorias</option>
        {DEAL_CATEGORIES.map((c) => (
          <option key={c.key} value={c.key}>{c.label}</option>
        ))}
      </select>
      <button
        onClick={onToggleActive}
        className={`px-3 py-1.5 rounded-[4px] text-[13px] transition-colors ${
          showActive
            ? "bg-[#111111] text-white"
            : "border border-[#dedbd6] text-[#313130] hover:border-[#111111]"
        }`}
      >
        Deals ativos
      </button>
    </div>
  );
}
