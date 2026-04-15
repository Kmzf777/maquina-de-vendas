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
  secretaria: "#c8cc8e",
  atacado: "#5b8aad",
  private_label: "#9b7abf",
  exportacao: "#5aad65",
  consumo: "#d4b84a",
};

const MODEL_COLORS: Record<string, string> = {
  "gpt-4.1": "#5b8aad",
  "gpt-4.1-mini": "#c8cc8e",
  "gpt-4o": "#9b7abf",
  "whisper-1": "#d4b84a",
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
      <div className="space-y-6">
        <div>
          <div className="h-8 w-48 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
          <div className="h-4 w-72 rounded-lg animate-pulse mt-2" style={{ backgroundColor: "#e5e5dc" }} />
        </div>
        <div className="grid grid-cols-4 gap-5">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card p-5 h-28 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-[28px] font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
            Estatisticas
          </h1>
          <p className="text-[14px] mt-1" style={{ color: "var(--text-muted)" }}>
            Custos e consumo do agente de IA
          </p>
        </div>

        {/* Period Filter */}
        <div className="flex items-center gap-2">
          <nav className="inline-flex gap-1 p-1 bg-[#f6f7ed] rounded-xl">
            {PERIOD_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                onClick={() => { setSelectedPeriod(opt.days); setCustomStart(""); setCustomEnd(""); }}
                className={`px-4 py-2 text-[13px] font-medium rounded-lg transition-all ${
                  selectedPeriod === opt.days && !customStart
                    ? "bg-[#1f1f1f] text-white shadow-sm"
                    : "text-[#5f6368] hover:text-[#1f1f1f] hover:bg-white/60"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </nav>
          <div className="flex items-center gap-1.5 ml-2">
            <input
              type="date"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
              className="px-3 py-2 text-[13px] rounded-lg border border-[#e0e0d8] bg-white"
            />
            <span className="text-[13px] text-[#5f6368]">a</span>
            <input
              type="date"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
              className="px-3 py-2 text-[13px] rounded-lg border border-[#e0e0d8] bg-white"
            />
          </div>
        </div>
      </div>

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
      <div className="card p-6 mb-8">
        <h2 className="text-[15px] font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
          Custo Diario (USD)
        </h2>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={daily}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e5dc" />
            <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 12, fill: "#8a8a8a" }} />
            <YAxis tick={{ fontSize: 12, fill: "#8a8a8a" }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
            <Tooltip
              formatter={(value) => [`$${Number(value).toFixed(4)}`, "Custo"]}
              labelFormatter={(label) => formatDate(String(label))}
            />
            <Line type="monotone" dataKey="cost" stroke="#6b8e5a" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Breakdown Charts */}
      <div className="grid grid-cols-2 gap-5 mb-8">
        {/* By Stage */}
        <div className="card p-6">
          <h2 className="text-[15px] font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            Custo por Stage
          </h2>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={byStage}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5dc" />
              <XAxis dataKey="key" tick={{ fontSize: 12, fill: "#8a8a8a" }} />
              <YAxis tick={{ fontSize: 12, fill: "#8a8a8a" }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
              <Tooltip formatter={(value) => [`$${Number(value).toFixed(4)}`, "Custo"]} />
              <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
                {byStage.map((entry) => (
                  <Cell key={entry.key} fill={STAGE_COLORS[entry.key] || "#8a8a8a"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* By Model */}
        <div className="card p-6">
          <h2 className="text-[15px] font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            Custo por Modelo
          </h2>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={byModel}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5dc" />
              <XAxis dataKey="key" tick={{ fontSize: 12, fill: "#8a8a8a" }} />
              <YAxis tick={{ fontSize: 12, fill: "#8a8a8a" }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
              <Tooltip formatter={(value) => [`$${Number(value).toFixed(4)}`, "Custo"]} />
              <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
                {byModel.map((entry) => (
                  <Cell key={entry.key} fill={MODEL_COLORS[entry.key] || "#8a8a8a"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top Leads Table */}
      <div className="card p-6">
        <h2 className="text-[15px] font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
          Top Leads por Custo
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#e5e5dc]">
                <th className="text-left text-[12px] font-medium text-[#8a8a8a] uppercase tracking-wider pb-3 pl-2">Lead</th>
                <th className="text-left text-[12px] font-medium text-[#8a8a8a] uppercase tracking-wider pb-3">Stage</th>
                <th className="text-right text-[12px] font-medium text-[#8a8a8a] uppercase tracking-wider pb-3">Chamadas</th>
                <th className="text-right text-[12px] font-medium text-[#8a8a8a] uppercase tracking-wider pb-3">Tokens</th>
                <th className="text-right text-[12px] font-medium text-[#8a8a8a] uppercase tracking-wider pb-3 pr-2">Custo</th>
              </tr>
            </thead>
            <tbody>
              {topLeads.map((lead) => (
                <tr key={lead.lead_id} className="border-b border-[#f0f0e8] hover:bg-[#fafaf5] transition-colors">
                  <td className="py-3 pl-2">
                    <div className="text-[13px] font-medium" style={{ color: "var(--text-primary)" }}>{lead.name}</div>
                    {lead.phone && (
                      <div className="text-[12px]" style={{ color: "var(--text-muted)" }}>{lead.phone}</div>
                    )}
                  </td>
                  <td className="py-3">
                    <span className="text-[12px] font-medium px-2.5 py-1 rounded-full" style={{
                      backgroundColor: `${STAGE_COLORS[lead.stage] || "#8a8a8a"}20`,
                      color: STAGE_COLORS[lead.stage] || "#8a8a8a",
                    }}>
                      {lead.stage}
                    </span>
                  </td>
                  <td className="py-3 text-right text-[13px]" style={{ color: "var(--text-secondary)" }}>{lead.calls}</td>
                  <td className="py-3 text-right text-[13px]" style={{ color: "var(--text-secondary)" }}>{lead.tokens.toLocaleString()}</td>
                  <td className="py-3 text-right text-[13px] font-medium pr-2" style={{ color: "var(--text-primary)" }}>{formatUSD(lead.cost)}</td>
                </tr>
              ))}
              {topLeads.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-[13px]" style={{ color: "var(--text-muted)" }}>
                    Nenhum dado de custo encontrado para o periodo selecionado
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
