"use client";

import type { Campaign } from "@/lib/types";
import { campaignNodeCount } from "@/lib/campaign-node-count";
import { isSystemCampaign } from "@/lib/system-campaign";

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  draft:    { bg: "bg-[#f0ede8]",       text: "text-[#7b7b78]",   label: "Rascunho" },
  active:   { bg: "bg-[#0bdf50]/10",    text: "text-[#0bdf50]",   label: "Ativa" },
  paused:   { bg: "bg-[#fe4c02]/10",    text: "text-[#fe4c02]",   label: "Pausada" },
  archived: { bg: "bg-[#f0ede8]",       text: "text-[#7b7b78]",   label: "Arquivada" },
};

interface CadenceCardProps {
  campaign: Campaign;
  onClick: () => void;
  onRefresh: () => void;
}

export function CadenceCard({ campaign, onClick }: CadenceCardProps) {
  // O espelho do motor da Valéria é tecnicamente draft (proteção de backend contra
  // execução dupla), mas "Rascunho" sugere fluxo inacabado — o selo vira "Sistema".
  const st = isSystemCampaign(campaign.id)
    ? { bg: "bg-[#ff5600]/10", text: "text-[#ff5600]", label: "Sistema" }
    : (STATUS_STYLES[campaign.status] ?? STATUS_STYLES.draft);
  const nodeCount = campaignNodeCount(campaign);

  return (
    <div
      onClick={onClick}
      className="bg-white border border-[#dedbd6] rounded-[8px] p-5 cursor-pointer hover:border-[#111111] transition-colors"
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <p className="text-[15px] font-medium text-[#111111] leading-tight">{campaign.name}</p>
          {campaign.description && (
            <p className="text-[12px] text-[#7b7b78] mt-0.5">{campaign.description}</p>
          )}
        </div>
        <span className={`text-[10px] font-semibold uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] flex-shrink-0 ml-2 ${st.bg} ${st.text}`}>
          {st.label}
        </span>
      </div>
      <div className="flex items-center gap-4 text-[12px] text-[#7b7b78]">
        <span>{nodeCount} nós</span>
        <span>·</span>
        <span>Criada {new Date(campaign.created_at).toLocaleDateString("pt-BR")}</span>
      </div>
    </div>
  );
}
