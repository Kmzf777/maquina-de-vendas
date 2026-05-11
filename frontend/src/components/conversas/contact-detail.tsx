"use client";

import { useState, useEffect, useCallback } from "react";
import { AGENT_STAGES } from "@/lib/constants";
import { EditableField } from "./editable-field";
import { DealCreateModal } from "@/components/deals/deal-create-modal";
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";
import type { Lead, Tag, Conversation, Pipeline, PipelineStage } from "@/lib/types";

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
  followupEnabled,
  togglingFollowup,
  onToggleFollowup,
}: ContactDetailProps) {
  const [showTagDropdown, setShowTagDropdown] = useState(false);
  const [deals, setDeals] = useState<LeadDeal[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [showCreateDeal, setShowCreateDeal] = useState(false);
  const lead = conversation.leads as Lead | undefined | null;
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


  const stageInfo = lead ? AGENT_STAGES.find((s) => s.key === lead.stage) : null;
  const leadTagIds = new Set(leadTags.map((t) => t.id));
  const availableTags = tags.filter((t) => !leadTagIds.has(t.id));

  async function updateLeadField(field: string, value: string) {
    if (!lead) return;
    await fetch(`/api/leads/${lead.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: value }),
    });
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

  const createdMs = lead?.created_at ? new Date(lead.created_at).getTime() : NaN;
  const daysActive = isNaN(createdMs) ? 0 : Math.floor((Date.now() - createdMs) / (1000 * 60 * 60 * 24));

  return (
    <div className="w-full md:w-[320px] bg-white border-l-0 md:border-l border-[#dedbd6] flex flex-col h-full overflow-y-auto">
      {onBack && (
        <div className="md:hidden border-b border-[#dedbd6] px-4 py-3 flex flex-col gap-3 flex-shrink-0 bg-[#faf9f6]">
          {/* Back bar */}
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
          {/* Mobile controls: AI toggle, WA indicator */}
          <div className="flex items-center gap-2 flex-wrap">
            {onToggleAi && (
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
      {/* Avatar + Name */}
      <div className="flex flex-col items-center pt-8 pb-4 px-4 border-b border-[#dedbd6]">
        <div className="w-20 h-20 rounded-full bg-[#8a8a80] flex items-center justify-center text-white text-2xl font-medium mb-3">
          {displayName.charAt(0).toUpperCase()}
        </div>
        <h3 className="text-[16px] font-medium text-[#111111]">{displayName}</h3>
        <p className="text-[13px] text-[#7b7b78] mt-0.5">{lead?.phone || ""}</p>
        {channel && (
          <span className="mt-2 text-[11px] px-2 py-0.5 rounded-[4px] bg-[#dedbd6]/60 text-[#7b7b78]">
            {channel.name}
          </span>
        )}
        {lead?.on_hold && (
          <span className="mt-2 px-2.5 py-0.5 rounded-[4px] text-[11px] bg-[#dedbd6]/60 text-[#7b7b78]">
            Em espera
          </span>
        )}
      </div>

      {lead ? (
        <div className="p-4 space-y-4 text-sm">
          {/* Stage info */}
          <div>
            <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1 block">Stage (Agente)</span>
            <span className="text-[14px] text-[#111111]">{stageInfo?.label || lead.stage}</span>
          </div>

          {/* Oportunidades */}
          <div className="border-t border-[#dedbd6] pt-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Oportunidades</span>
              <button
                onClick={() => setShowCreateDeal(true)}
                className="w-6 h-6 flex items-center justify-center rounded-[4px] border border-[#dedbd6] text-[#7b7b78] hover:border-[#111111] hover:text-[#111111] transition-colors"
                title="Nova oportunidade"
              >
                <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
                </svg>
              </button>
            </div>
            {deals.length === 0 ? (
              <p className="text-[12px] text-[#7b7b78]">Nenhuma oportunidade</p>
            ) : (
              <div className="space-y-2">
                {deals.map((deal) => {
                  const stage = deal.pipeline_stages;
                  const isProtected = stage?.is_protected ?? false;
                  return (
                    <div
                      key={deal.id}
                      className={`flex items-start gap-2 p-2 rounded-[6px] border border-[#dedbd6] bg-white ${isProtected ? "opacity-50" : ""}`}
                    >
                      <span
                        className="w-2 h-2 rounded-full flex-shrink-0 mt-1"
                        style={{ backgroundColor: stage?.dot_color || "#dedbd6" }}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-[13px] text-[#111111] truncate">{deal.title}</p>
                        <p className="text-[11px] text-[#7b7b78]">
                          {deal.pipelines?.name || "—"} · {stage?.label || "—"}
                        </p>
                        {deal.value > 0 && (
                          <p className="text-[12px] text-[#111111]">
                            R$ {deal.value.toLocaleString("pt-BR")}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* B2B Fields */}
          <div className="border-t border-[#dedbd6] pt-4 space-y-3">
            <h4 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Dados da Empresa</h4>
            <EditableField label="CNPJ" value={lead.cnpj} onSave={(v) => updateLeadField("cnpj", v)} placeholder="00.000.000/0000-00" />
            <EditableField label="Razao Social" value={lead.razao_social} onSave={(v) => updateLeadField("razao_social", v)} />
            <EditableField label="Nome Fantasia" value={lead.nome_fantasia} onSave={(v) => updateLeadField("nome_fantasia", v)} />
            <EditableField label="Inscricao Estadual" value={lead.inscricao_estadual} onSave={(v) => updateLeadField("inscricao_estadual", v)} />
            <EditableField label="Endereco" value={lead.endereco} onSave={(v) => updateLeadField("endereco", v)} />
          </div>

          {/* Contact Info */}
          <div className="border-t border-[#dedbd6] pt-4 space-y-3">
            <h4 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Contato</h4>
            <EditableField label="Telefone Comercial" value={lead.telefone_comercial} onSave={(v) => updateLeadField("telefone_comercial", v)} />
            <EditableField label="Email" value={lead.email} onSave={(v) => updateLeadField("email", v)} />
            <EditableField label="Instagram" value={lead.instagram} onSave={(v) => updateLeadField("instagram", v)} placeholder="@usuario" />
          </div>

          {/* Tags */}
          <div className="border-t border-[#dedbd6] pt-4">
            <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-2">Tags</span>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {leadTags.map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-[4px] text-[12px] text-white"
                  style={{ backgroundColor: tag.color }}
                >
                  {tag.name}
                  <button onClick={() => onTagToggle(tag.id, false)} className="hover:opacity-70 ml-0.5">x</button>
                </span>
              ))}
            </div>
            <div className="relative">
              <button
                onClick={() => setShowTagDropdown(!showTagDropdown)}
                className="text-[12px] text-[#7b7b78] hover:text-[#111111] transition-colors"
              >
                + Adicionar tag
              </button>
              {showTagDropdown && availableTags.length > 0 && (
                <div className="absolute top-6 left-0 bg-white border border-[#dedbd6] rounded-[8px] py-1 z-10 min-w-[160px]">
                  {availableTags.map((tag) => (
                    <button
                      key={tag.id}
                      onClick={() => { onTagToggle(tag.id, true); setShowTagDropdown(false); }}
                      className="flex items-center gap-2 w-full px-3 py-1.5 text-[13px] text-[#111111] hover:bg-[#dedbd6]/30 transition-colors"
                    >
                      <span className="w-3 h-3 rounded-full" style={{ backgroundColor: tag.color }} />
                      {tag.name}
                    </button>
                  ))}
                </div>
              )}
              {showTagDropdown && availableTags.length === 0 && (
                <div className="absolute top-6 left-0 bg-white border border-[#dedbd6] rounded-[8px] p-3 z-10">
                  <p className="text-[#7b7b78] text-[12px]">Nenhuma tag disponivel.</p>
                </div>
              )}
            </div>
          </div>

          {/* Contact Stats */}
          <div className="border-t border-[#dedbd6] pt-4 space-y-2">
            <h4 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Estatisticas</h4>
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-[#7b7b78]">Dias ativos</span>
              <span className="text-[13px] text-[#111111]">{daysActive}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-[#7b7b78]">Fonte</span>
              <span className="text-[13px] text-[#111111]">{lead.channel}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-[#7b7b78]">Canal</span>
              <span className="text-[13px] text-[#111111]">{channel?.name || "—"}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-[#7b7b78]">Criado em</span>
              <span className="text-[13px] text-[#111111]">
                {new Date(lead.created_at).toLocaleDateString("pt-BR")}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="p-4">
          <div className="bg-white border border-[#dedbd6] rounded-[8px] p-3">
            <p className="text-[#111111] text-[13px] font-medium">Contato sem lead</p>
            <p className="text-[#7b7b78] text-[12px] mt-1">Este contato nao esta cadastrado como lead no CRM.</p>
          </div>
        </div>
      )}

      {showCreateDeal && lead && (
        <DealCreateModal
          leads={[lead]}
          pipelines={pipelines}
          preselectedLead={lead}
          onClose={() => setShowCreateDeal(false)}
          onCreate={handleCreateDeal}
        />
      )}
    </div>
  );
}
