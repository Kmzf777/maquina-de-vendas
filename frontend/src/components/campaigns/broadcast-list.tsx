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
          className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-64"
        />
        <div className="flex gap-1">
          {filters.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={filter === f.key
                ? "bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                : "bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="text-[14px] text-[#7b7b78] text-center py-12">Nenhum disparo encontrado</p>
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
