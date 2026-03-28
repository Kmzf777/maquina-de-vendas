"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useRealtimeCampaigns } from "@/hooks/use-realtime-campaigns";
import { CAMPAIGN_STATUS_COLORS } from "@/lib/constants";
import { CampaignKpis } from "@/components/campaign-kpis";
import { CadenceLeadsTable } from "@/components/cadence-leads-table";
import { CadenceStepsModal } from "@/components/cadence-steps-modal";
import { CadenceActivity } from "@/components/cadence-activity";

const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

type Tab = "leads" | "steps" | "atividade";

export default function CampaignDetailPage() {
  const params = useParams<{ id: string }>();
  const { campaigns, loading } = useRealtimeCampaigns();
  const [tab, setTab] = useState<Tab>("leads");
  const [showModal, setShowModal] = useState(false);

  const campaign = campaigns.find((c) => c.id === params.id);

  async function handleAction(action: "start" | "pause") {
    if (!campaign) return;
    await fetch(`${FASTAPI_URL}/api/campaigns/${campaign.id}/${action}`, {
      method: "POST",
    });
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-12">
        <div className="w-5 h-5 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
        <p className="text-[#5f6368] text-[14px]">Carregando...</p>
      </div>
    );
  }

  if (!campaign) {
    return (
      <div className="py-12 text-center">
        <p className="text-[14px] text-[#5f6368] mb-4">Campanha nao encontrada.</p>
        <Link href="/campanhas" className="text-[13px] font-medium text-[#1f1f1f] hover:underline">
          &larr; Voltar para campanhas
        </Link>
      </div>
    );
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "leads", label: "Leads em Cadencia" },
    { key: "steps", label: "Steps de Cadencia" },
    { key: "atividade", label: "Atividade" },
  ];

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <Link href="/campanhas" className="text-[13px] text-[#5f6368] hover:text-[#1f1f1f] transition-colors mb-3 inline-block">
          &larr; Campanhas
        </Link>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-[28px] font-bold text-[#1f1f1f]">{campaign.name}</h1>
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-medium ${
                CAMPAIGN_STATUS_COLORS[campaign.status] || ""
              }`}
            >
              {campaign.status}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowModal(true)}
              className="btn-secondary px-4 py-2 rounded-xl text-[13px] font-medium"
            >
              Configurar Cadencia
            </button>
            {(campaign.status === "draft" || campaign.status === "paused") && (
              <button
                onClick={() => handleAction("start")}
                className="btn-primary px-4 py-2 rounded-xl text-[13px] font-medium"
              >
                Iniciar
              </button>
            )}
            {campaign.status === "running" && (
              <button
                onClick={() => handleAction("pause")}
                className="btn-secondary px-4 py-2 rounded-xl text-[13px] font-medium"
              >
                Pausar
              </button>
            )}
          </div>
        </div>
        <div className="flex items-center gap-4 mt-2 text-[12px] text-[#5f6368]">
          <span>Template: <strong className="text-[#1f1f1f]">{campaign.template_name}</strong></span>
          <span>Criada em: {new Date(campaign.created_at).toLocaleDateString("pt-BR")}</span>
          <span>Total: <strong className="text-[#1f1f1f]">{campaign.total_leads}</strong> leads</span>
        </div>
      </div>

      {/* KPIs */}
      <div className="mb-6">
        <CampaignKpis campaign={campaign} />
      </div>

      {/* Config Summary Bar */}
      <div className="card p-4 mb-6">
        <div className="flex items-center gap-6 text-[12px] text-[#5f6368]">
          <span>Intervalo: <strong className="text-[#1f1f1f]">{campaign.cadence_interval_hours || 24}h</strong></span>
          <span>Janela: <strong className="text-[#1f1f1f]">{campaign.cadence_send_start_hour || 7}h&ndash;{campaign.cadence_send_end_hour || 18}h</strong></span>
          <span>Cooldown: <strong className="text-[#1f1f1f]">{campaign.cadence_cooldown_hours || 48}h</strong></span>
          <span>Max msgs: <strong className="text-[#1f1f1f]">{campaign.cadence_max_messages || 8}</strong></span>
          <span>Follow-ups enviados: <strong className="text-[#1f1f1f]">{campaign.cadence_sent || 0}</strong></span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 border-b border-[#ededea]">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2.5 text-[13px] font-medium transition-colors relative ${
              tab === t.key
                ? "text-[#1f1f1f]"
                : "text-[#9ca3af] hover:text-[#5f6368]"
            }`}
          >
            {t.label}
            {tab === t.key && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#1f1f1f] rounded-full" />
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === "leads" && <CadenceLeadsTable campaignId={campaign.id} />}
      {tab === "steps" && (
        <div className="card p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-[14px] font-semibold text-[#1f1f1f]">Steps de Cadencia por Stage</h3>
            <button
              onClick={() => setShowModal(true)}
              className="btn-secondary px-4 py-1.5 rounded-lg text-[12px] font-medium"
            >
              Editar Steps
            </button>
          </div>
          <p className="text-[13px] text-[#5f6368]">
            Clique em &ldquo;Editar Steps&rdquo; ou &ldquo;Configurar Cadencia&rdquo; para gerenciar as mensagens de follow-up.
          </p>
        </div>
      )}
      {tab === "atividade" && <CadenceActivity campaignId={campaign.id} />}

      {/* Modal */}
      <CadenceStepsModal
        campaign={campaign}
        open={showModal}
        onClose={() => setShowModal(false)}
      />
    </div>
  );
}
