"use client";

interface KanbanFiltersProps {
  search: string;
  onSearchChange: (val: string) => void;
  showActive: boolean;
  onToggleActive: () => void;
}

export function KanbanFilters({ search, onSearchChange, showActive, onToggleActive }: KanbanFiltersProps) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <div className="relative w-80">
        <svg
          className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9ca3af]"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
          />
        </svg>
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Buscar por nome, empresa ou telefone..."
          className="w-full text-[13px] rounded-[10px] pl-9 pr-4 py-2.5 bg-white border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] transition-colors text-[#1f1f1f] placeholder:text-[#9ca3af]"
        />
      </div>
      <button
        onClick={onToggleActive}
        className={`px-4 py-2.5 rounded-[10px] text-[12px] font-medium transition-colors ${
          showActive
            ? "bg-[#1f1f1f] text-white"
            : "bg-white text-[#5f6368] border border-[#e5e5dc] hover:bg-[#f6f7ed]"
        }`}
      >
        Leads ativos
      </button>
    </div>
  );
}
