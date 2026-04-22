"use client";

import { useState, useEffect, useCallback } from "react";
import { KpiCard } from "@/components/kpi-card";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell,
} from "recharts";

const API_BASE = "";

const PERIOD_OPTIONS = [
  { label: "Hoje", days: 1 },
  { label: "7 dias", days: 7 },
  { label: "30 dias", days: 30 },
];

const STAGE_COLORS: Record<string, string> = {
  secretaria: "#dedbd6",
  atacado: "#111111",
  private_label: "#7b7b78",
  exportacao: "#0bdf50",
  consumo: "#ff5600",
};

const MODEL_COLORS: Record<string, string> = {
  "gpt-4.1": "#111111",
  "gpt-4.1-mini": "#7b7b78",
  "gpt-4o": "#dedbd6",
  "whisper-1": "#0bdf50",
};

const DollarIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M10 2v16M14 5.5H8.5a2.5 2.5 0 000 5h3a2.5 2.5 0 010 5H6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const CallsIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const TokensIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.8" />
    <path d="M8 8h4M8 12h4M10 6v8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);
const AvgIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="7.5" cy="7" r="2.5" stroke="currentColor" strokeWidth="1.8" />
    <path d="M2.5 16c0-2.5 2-4.5 5-4.5s5 2 5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    <path d="M15 6v6M12 9h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

function formatUSD(value: number): string {
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return `${d.getDate()}/${d.getMonth() + 1}`;
}

interface CostSummary {
  total_cost: number;
  total_calls: number;
  total_tokens: number;
  avg_cost_per_lead: number;
  unique_leads: number;
}

interface DailyData {
  date: string;
  cost: number;
}

interface BreakdownItem {
  key: string;
  cost: number;
  calls: number;
  tokens: number;
}

interface TopLead {
  lead_id: string;
  name: string;
  phone: string;
  stage: string;
  cost: number;
  calls: number;
  tokens: number;
}

export default function EstatisticasPage() {
  const [selectedPeriod, setSelectedPeriod] = useState(30);
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [daily, setDaily] = useState<DailyData[]>([]);
  const [byStage, setByStage] = useState<BreakdownItem[]>([]);
  const [byModel, setByModel] = useState<BreakdownItem[]>([]);
  const [topLeads, setTopLeads] = useState<TopLead[]>([]);
  const [loading, setLoading] = useState(true);

  const getDateRange = useCallback(() => {
    if (customStart && customEnd) {
      return { start_date: customStart, end_date: customEnd };
    }
    const end = new Date();
    end.setDate(end.getDate() + 1);
    const start = new Date();
    start.setDate(start.getDate() - selectedPeriod);
    return {
      start_date: start.toISOString().slice(0, 10),
      end_date: end.toISOString().slice(0, 10),
    };
  }, [selectedPeriod, customStart, customEnd]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    const { start_date, end_date } = getDateRange();
    const params = `start_date=${start_date}&end_date=${end_date}`;

    try {
      const [summaryRes, dailyRes, stageRes, modelRes, leadsRes] = await Promise.all([
        fetch(`${API_BASE}/api/stats/costs?${params}`),
        fetch(`${API_BASE}/api/stats/costs/daily?${params}`),
        fetch(`${API_BASE}/api/stats/costs/breakdown?${params}&group_by=stage`),
        fetch(`${API_BASE}/api/stats/costs/breakdown?${params}&group_by=model`),
        fetch(`${API_BASE}/api/stats/costs/top-leads?${params}&limit=20`),
      ]);

      const [summaryData, dailyData, stageData, modelData, leadsData] = await Promise.all([
        summaryRes.json(),
        dailyRes.json(),
        stageRes.json(),
        modelRes.json(),
        leadsRes.json(),
      ]);

      setSummary(summaryData);
      setDaily(dailyData.data);
      setByStage(stageData.data);
      setByModel(modelData.data);
      setTopLeads(leadsData.data);
    } catch (e) {
      console.error("Failed to fetch stats:", e);
    } finally {
      setLoading(false);
    }
  }, [getDateRange]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0">
          <div className="h-8 w-48 rounded-[4px] animate-pulse bg-[#dedbd6]" />
          <div className="h-4 w-72 rounded-[4px] animate-pulse mt-2 bg-[#dedbd6]" />
        </div>
        <div className="p-8 flex-1 bg-[#faf9f6]">
          <div className="grid grid-cols-4 gap-5">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="bg-white border border-[#dedbd6] rounded-[8px] p-5 h-28 animate-pulse" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Page Header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0 flex items-end justify-between">
        <div>
          <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111]">
            Tokens AI
          </h1>
          <p className="text-[14px] text-[#7b7b78] mt-0.5">
            Uso de tokens por modelo
          </p>
        </div>

        {/* Period Filter */}
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {PERIOD_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                onClick={() => { setSelectedPeriod(opt.days); setCustomStart(""); setCustomEnd(""); }}
                className={selectedPeriod === opt.days && !customStart
                  ? "bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                  : "bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1.5 ml-2">
            <input
              type="date"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
            />
            <span className="text-[14px] text-[#7b7b78]">a</span>
            <input
              type="date"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
            />
          </div>
        </div>
      </div>

      <div className="p-8 overflow-auto flex-1 bg-[#faf9f6]">
        {/* KPI Cards */}
        <div className="grid grid-cols-4 gap-5 mb-8">
          <KpiCard label="Custo Total" value={formatUSD(summary?.total_cost ?? 0)} icon={DollarIcon} />
          <KpiCard label="Chamadas API" value={summary?.total_calls ?? 0} icon={CallsIcon} />
          <KpiCard label="Tokens Consumidos" value={(summary?.total_tokens ?? 0).toLocaleString()} icon={TokensIcon} />
          <KpiCard
            label="Custo Medio/Lead"
            value={formatUSD(summary?.avg_cost_per_lead ?? 0)}
            subtitle={`${summary?.unique_leads ?? 0} leads`}
            icon={AvgIcon}
          />
        </div>

        {/* Daily Cost Line Chart */}
        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5 mb-8">
          <h2 className="text-[14px] font-normal text-[#111111] mb-4">
            Custo Diario (USD)
          </h2>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={daily}>
              <CartesianGrid strokeDasharray="3 3" stroke="#dedbd6" />
              <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 12, fill: "#7b7b78" }} />
              <YAxis tick={{ fontSize: 12, fill: "#7b7b78" }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
              <Tooltip
                formatter={(value) => [`$${Number(value).toFixed(4)}`, "Custo"]}
                labelFormatter={(label) => formatDate(String(label))}
              />
              <Line type="monotone" dataKey="cost" stroke="#111111" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Breakdown Charts */}
        <div className="grid grid-cols-2 gap-5 mb-8">
          {/* By Stage */}
          <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
            <h2 className="text-[14px] font-normal text-[#111111] mb-4">
              Custo por Stage
            </h2>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={byStage}>
                <CartesianGrid strokeDasharray="3 3" stroke="#dedbd6" />
                <XAxis dataKey="key" tick={{ fontSize: 12, fill: "#7b7b78" }} />
                <YAxis tick={{ fontSize: 12, fill: "#7b7b78" }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
                <Tooltip formatter={(value) => [`$${Number(value).toFixed(4)}`, "Custo"]} />
                <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
                  {byStage.map((entry) => (
                    <Cell key={entry.key} fill={STAGE_COLORS[entry.key] || "#7b7b78"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* By Model */}
          <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
            <h2 className="text-[14px] font-normal text-[#111111] mb-4">
              Custo por Modelo
            </h2>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={byModel}>
                <CartesianGrid strokeDasharray="3 3" stroke="#dedbd6" />
                <XAxis dataKey="key" tick={{ fontSize: 12, fill: "#7b7b78" }} />
                <YAxis tick={{ fontSize: 12, fill: "#7b7b78" }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
                <Tooltip formatter={(value) => [`$${Number(value).toFixed(4)}`, "Custo"]} />
                <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
                  {byModel.map((entry) => (
                    <Cell key={entry.key} fill={MODEL_COLORS[entry.key] || "#7b7b78"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Top Leads Table */}
        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
          <h2 className="text-[14px] font-normal text-[#111111] mb-4">
            Top Leads por Custo
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[#dedbd6]">
                  <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Lead</th>
                  <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Stage</th>
                  <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-right font-normal">Chamadas</th>
                  <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-right font-normal">Tokens</th>
                  <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-right font-normal">Custo</th>
                </tr>
              </thead>
              <tbody>
                {topLeads.map((lead) => (
                  <tr key={lead.lead_id} className="border-b border-[#dedbd6] hover:bg-[#faf9f6] transition-colors">
                    <td className="px-4 py-3">
                      <div className="text-[14px] text-[#111111]">{lead.name}</div>
                      {lead.phone && (
                        <div className="text-[12px] text-[#7b7b78]">{lead.phone}</div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className="bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]">
                        {lead.stage}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-[14px] text-[#7b7b78]">{lead.calls}</td>
                    <td className="px-4 py-3 text-right text-[14px] text-[#7b7b78]">{lead.tokens.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right text-[14px] font-normal text-[#111111]">{formatUSD(lead.cost)}</td>
                  </tr>
                ))}
                {topLeads.length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-[14px] text-[#7b7b78]">
                      Nenhum dado de custo encontrado para o periodo selecionado
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
