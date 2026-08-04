"use client";

// Página admin "Relatório Campanhas" (/trafego): rastreio de campanhas e leads × vendas.
import { useEffect, useState } from "react";
import { useCurrentRole } from "@/hooks/use-current-role";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { CampaignReportTable, type CampaignRow, type ReportTotal, type ChannelSubtotals } from "@/components/trafego/campaign-report-table";
import { CampaignLeadsDrawer } from "@/components/trafego/campaign-leads-drawer";

type Report = { mode: string; period: string; rows: CampaignRow[]; total: ReportTotal; channel_subtotals: ChannelSubtotals };

export default function TrafegoPage() {
  const { role, loading: roleLoading } = useCurrentRole();
  const [period, setPeriod] = useState("30d");
  const [mode, setMode] = useState<"lead" | "sale">("lead");
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<{ channel: string; campaign: string } | null>(null);

  useEffect(() => {
    if (roleLoading || role !== "admin") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    fetch(`/api/traffic/report?period=${period}&mode=${mode}`)
      .then(r => r.json())
      .then((d: Report) => setReport(d))
      .catch(() => setReport(null))
      .finally(() => setLoading(false));
  }, [period, mode, role, roleLoading]);

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
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <span className="text-[13px] text-[#7b7b78]">Por venda</span>
            <Switch checked={mode === "sale"} onCheckedChange={(c) => setMode(c ? "sale" : "lead")} />
          </label>
          <Select value={period} onValueChange={setPeriod}>
            <SelectTrigger className="w-[150px] text-[14px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="7d">Últimos 7 dias</SelectItem>
              <SelectItem value="30d">Últimos 30 dias</SelectItem>
              <SelectItem value="90d">Últimos 90 dias</SelectItem>
              <SelectItem value="all">Tudo</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-4 md:px-8 py-4 md:py-8 bg-[#faf9f6]">
        {loading ? (
          <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4 md:p-5 space-y-2">
            {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : (
          <div className="bg-white border border-[#dedbd6] rounded-[8px] p-2 md:p-4 overflow-hidden">
            <CampaignReportTable
              rows={report?.rows ?? []}
              total={report?.total}
              subtotals={report?.channel_subtotals ?? {}}
              onRowClick={(r) => setSelected({ channel: r.channel, campaign: r.campaign })}
            />
          </div>
        )}
      </div>

      <CampaignLeadsDrawer
        channel={selected?.channel ?? null}
        campaign={selected?.campaign ?? null}
        period={period}
        mode={mode}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
