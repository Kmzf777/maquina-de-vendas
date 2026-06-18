"use client";

import { useState, useEffect, useCallback } from "react";
import { DealCreateModal } from "@/components/deals/deal-create-modal";
import { SaleCreateModal } from "@/components/sales/sale-create-modal";
import { useLeadSales } from "@/hooks/use-lead-sales";
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";
import { CrmPerfilTab } from "./tabs/crm-perfil-tab";
import { CrmNotasTab } from "./tabs/crm-notas-tab";
import { CrmCampanhasTab } from "./tabs/crm-campanhas-tab";
import { CrmMetricasTab } from "./tabs/crm-metricas-tab";
import type { Lead, Tag, Conversation, Pipeline, PipelineStage, Sale } from "@/lib/types";

interface LeadDeal {
  id: string;
  title: string;
  value: number;
  category: string | null;
  stage_id: string | null;
  pipeline_id: string | null;
  updated_at: string;
  pipeline_stages: Pick<PipelineStage, "id" | "label" | "dot_color" | "key" | "is_protected"> | null;
  pipelines: Pick<Pipeline, "id" | "name"> | null;
}

type TabKey = "perfil" | "notas" | "campanhas" | "metricas";

const TABS: { key: TabKey; label: string }[] = [
  { key: "perfil", label: "Perfil" },
  { key: "notas", label: "Notas" },
  { key: "campanhas", label: "Campanhas" },
  { key: "metricas", label: "Métricas" },
];

interface ContactDetailProps {
  conversation: Conversation;
  tags: Tag[];
  leadTags: Tag[];
  onTagToggle: (tagId: string, add: boolean) => void;
  onBack?: () => void;
  aiEnabled?: boolean;
  togglingAi?: boolean;
  onToggleAi?: () => void | Promise<void>;
  followupEnabled?: boolean;
  togglingFollowup?: boolean;
  onToggleFollowup?: () => void | Promise<void>;
  onLeadUpdate?: (leadId: string, patch: Partial<Lead>) => void;
  onDealStageChange?: (dealId: string, stageId: string) => Promise<void>;
}

export function ContactDetail({
  conversation,
  tags,
  leadTags,
  onTagToggle,
  onBack,
  aiEnabled,
  togglingAi,
  onToggleAi,
  onLeadUpdate,
  onDealStageChange,
}: ContactDetailProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("perfil");
  const [deals, setDeals] = useState<LeadDeal[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [showCreateDeal, setShowCreateDeal] = useState(false);
  const [showCreateSale, setShowCreateSale] = useState(false);
  const [editingSale, setEditingSale] = useState<Sale | null>(null);
  const [currentUserEmail, setCurrentUserEmail] = useState<string>("");
  const lead = conversation.leads as Lead | undefined | null;
  const { sales, refetch: refetchSales } = useLeadSales(lead?.id);
  const channel = conversation.channels;
  const displayName = lead?.name || lead?.phone || "Desconhecido";

  const fetchDeals = useCallback(async () => {
    if (!lead) return;
    const res = await fetch(`/api/leads/${lead.id}/deals`);
    if (res.ok) {
      const data = await res.json();
      setDeals(Array.isArray(data) ? data : []);
    }
  }, [lead?.id]);

  useEffect(() => {
    fetchDeals();
  }, [fetchDeals]);

  useEffect(() => {
    fetch("/api/pipelines")
      .then((r) => r.json())
      .then((data) => setPipelines(Array.isArray(data) ? data : []));
  }, []);

  useEffect(() => {
    import("@/lib/supabase/client").then(({ createClient }) => {
      createClient().auth.getSession().then(({ data: { session } }) => {
        setCurrentUserEmail(session?.user?.email ?? "");
      });
    });
  }, []);

  async function updateLeadField(field: string, value: string) {
    if (!lead) return;
    onLeadUpdate?.(lead.id, { [field]: value } as Partial<Lead>);
    try {
      const res = await fetch(`/api/leads/${lead.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value }),
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
    } catch {
      onLeadUpdate?.(lead.id, { [field]: (lead as unknown as Record<string, unknown>)[field] } as Partial<Lead>);
    }
  }

  async function handleCreateDeal(data: {
    lead_id: string;
    title: string;
    value: number;
    category: string;
    expected_close_date: string;
    pipeline_id?: string;
  }) {
    if (!data.pipeline_id) return;
    const res = await fetch("/api/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (res.ok) {
      await fetchDeals();
    }
  }

  async function handleDealStageChange(dealId: string, stageId: string) {
    const res = await fetch(`/api/deals/${dealId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage_id: stageId }),
    });
    if (res.ok) await fetchDeals();
  }

  return (
    <div className="w-full md:w-[320px] bg-white border-l-0 md:border-l border-[#dedbd6] flex flex-col h-full">
      {onBack && (
        <div className="md:hidden border-b border-[#dedbd6] px-4 py-3 flex flex-col gap-3 flex-shrink-0 bg-[#faf9f6]">
          <div className="flex items-center gap-3">
            <button
              onClick={onBack}
              className="w-8 h-8 flex items-center justify-center rounded-[4px] text-[#313130] hover:bg-[#dedbd6]/60 transition-colors"
              aria-label="Voltar"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
              </svg>
            </button>
            <span className="text-[14px] font-medium text-[#111111]">Informações do Lead</span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {onToggleAi && conversation.channels?.mode !== "human" && (
              <button
                type="button"
                onClick={() => onToggleAi()}
                disabled={togglingAi}
                className={`inline-flex items-center gap-2 rounded-[4px] px-3 py-1.5 text-xs font-medium transition-colors ${
                  aiEnabled
                    ? "bg-[#ff5600] text-white hover:bg-[#e64e00]"
                    : "bg-[#dedbd6] text-[#111111] hover:bg-[#cbc7c0]"
                } ${togglingAi ? "opacity-60 cursor-not-allowed" : ""}`}
                aria-pressed={aiEnabled}
              >
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${aiEnabled ? "bg-white animate-pulse" : "bg-[#7b7b78]"}`} aria-hidden />
                Valéria IA · {aiEnabled ? "Ativa" : "Pausada"}
              </button>
            )}
            <WhatsappWindowIndicator
              expiresAt={conversation.whatsapp_window_expires_at ?? null}
              variant="header"
            />
          </div>
        </div>
      )}

      <div className="flex items-center gap-3 px-4 py-4 border-b border-[#dedbd6] flex-shrink-0">
        <div className="w-10 h-10 rounded-full bg-[#8a8a80] flex-shrink-0 flex items-center justify-center text-white text-sm font-medium">
          {displayName.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-[14px] font-medium text-[#111111] truncate">{displayName}</h3>
          <p className="text-[12px] text-[#7b7b78] truncate">{lead?.phone || ""}</p>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            {channel && (
              <span className="text-[11px] px-1.5 py-0.5 rounded-[4px] bg-[#dedbd6]/60 text-[#7b7b78]">
                {channel.name}
              </span>
            )}
            {lead?.on_hold && (
              <span className="px-1.5 py-0.5 rounded-[4px] text-[11px] bg-[#dedbd6]/60 text-[#7b7b78]">
                Em espera
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="flex border-b border-[#dedbd6] flex-shrink-0">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex-1 py-2 text-[12px] font-medium border-b-2 transition-colors ${
              activeTab === tab.key
                ? "text-[#111111] border-[#111111]"
                : "text-[#7b7b78] border-transparent hover:text-[#111111]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {lead ? (
          <>
            {activeTab === "perfil" && (
              <CrmPerfilTab
                lead={lead}
                onSaveField={updateLeadField}
                deals={deals}
                pipelines={pipelines}
                tags={tags}
                leadTags={leadTags}
                onTagToggle={onTagToggle}
                onCreateDeal={() => setShowCreateDeal(true)}
                onDealStageChange={onDealStageChange ?? handleDealStageChange}
                sales={sales}
                onCreateSale={() => setShowCreateSale(true)}
                onEditSale={(s) => setEditingSale(s as Sale)}
                onDeleteSale={async (saleId) => {
                  if (!window.confirm("Excluir esta venda? Esta ação não pode ser desfeita.")) return;
                  const res = await fetch(`/api/sales/${saleId}`, { method: "DELETE" });
                  if (res.ok) refetchSales(); else alert("Erro ao excluir venda.");
                }}
              />
            )}
            {activeTab === "notas" && (
              <CrmNotasTab leadId={lead.id} />
            )}
            {activeTab === "campanhas" && (
              <CrmCampanhasTab leadId={lead.id} />
            )}
            {activeTab === "metricas" && (
              <CrmMetricasTab lead={lead} />
            )}
          </>
        ) : (
          <div className="p-4">
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-3">
              <p className="text-[#111111] text-[13px] font-medium">Contato sem lead</p>
              <p className="text-[#7b7b78] text-[12px] mt-1">Este contato nao esta cadastrado como lead no CRM.</p>
            </div>
          </div>
        )}
      </div>

      {showCreateDeal && lead && (
        <DealCreateModal
          leads={[lead]}
          pipelines={pipelines}
          preselectedLead={lead}
          onClose={() => setShowCreateDeal(false)}
          onCreate={handleCreateDeal}
        />
      )}
      {(showCreateSale || editingSale) && lead && (
        <SaleCreateModal
          leadId={lead.id}
          conversationId={conversation.id}
          currentUserEmail={currentUserEmail}
          editingSale={editingSale}
          onClose={() => { setShowCreateSale(false); setEditingSale(null); }}
          onSaved={() => { refetchSales(); setShowCreateSale(false); setEditingSale(null); }}
        />
      )}
    </div>
  );
}
