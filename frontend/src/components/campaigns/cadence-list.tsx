"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Campaign } from "@/lib/types";
import { CadenceCard } from "./cadence-card";

interface CadenceListProps {
  campaigns: Campaign[];
  onRefresh: () => void;
}

const FILTERS = [
  { key: "all", label: "Todas" },
  { key: "active", label: "Ativas" },
  { key: "draft", label: "Rascunho" },
  { key: "paused", label: "Pausadas" },
  { key: "archived", label: "Arquivadas" },
];

export function CadenceList({ campaigns, onRefresh }: CadenceListProps) {
  const router = useRouter();
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const filtered = campaigns.filter((c) => {
    if (filter !== "all" && c.status !== filter) return false;
    if (search && !c.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="bg-[#faf9f6]">
      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Buscar cadência..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-64"
        />
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={filter === f.key
                ? "bg-[#111111] text-white rounded-[4px] px-3 py-1.5 text-[13px]"
                : "border border-[#dedbd6] text-[#313130] rounded-[4px] px-3 py-1.5 text-[13px] hover:border-[#111111]"}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="text-[#7b7b78] text-center py-8">Nenhuma cadência encontrada</p>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {filtered.map((c) => (
            <CadenceCard
              key={c.id}
              campaign={c}
              onClick={() => router.push(`/campanhas/cadencias/${c.id}`)}
              onRefresh={onRefresh}
            />
          ))}
        </div>
      )}
    </div>
  );
}
