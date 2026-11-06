"use client";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCurrentRole } from "@/hooks/use-current-role";
import { Skeleton } from "@/components/ui/skeleton";
import type { CampaignRow } from "@/components/trafego/campaign-report-table";
import { CampaignKpis } from "@/components/trafego/campaign-kpis";
import { CampaignTimeseries, type TsPoint } from "@/components/trafego/campaign-timeseries";
import { CampaignLeadsTable, type CampaignLead } from "@/components/trafego/campaign-leads-table";
import { FRASE_MODO, modoDaUrl } from "@/lib/traffic-mode";
import { detalheCampanhaUrl } from "@/lib/traffic-jornada";

type Detail = { summary: CampaignRow; leads: CampaignLead[]; timeseries: TsPoint[] };

const CHANNEL_STYLES: Record<string, string> = {
  "Google Ads": "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20",
  "Meta Ads": "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20",
  "Orgânico": "bg-[#0bdf50]/10 text-[#0f9d43] border-[#0bdf50]/20",
  "Sem rastreio": "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
};

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
      <Skeleton className="h-60 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  );
}

function Inner() {
  const sp = useSearchParams();
  const { role, loading: roleLoading } = useCurrentRole();
  const channel = sp.get("channel") || "";
  const campaign = sp.get("campaign") || "";
  const period = sp.get("period") || "30d";
  // Sem ?mode= abre a visão do período, como a página principal, os proxies e o backend.
  const mode = modoDaUrl(sp.get("mode"));
  const dateFrom = sp.get("date_from") || "";
  const dateTo = sp.get("date_to") || "";
  // F5: aberto pela "Primeira origem" no /trafego, o detalhe usa a mesma atribuição.
  const atribuicao = sp.get("atribuicao") === "primeira" ? "primeira" : "";
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (roleLoading || role !== "admin") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    const params: Record<string, string> = { channel, campaign, period, mode };
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    if (atribuicao) params.atribuicao = atribuicao;
    fetch(detalheCampanhaUrl(new URLSearchParams(params).toString(), atribuicao))
      .then(r => r.json())
      .then((d: Detail) => setDetail(d))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [channel, campaign, period, mode, dateFrom, dateTo, atribuicao, role, roleLoading]);

  const backQs = new URLSearchParams({
    ...(period ? { period } : {}),
    mode,
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
  }).toString();

  if (!roleLoading && role !== "admin") {
    return <div className="p-8 text-[14px] text-[#7b7b78]">Acesso restrito a administradores.</div>;
  }

  const channelStyle = CHANNEL_STYLES[channel] ?? CHANNEL_STYLES["Sem rastreio"];

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-4 md:py-5 flex-shrink-0">
        <Link
          href={`/trafego?${backQs}`}
          className="text-[13px] text-[#7b7b78] hover:text-[#111111] transition-colors"
        >
          ← Voltar
        </Link>
        <div className="flex items-center gap-3 mt-2">
          <span className={`inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-[4px] border ${channelStyle}`}>
            {channel}
          </span>
          <h1
            style={{ letterSpacing: "-0.6px" }}
            className="text-[22px] md:text-[28px] font-normal text-[#111111]"
          >
            {campaign}
          </h1>
        </div>
        <p data-testid="frase-modo" className="text-[12px] text-[#7b7b78] mt-1">{FRASE_MODO[mode]}</p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-4 md:px-8 py-4 md:py-6 bg-[#faf9f6] space-y-5">
        {loading || !detail ? (
          <LoadingSkeleton />
        ) : (
          <>
            <CampaignKpis summary={detail.summary} periodo={mode === "periodo"} />
            <CampaignTimeseries data={detail.timeseries} />
            <CampaignLeadsTable leads={detail.leads} />
          </>
        )}
      </div>
    </div>
  );
}

export default function CampaignDetailPage() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}
