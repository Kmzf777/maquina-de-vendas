"use client";

// Página admin "Relatório Campanhas" (/trafego): rastreio de campanhas e leads x vendas registradas.
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useCurrentRole } from "@/hooks/use-current-role";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { CampaignReportTable, type CampaignRow, type ReportTotal, type ChannelSubtotals } from "@/components/trafego/campaign-report-table";

type Report = { mode: string; period: string; rows: CampaignRow[]; total: ReportTotal; channel_subtotals: ChannelSubtotals };

export default function TrafegoPage() {
  const { role, loading: roleLoading } = useCurrentRole();
  const [period, setPeriod] = useState("30d");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [dateMode, setDateMode] = useState<"preset" | "mes" | "custom">("preset");
  const [mode, setMode] = useState<"lead" | "sale">("lead");
  const router = useRouter();
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);

  // handler do seletor de mês (YYYY-MM) → converte p/ from/to do 1º ao último dia
  const onMonth = (ym: string) => {
    if (!ym) { setDateFrom(""); setDateTo(""); return; }
    const [y, m] = ym.split("-").map(Number);
    const last = new Date(y, m, 0).getDate();
    setDateFrom(`${ym}-01`);
    setDateTo(`${ym}-${String(last).padStart(2, "0")}`);
  };

  useEffect(() => {
    if (roleLoading || role !== "admin") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    const q = (dateFrom || dateTo)
      ? `mode=${mode}${dateFrom ? `&date_from=${dateFrom}` : ""}${dateTo ? `&date_to=${dateTo}` : ""}`
      : `period=${period}&mode=${mode}`;
    fetch(`/api/traffic/report?${q}`)
      .then(r => r.json())
      .then((d: Report) => setReport(d))
      .catch(() => setReport(null))
      .finally(() => setLoading(false));
  }, [period, mode, dateFrom, dateTo, role, roleLoading]);

  if (!roleLoading && role !== "admin") {
    return <div className="p-8 text-[14px] text-[#7b7b78]">Acesso restrito a administradores.</div>;
  }

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-4 md:py-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between flex-shrink-0">
        <div>
          <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[24px] md:text-[32px] font-normal text-[#111111]">
            Relatório Campanhas
          </h1>
          <p className="text-[13px] md:text-[14px] text-[#7b7b78] mt-0.5">
            Rastreio de campanhas e leads por origem, cruzado com vendas registradas
          </p>
        </div>
        <div className="flex items-center gap-4 flex-wrap">
          <label className="flex items-center gap-2 cursor-pointer">
            <span className="text-[13px] text-[#7b7b78]">Por venda</span>
            <Switch checked={mode === "sale"} onCheckedChange={(c) => setMode(c ? "sale" : "lead")} />
          </label>
          <Select value={dateMode} onValueChange={(v) => {
            setDateMode(v as "preset" | "mes" | "custom");
            setDateFrom(""); setDateTo("");
          }}>
            <SelectTrigger className="w-[140px] text-[14px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="preset">Período</SelectItem>
              <SelectItem value="mes">Por mês</SelectItem>
              <SelectItem value="custom">Personalizado</SelectItem>
            </SelectContent>
          </Select>
          {dateMode === "preset" && (
            <Select value={period} onValueChange={setPeriod}>
              <SelectTrigger className="w-[150px] text-[14px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="7d">Últimos 7 dias</SelectItem>
                <SelectItem value="30d">Últimos 30 dias</SelectItem>
                <SelectItem value="90d">Últimos 90 dias</SelectItem>
                <SelectItem value="all">Tudo</SelectItem>
              </SelectContent>
            </Select>
          )}
          {dateMode === "mes" && (
            <input type="month" onChange={(e) => onMonth(e.target.value)}
              className="border border-[#dedbd6] rounded-[6px] px-3 py-1.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none" />
          )}
          {dateMode === "custom" && (
            <div className="flex items-center gap-2">
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                className="border border-[#dedbd6] rounded-[6px] px-2 py-1.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none" />
              <span className="text-[#7b7b78] text-[13px]">até</span>
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                className="border border-[#dedbd6] rounded-[6px] px-2 py-1.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none" />
            </div>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 flex flex-col px-4 md:px-8 py-4 md:py-8 bg-[#faf9f6]">
        {loading ? (
          <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4 md:p-5 space-y-2">
            {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : (
          <div className="bg-white border border-[#dedbd6] rounded-[8px] flex-1 min-h-0 flex flex-col overflow-hidden">
            <CampaignReportTable
              rows={report?.rows ?? []}
              total={report?.total}
              subtotals={report?.channel_subtotals ?? {}}
              onRowClick={(r) => {
                const params: Record<string, string> = { channel: r.channel, campaign: r.campaign, period, mode };
                if (dateFrom) params.date_from = dateFrom;
                if (dateTo) params.date_to = dateTo;
                router.push(`/trafego/campanha?${new URLSearchParams(params).toString()}`);
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
