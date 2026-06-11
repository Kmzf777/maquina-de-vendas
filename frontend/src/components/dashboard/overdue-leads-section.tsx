"use client";

import { useState } from "react";
import Link from "next/link";
import { useOverdueLeads, type OverdueLead } from "@/hooks/use-overdue-leads";
import { formatBusinessDuration } from "@/lib/business-hours";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Sentinel para "todos" — Radix Select não aceita value vazio ("").
const ALL = "__all__";

function SkeletonRow() {
  return <div className="animate-pulse bg-[#dedbd6]/40 rounded-[8px] h-12" />;
}

export function OverdueLeadsSection() {
  const { leads, vendedores, isAdmin, loading } = useOverdueLeads();
  // Filtro por vendedor (admin), pelo userId — robusto a nomes repetidos.
  const [vendedorFilter, setVendedorFilter] = useState<string>(""); // "" = todos

  const visible: OverdueLead[] =
    isAdmin && vendedorFilter
      ? leads.filter((l) => l.userId === vendedorFilter)
      : leads;

  return (
    <div className="mb-8">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Em atraso agora
          </p>
          <span
            className={`text-[12px] font-medium px-2 py-0.5 rounded-[4px] ${
              visible.length > 0
                ? "bg-[#c41c1c]/10 text-[#c41c1c]"
                : "bg-[#dedbd6]/40 text-[#7b7b78]"
            }`}
          >
            {visible.length}
          </span>
        </div>
        {isAdmin && vendedores.length > 0 && (
          <Select
            value={vendedorFilter === "" ? ALL : vendedorFilter}
            onValueChange={(v) => setVendedorFilter(v === ALL ? "" : v)}
          >
            <SelectTrigger className="h-7 w-[180px] text-[13px] border-[#dedbd6] bg-white rounded-[6px] text-[#111111] focus:ring-0 focus:ring-offset-0">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="text-[13px]">
              <SelectItem value={ALL}>Todos os vendedores</SelectItem>
              {vendedores.map((v) => (
                <SelectItem key={v.userId} value={v.userId}>
                  {v.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
        {loading ? (
          <div className="p-3 space-y-2">
            <SkeletonRow />
            <SkeletonRow />
            <SkeletonRow />
          </div>
        ) : visible.length === 0 ? (
          <div className="px-4 py-8 text-center text-[14px] text-[#7b7b78]">
            Nenhum lead em atraso agora.
          </div>
        ) : (
          <ul className="divide-y divide-[#f0ede8]">
            {visible.map((l) => (
              <li
                key={l.conversationId}
                className="flex items-center gap-3 px-4 py-3"
              >
                <span
                  className="w-2 h-2 rounded-full bg-[#c41c1c] flex-shrink-0"
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] text-[#111111] truncate">
                    {l.leadName}
                  </p>
                  {isAdmin && (
                    <p className="text-[12px] text-[#7b7b78] truncate">
                      {l.vendedorName}
                    </p>
                  )}
                </div>
                <span className="text-[14px] text-[#c41c1c] font-medium whitespace-nowrap">
                  {formatBusinessDuration(l.elapsedMinutes)}
                </span>
                <Link
                  href={`/conversas?lead_id=${l.leadId}`}
                  className="bg-[#111111] text-white px-[12px] py-1.5 rounded-[4px] text-[13px] whitespace-nowrap transition-transform hover:scale-105 active:scale-[0.95]"
                >
                  Abrir conversa
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
