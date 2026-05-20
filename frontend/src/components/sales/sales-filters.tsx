"use client";

import { useEffect, useState } from "react";
import type { TeamUser } from "@/lib/types";
import type { SalesFilters } from "@/hooks/use-sales";

interface SalesFiltersProps {
  filters: SalesFilters;
  onChange: (f: SalesFilters) => void;
}

function startOfMonth(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
}
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function SalesFiltersBar({ filters, onChange }: SalesFiltersProps) {
  const [users, setUsers] = useState<TeamUser[]>([]);

  useEffect(() => {
    fetch("/api/users")
      .then((r) => r.json())
      .then((data) => setUsers(Array.isArray(data) ? data : []));
  }, []);

  return (
    <div className="flex flex-wrap gap-3 items-end">
      <div>
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">De</label>
        <input
          type="date"
          value={filters.from ?? startOfMonth()}
          onChange={(e) => onChange({ ...filters, from: e.target.value, page: 1 })}
          className="bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
        />
      </div>
      <div>
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Até</label>
        <input
          type="date"
          value={filters.to ?? today()}
          onChange={(e) => onChange({ ...filters, to: e.target.value, page: 1 })}
          className="bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
        />
      </div>
      <div>
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Vendedor</label>
        <select
          value={filters.soldBy ?? ""}
          onChange={(e) => onChange({ ...filters, soldBy: e.target.value || undefined, page: 1 })}
          className="bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
        >
          <option value="">Todos</option>
          {users.map((u) => (
            <option key={u.id} value={u.email}>{u.name || u.email}</option>
          ))}
        </select>
      </div>
      <div className="flex-1 min-w-[200px]">
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Buscar produto</label>
        <input
          type="text"
          value={filters.search ?? ""}
          onChange={(e) => onChange({ ...filters, search: e.target.value || undefined, page: 1 })}
          placeholder="Ex: Café especial"
          className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
        />
      </div>
    </div>
  );
}
