"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Broadcast } from "@/lib/types";
import { BroadcastCard } from "./broadcast-card";

interface BroadcastListProps {
  broadcasts: Broadcast[];
  onRefresh: () => void;
}

export function BroadcastList({ broadcasts, onRefresh }: BroadcastListProps) {
  const router = useRouter();
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
    if (action === "start") {
      const spamRes = await fetch(`/api/broadcasts/${id}/spam-check`);
      if (!spamRes.ok) {
        const errBody = await spamRes.text();
        console.error("[spam-check] HTTP", spamRes.status, errBody);
        alert("Erro ao verificar spam. Tente novamente.");
        return;
      }
      const spamData = await spamRes.json();
      if ((spamData.conflicts ?? []).length > 0) {
        // Conflicts found — navigate to detail page where the full spam modal is shown
        router.push(`/campanhas/disparos/${id}`);
        return;
      }
      const startRes = await fetch(`/api/broadcasts/${id}/start`, { method: "POST" });
      if (!startRes.ok) {
        const body = await startRes.json().catch(() => ({}));
        alert(body.detail ?? "Erro ao iniciar disparo.");
        return;
      }
      onRefresh();
      return;
    }
    await fetch(`/api/broadcasts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "paused" }),
    });
    onRefresh();
  };

  return (
    <div className="bg-[#faf9f6]">
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
                ? "bg-[#111111] text-white rounded-[4px] px-3 py-1.5 text-[13px]"
                : "border border-[#dedbd6] text-[#313130] rounded-[4px] px-3 py-1.5 text-[13px] hover:border-[#111111]"}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="text-[#7b7b78] text-center py-8">Nenhum disparo encontrado</p>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {filtered.map((b) => (
            <BroadcastCard
              key={b.id}
              broadcast={b}
              onStart={() => handleAction(b.id, "start")}
              onPause={() => handleAction(b.id, "pause")}
              onClick={() => router.push(`/campanhas/disparos/${b.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
