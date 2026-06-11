"use client";

import { useState } from "react";
import { useSlaStats, type DateFilter } from "@/hooks/use-sla-stats";
import { formatBusinessDuration } from "@/lib/business-hours";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const DATE_FILTER_OPTIONS: { value: DateFilter; label: string }[] = [
  { value: "1d", label: "Hoje" },
  { value: "7d", label: "7 dias" },
  { value: "30d", label: "30 dias" },
  { value: "all", label: "Tudo" },
];

function dur(m: number | null): string {
  return m !== null ? formatBusinessDuration(m) : "—";
}

export function SlaTable() {
  const [filter, setFilter] = useState<DateFilter>("7d");
  const { rows, total, loading } = useSlaStats(filter);

  return (
    <div className="mb-8">
      <div className="flex items-center justify-between mb-4">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
          SLA — Resposta por vendedor
        </p>
        <Select value={filter} onValueChange={(v) => setFilter(v as DateFilter)}>
          <SelectTrigger className="h-7 w-[110px] text-[13px] border-[#dedbd6] bg-white rounded-[6px] text-[#111111] focus:ring-0 focus:ring-offset-0">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="text-[13px]">
            {DATE_FILTER_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
        <table className="w-full text-[14px]">
          <thead>
            <tr className="border-b border-[#dedbd6] text-[#7b7b78] text-[12px] uppercase tracking-[0.4px]">
              <th className="text-left font-normal px-4 py-3">Vendedor</th>
              <th className="text-right font-normal px-4 py-3">Média resp.</th>
              <th className="text-right font-normal px-4 py-3">Em atraso agora</th>
              <th className="text-right font-normal px-4 py-3">Pior SLA</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-[#7b7b78]">Carregando…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-[#7b7b78]">Nenhum vendedor configurado.</td></tr>
            ) : (
              rows.map((r) => (
                <tr key={r.userId} className="border-b border-[#f0ede8] last:border-0">
                  <td className="px-4 py-3 text-[#111111]">{r.displayName}</td>
                  <td className="px-4 py-3 text-right text-[#111111]">{dur(r.avgMinutes)}</td>
                  <td className={`px-4 py-3 text-right font-medium ${r.overdueCount > 0 ? "text-[#c41c1c]" : "text-[#111111]"}`}>
                    {r.overdueCount}
                  </td>
                  <td className="px-4 py-3 text-right text-[#111111]">{dur(r.worstMinutes)}</td>
                </tr>
              ))
            )}
          </tbody>
          {!loading && rows.length > 0 && (
            <tfoot>
              <tr className="border-t border-[#dedbd6] bg-[#faf9f6] font-medium">
                <td className="px-4 py-3 text-[#111111]">Total</td>
                <td className="px-4 py-3 text-right text-[#111111]">{dur(total.avgMinutes)}</td>
                <td className={`px-4 py-3 text-right ${total.overdueCount > 0 ? "text-[#c41c1c]" : "text-[#111111]"}`}>
                  {total.overdueCount}
                </td>
                <td className="px-4 py-3 text-right text-[#111111]">{dur(total.worstMinutes)}</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
