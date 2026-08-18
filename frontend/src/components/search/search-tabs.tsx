"use client";

import type { SearchTab } from "@/lib/universal-search";
import { countForTab, type UniversalSearchResults } from "@/hooks/use-universal-search";

const TABS: SearchTab[] = ["all", "leads", "deals", "sales", "conversations"];

const TAB_LABELS: Record<SearchTab, string> = {
  all: "Tudo",
  leads: "Leads",
  deals: "Deals",
  sales: "Vendas",
  conversations: "Conversas",
};

interface SearchTabsProps {
  active: SearchTab;
  onChange: (tab: SearchTab) => void;
  results: UniversalSearchResults;
}

export function SearchTabs({ active, onChange, results }: SearchTabsProps) {
  return (
    <div className="flex items-center gap-1 border-b border-[#dedbd6] overflow-x-auto">
      {TABS.map((tab) => {
        const count = countForTab(results, tab);
        const isActive = tab === active;
        return (
          <button
            key={tab}
            type="button"
            onClick={() => onChange(tab)}
            className={`px-3.5 py-2.5 text-[13px] font-medium border-b-2 -mb-px whitespace-nowrap transition-colors ${
              isActive
                ? "border-[#111111] text-[#111111]"
                : "border-transparent text-[#7b7b78] hover:text-[#111111]"
            }`}
          >
            {TAB_LABELS[tab]}
            {count !== null && count > 0 && (
              <span className="ml-1.5 text-[11px] text-[#7b7b78]">{count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
