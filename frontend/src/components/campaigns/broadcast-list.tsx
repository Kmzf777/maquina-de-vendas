"use client";

import { useState } from "react";
import type { Broadcast } from "@/lib/types";
import { BroadcastCard } from "./broadcast-card";

interface BroadcastListProps {
  broadcasts: Broadcast[];
  onRefresh: () => void;
}

export function BroadcastList({ broadcasts, onRefresh }: BroadcastListProps) {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const filtered = broadcasts.filter((b) => {
    if (filter !== "all" && b.status !== filter) return false;
    if (search && !b.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const filters = [
    { key: "all", label: "Todos" },
    { key: "draft", label: "Rascunho" },
    { key: "running", label: "Rodando" },
    { key: "completed", label: "Completos" },
  ];

  const handleAction = async (id: string, action: "start" | "pause") => {
    const url = action === "start" ? `/api/broadcasts/${id}/start` : `/api/broadcasts/${id}`;
    const method = action === "start" ? "POST" : "PATCH";
    const body = action === "pause" ? JSON.stringify({ status: "paused" }) : undefined;
    await fetch(url, { method, headers: { "Content-Type": "application/json" }, body });
    onRefresh();
  };

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Buscar disparo..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-1.5 rounded-lg border border-[#e5e5dc] text-[13px] bg-white w-64"
        />
        <div className="flex gap-1">
          {filters.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors ${
                filter === f.key ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="text-[13px] text-[#9ca3af] text-center py-12">Nenhum disparo encontrado</p>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {filtered.map((b) => (
            <BroadcastCard
              key={b.id}
              broadcast={b}
              onStart={() => handleAction(b.id, "start")}
              onPause={() => handleAction(b.id, "pause")}
              onClick={() => {}}
            />
          ))}
        </div>
      )}
    </div>
  );
}
