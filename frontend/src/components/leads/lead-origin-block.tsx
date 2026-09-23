"use client";

import { Badge } from "@/components/ui/badge";
import { useLeadOrigin } from "@/hooks/use-lead-origin";
import type { LeadOriginKind } from "@/lib/lead-origin";

const KIND_LABEL: Record<LeadOriginKind, string> = {
  pago: "Pago",
  organico: "Orgânico",
  importado: "Importado",
  sem_rastreio: "",
};

const KIND_CLASS: Record<LeadOriginKind, string> = {
  pago: "border-0 bg-[#111111] text-white font-medium",
  organico: "border-[#0bdf50]/30 bg-[#0bdf50]/10 text-[#0f9d43] font-normal",
  importado: "border-[#dedbd6] bg-[#f4f4f0] text-[#5f6368] font-normal",
  sem_rastreio: "border-[#dedbd6] text-[#7b7b78] font-normal",
};

/** Bloco "Origem" do lead: tipo · canal, e a campanha/página/indicador embaixo. */
export function LeadOriginBlock({ leadId }: { leadId: string }) {
  const { origin, loading, error } = useLeadOrigin(leadId);

  return (
    <div>
      <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1 block">Origem</span>
      {loading && !origin && <p className="text-[12px] text-[#7b7b78] px-2">Carregando origem…</p>}
      {error && <p className="text-[12px] text-[#7b7b78] px-2">Origem indisponível</p>}
      {origin && (
        <div className="px-2 space-y-0.5">
          <Badge
            variant="outline"
            className={`h-[18px] px-1.5 text-[10px] rounded-[4px] ${KIND_CLASS[origin.kind]}`}
          >
            {KIND_LABEL[origin.kind] ? `${KIND_LABEL[origin.kind]} · ${origin.channel}` : origin.channel}
          </Badge>
          {origin.detail && (
            <p className="text-[13px] text-[#111111] break-words" title={origin.detail}>
              {origin.detail}
            </p>
          )}
          {origin.funnel && <p className="text-[11px] text-[#7b7b78]">Funil: {origin.funnel}</p>}
        </div>
      )}
    </div>
  );
}
