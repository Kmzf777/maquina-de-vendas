"use client";

import { useState, useEffect, useCallback } from "react";
import type { ReactNode } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

const API_BASE = "";
const MARKETING_PRICE = 0.0617;
const UTILITY_PRICE = 0.0067;

const PERIOD_OPTIONS = [
  { label: "Hoje", days: 1 },
  { label: "7 dias", days: 7 },
  { label: "30 dias", days: 30 },
];

function formatUSD(value: number): string {
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return `${d.getDate()}/${d.getMonth() + 1}`;
}

interface WhatsappSummary {
  marketing_count: number;
  marketing_cost: number;
  utility_count: number;
  utility_cost: number;
  total_whatsapp_cost: number;
  truncated?: boolean;
}

interface AISummary {
  total_cost: number;
  total_calls: number;
  total_tokens: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
}

interface DailyAI {
  date: string;
  cost: number;
}

interface DailyWA {
  date: string;
  marketing_cost: number;
  utility_cost: number;
  total: number;
}

interface CombinedDaily {
  date: string;
  marketing: number;
  utility: number;
  ia: number;
}

export default function EstatisticasPage() {
  const [selectedPeriod, setSelectedPeriod] = useState(1);
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [appliedCustomStart, setAppliedCustomStart] = useState("");
  const [appliedCustomEnd, setAppliedCustomEnd] = useState("");

  const [whatsapp, setWhatsapp] = useState<WhatsappSummary | null>(null);
  const [ai, setAi] = useState<AISummary | null>(null);
  const [dailyData, setDailyData] = useState<CombinedDaily[]>([]);
  const [loading, setLoading] = useState(true);

  const getDateRange = useCallback(() => {
    if (appliedCustomStart && appliedCustomEnd) {
      return { start_date: appliedCustomStart, end_date: appliedCustomEnd };
    }
    const end = new Date();
    end.setDate(end.getDate() + 1);
    const start = new Date();
    start.setDate(start.getDate() - selectedPeriod);
    return {
      start_date: start.toISOString().slice(0, 10),
      end_date: end.toISOString().slice(0, 10),
    };
  }, [selectedPeriod, appliedCustomStart, appliedCustomEnd]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    const { start_date, end_date } = getDateRange();
    const params = `start_date=${start_date}&end_date=${end_date}`;

    try {
      const [aiRes, waRes, aiDailyRes, waDailyRes] = await Promise.all([
        fetch(`${API_BASE}/api/stats/costs?${params}`),
        fetch(`${API_BASE}/api/stats/whatsapp?${params}`),
        fetch(`${API_BASE}/api/stats/costs/daily?${params}`),
        fetch(`${API_BASE}/api/stats/whatsapp/daily?${params}`),
      ]);

      const responses = [
        { name: "costs", res: aiRes },
        { name: "whatsapp", res: waRes },
        { name: "costs/daily", res: aiDailyRes },
        { name: "whatsapp/daily", res: waDailyRes },
      ];
      const failed = responses.filter((r) => !r.res.ok);
      if (failed.length > 0) {
        const details = failed
          .map((r) => `${r.name} → HTTP ${r.res.status}`)
          .join(", ");
        throw new Error(`stats fetch failed: ${details}`);
      }
      const [aiData, waData, aiDailyData, waDailyData] = await Promise.all([
        aiRes.json(),
        waRes.json(),
        aiDailyRes.json(),
        waDailyRes.json(),
      ]);

      setAi(aiData);
      setWhatsapp(waData);

      const aiByDate: Record<string, number> = {};
      for (const d of (aiDailyData?.data ?? []) as DailyAI[]) {
        aiByDate[d.date] = d.cost;
      }

      const waByDate: Record<string, DailyWA> = {};
      for (const d of (waDailyData?.data ?? []) as DailyWA[]) {
        waByDate[d.date] = d;
      }

      // Union of all dates from both series
      const allDates = Array.from(
        new Set([
          ...Object.keys(waByDate),
          ...Object.keys(aiByDate),
        ])
      ).sort();

      const combined: CombinedDaily[] = allDates.map((date) => ({
        date,
        marketing: waByDate[date]?.marketing_cost ?? 0,
        utility: waByDate[date]?.utility_cost ?? 0,
        ia: aiByDate[date] ?? 0,
      }));

      setDailyData(combined);
    } catch (e) {
      console.error("Failed to fetch stats:", e);
    } finally {
      setLoading(false);
    }
  }, [getDateRange]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const totalCost =
    (whatsapp?.total_whatsapp_cost ?? 0) + (ai?.total_cost ?? 0);

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0">
          <Skeleton className="h-8 w-48 rounded-[4px]" />
          <Skeleton className="h-4 w-72 rounded-[4px] mt-2" />
        </div>
        <div className="p-8 flex-1 bg-[#faf9f6] space-y-6">
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-28 rounded-[8px]" />
            ))}
          </div>
          <Skeleton className="h-72 rounded-[8px]" />
          <Skeleton className="h-48 rounded-[8px]" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <Alert className="rounded-none border-x-0 border-t-0 border-b border-amber-200 bg-amber-50 py-2.5 px-8 text-amber-800">
        <AlertDescription className="text-xs">
          Todos os valores estão em dólar americano (USD) — moeda de cobrança da Meta e dos modelos de IA.
        </AlertDescription>
      </Alert>

      {/* Header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1
            style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }}
            className="text-[32px] font-normal text-[#111111]"
          >
            Custos Operacionais
          </h1>
          <p className="text-[14px] text-[#7b7b78] mt-0.5">WhatsApp + IA</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            {PERIOD_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                onClick={() => {
                  setSelectedPeriod(opt.days);
                  setCustomStart("");
                  setCustomEnd("");
                  setAppliedCustomStart("");
                  setAppliedCustomEnd("");
                }}
                className={
                  selectedPeriod === opt.days && !customStart
                    ? "bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                    : "bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                }
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1.5">
            <input
              type="date"
              value={customStart}
              onChange={(e) => {
                setCustomStart(e.target.value);
                if (e.target.value.length === 10 && customEnd.length === 10) {
                  setAppliedCustomStart(e.target.value);
                  setAppliedCustomEnd(customEnd);
                }
              }}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
            />
            <span className="text-[14px] text-[#7b7b78]">a</span>
            <input
              type="date"
              value={customEnd}
              onChange={(e) => {
                setCustomEnd(e.target.value);
                if (customStart.length === 10 && e.target.value.length === 10) {
                  setAppliedCustomStart(customStart);
                  setAppliedCustomEnd(e.target.value);
                }
              }}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
            />
          </div>
        </div>
      </div>

      <div className="p-6 md:p-8 overflow-auto flex-1 bg-[#faf9f6] space-y-6">
        {/* Summary Cards */}
        <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
          <Card className="border-[#dedbd6] rounded-[8px] ring-0 shadow-none">
            <CardHeader className="pb-1 pt-4 px-5">
              <CardTitle className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal">
                Marketing WPP
              </CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-4">
              <p className="text-[24px] font-normal text-[#111111] leading-none">
                {formatUSD(whatsapp?.marketing_cost ?? 0)}
              </p>
              <p className="text-[12px] text-[#7b7b78] mt-1">
                {whatsapp?.marketing_count ?? 0} msgs · ${MARKETING_PRICE}/msg
              </p>
            </CardContent>
          </Card>

          <Card className="border-[#dedbd6] rounded-[8px] ring-0 shadow-none">
            <CardHeader className="pb-1 pt-4 px-5">
              <CardTitle className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal">
                Utilidade WPP
              </CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-4">
              <p className="text-[24px] font-normal text-[#111111] leading-none">
                {formatUSD(whatsapp?.utility_cost ?? 0)}
              </p>
              <p className="text-[12px] text-[#7b7b78] mt-1">
                {whatsapp?.utility_count ?? 0} msgs · ${UTILITY_PRICE}/msg
              </p>
            </CardContent>
          </Card>

          <Card className="border-[#dedbd6] rounded-[8px] ring-0 shadow-none">
            <CardHeader className="pb-1 pt-4 px-5">
              <CardTitle className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal">
                LLM / IA
              </CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-4">
              <p className="text-[24px] font-normal text-[#111111] leading-none">
                {formatUSD(ai?.total_cost ?? 0)}
              </p>
              <p className="text-[12px] text-[#7b7b78] mt-1">
                {ai?.total_calls ?? 0} chamadas ·{" "}
                {(ai?.total_tokens ?? 0).toLocaleString()} tokens
              </p>
            </CardContent>
          </Card>

          <Card className="border-transparent rounded-[8px] bg-[#111111] ring-0 shadow-none">
            <CardHeader className="pb-1 pt-4 px-5">
              <CardTitle className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal">
                Total Operacional
              </CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-4">
              <p className="text-[24px] font-normal text-white leading-none">
                {formatUSD(totalCost)}
              </p>
              <p className="text-[12px] text-[#7b7b78] mt-1">WPP + IA</p>
            </CardContent>
          </Card>
        </div>

        {whatsapp?.truncated && (
          <p className="text-[12px] text-[#ff5600]">
            ⚠ Período com mais de 10.000 disparos — valores exibidos são um limite inferior.
          </p>
        )}

        {/* Daily Cost Chart */}
        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
          <h2 className="text-[14px] font-normal text-[#111111] mb-4">
            Custo Diário (USD)
          </h2>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={dailyData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#dedbd6" />
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                tick={{ fontSize: 12, fill: "#7b7b78" }}
              />
              <YAxis
                tick={{ fontSize: 12, fill: "#7b7b78" }}
                tickFormatter={(v: number) => `$${v.toFixed(2)}`}
              />
              <Tooltip
                formatter={(value: number | string | ReadonlyArray<number | string> | undefined, name: number | string | undefined) => [
                  `$${Number(value ?? 0).toFixed(4)}`,
                  name === "marketing"
                    ? "Marketing WPP"
                    : name === "utility"
                    ? "Utilidade WPP"
                    : "IA",
                ]}
                labelFormatter={(label: ReactNode) => formatDate(String(label ?? ""))}
              />
              <Legend
                formatter={(value: string) =>
                  value === "marketing"
                    ? "Marketing WPP"
                    : value === "utility"
                    ? "Utilidade WPP"
                    : "IA"
                }
              />
              <Line
                type="monotone"
                dataKey="marketing"
                stroke="#111111"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="utility"
                stroke="#0bdf50"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="ia"
                stroke="#7b7b78"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Details Table */}
        <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="border-[#dedbd6] hover:bg-transparent">
                <TableHead className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal h-10">
                  Categoria
                </TableHead>
                <TableHead className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal text-right h-10">
                  Qtd.
                </TableHead>
                <TableHead className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal text-right h-10">
                  Tokens / Chamadas
                </TableHead>
                <TableHead className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-normal text-right h-10">
                  Custo
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow className="border-[#dedbd6] hover:bg-[#faf9f6]">
                <TableCell className="text-[14px] text-[#111111] py-3">
                  Marketing WhatsApp
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  {whatsapp?.marketing_count ?? 0} msgs
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  —
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] py-3">
                  {formatUSD(whatsapp?.marketing_cost ?? 0)}
                </TableCell>
              </TableRow>

              <TableRow className="border-[#dedbd6] hover:bg-[#faf9f6]">
                <TableCell className="text-[14px] text-[#111111] py-3">
                  Utilidade WhatsApp
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  {whatsapp?.utility_count ?? 0} msgs
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  —
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] py-3">
                  {formatUSD(whatsapp?.utility_cost ?? 0)}
                </TableCell>
              </TableRow>

              <TableRow className="border-[#dedbd6] hover:bg-[#faf9f6]">
                <TableCell className="text-[14px] text-[#111111] py-3">
                  LLM / IA
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  {ai?.total_calls ?? 0} chamadas
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] py-3">
                  {(ai?.total_tokens ?? 0).toLocaleString()}
                  {ai && (
                    <span className="text-[11px] ml-1">
                      ({ai.total_prompt_tokens.toLocaleString()} in /{" "}
                      {ai.total_completion_tokens.toLocaleString()} out)
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] py-3">
                  {formatUSD(ai?.total_cost ?? 0)}
                </TableCell>
              </TableRow>

              <TableRow className="bg-[#faf9f6] hover:bg-[#faf9f6] border-0">
                <TableCell className="text-[14px] font-medium text-[#111111] py-3">
                  Total
                </TableCell>
                <TableCell />
                <TableCell />
                <TableCell className="text-right text-[14px] font-medium text-[#111111] py-3">
                  {formatUSD(totalCost)}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
