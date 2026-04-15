"use client";

import { useState, useEffect } from "react";
import type { Cadence } from "@/lib/types";
import { CadenceCard } from "./cadence-card";
import { createClient } from "@/lib/supabase/client";

interface CadenceListProps {
  cadences: Cadence[];
}

export function CadenceList({ cadences }: CadenceListProps) {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [enrollmentData, setEnrollmentData] = useState<Record<string, { active: number; responded: number; exhausted: number; completed: number }>>({});
  const [stepsData, setStepsData] = useState<Record<string, number>>({});

  useEffect(() => {
    const supabase = createClient();

    async function loadCounts() {
      const { data: enrollments } = await supabase
        .from("cadence_enrollments")
        .select("cadence_id, status");

      const { data: steps } = await supabase
        .from("cadence_steps")
        .select("cadence_id");

      if (enrollments) {
        const counts: typeof enrollmentData = {};
        for (const e of enrollments) {
          if (!counts[e.cadence_id]) counts[e.cadence_id] = { active: 0, responded: 0, exhausted: 0, completed: 0 };
          const s = e.status as keyof typeof counts[string];
          if (s in counts[e.cadence_id]) counts[e.cadence_id][s]++;
        }
        setEnrollmentData(counts);
      }

      if (steps) {
        const sc: Record<string, number> = {};
        for (const s of steps) {
          sc[s.cadence_id] = (sc[s.cadence_id] || 0) + 1;
        }
        setStepsData(sc);
      }
    }

    loadCounts();
  }, [cadences]);

  const filtered = cadences.filter((c) => {
    if (filter !== "all" && c.status !== filter) return false;
    if (search && !c.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const filters = [
    { key: "all", label: "Todas" },
    { key: "active", label: "Ativas" },
    { key: "paused", label: "Pausadas" },
    { key: "archived", label: "Arquivadas" },
  ];

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Buscar cadencia..."
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
        <p className="text-[13px] text-[#9ca3af] text-center py-12">Nenhuma cadencia encontrada</p>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {filtered.map((c) => (
            <CadenceCard
              key={c.id}
              cadence={c}
              enrollmentCounts={enrollmentData[c.id]}
              stepsCount={stepsData[c.id]}
            />
          ))}
        </div>
      )}
    </div>
  );
}
