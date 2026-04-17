"use client";

import { useState, useEffect } from "react";
import { AGENT_STAGES } from "@/lib/constants";
import { EditableField } from "./editable-field";
import { createClient } from "@/lib/supabase/client";
import type { Lead, Tag, Conversation } from "@/lib/types";

interface ContactDetailProps {
  conversation: Conversation;
  tags: Tag[];
  leadTags: Tag[];
  onTagToggle: (tagId: string, add: boolean) => void;
}

export function ContactDetail({
  conversation,
  tags,
  leadTags,
  onTagToggle,
}: ContactDetailProps) {
  const [showTagDropdown, setShowTagDropdown] = useState(false);
  const [activeDeal, setActiveDeal] = useState<{ title: string; value: number; stage: string } | null>(null);
  const [agentProfiles, setAgentProfiles] = useState<{ id: string; name: string }[]>([]);
  const [aiEnabled, setAiEnabled] = useState(conversation.ai_enabled);
  const [agentProfileId, setAgentProfileId] = useState<string | null>(conversation.agent_profile_id);
  const lead = conversation.leads as Lead | undefined | null;
  const channel = conversation.channels;
  const displayName = lead?.name || lead?.phone || "Desconhecido";
  const supabase = createClient();

  useEffect(() => {
    if (!lead) return;
    import("@/lib/supabase/client").then(({ createClient: createSbClient }) => {
      const sb = createSbClient();
      sb.from("deals")
        .select("title, value, stage")
        .eq("lead_id", lead.id)
        .not("stage", "in", "(fechado_ganho,fechado_perdido)")
        .order("updated_at", { ascending: false })
        .limit(1)
        .then(({ data }) => {
          if (data && data.length > 0) setActiveDeal(data[0]);
        });
    });
  }, [lead?.id]);

  useEffect(() => {
    setAiEnabled(conversation.ai_enabled);
    setAgentProfileId(conversation.agent_profile_id);
  }, [conversation.id]);

  useEffect(() => {
    fetch("/api/agent-profiles")
      .then((r) => r.json())
      .then((data) => setAgentProfiles(Array.isArray(data) ? data : []));
  }, []);

  async function updateAgent(patch: { ai_enabled?: boolean; agent_profile_id?: string | null }) {
    const prevAiEnabled = aiEnabled;
    const prevAgentProfileId = agentProfileId;

    if (patch.ai_enabled !== undefined) setAiEnabled(patch.ai_enabled);
    if ("agent_profile_id" in patch) setAgentProfileId(patch.agent_profile_id ?? null);

    const res = await fetch(`/api/conversations/${conversation.id}/agent`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });

    if (!res.ok) {
      setAiEnabled(prevAiEnabled);
      setAgentProfileId(prevAgentProfileId);
    }
  }

  const stageInfo = lead ? AGENT_STAGES.find((s) => s.key === lead.stage) : null;
  const leadTagIds = new Set(leadTags.map((t) => t.id));
  const availableTags = tags.filter((t) => !leadTagIds.has(t.id));

  async function updateLeadField(field: string, value: string) {
    if (!lead) return;
    await supabase.from("leads").update({ [field]: value }).eq("id", lead.id);
  }

  const daysActive = lead
    ? Math.floor((Date.now() - new Date(lead.created_at).getTime()) / (1000 * 60 * 60 * 24))
    : 0;

  return (
    <div className="w-[320px] bg-white border-l border-[#dedbd6] flex flex-col h-full overflow-y-auto">
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
          {/* Agente IA */}
          <div>
            <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2 block">Agente IA</span>
            <div className="space-y-2">
              {/* Profile dropdown */}
              <div>
                <label className="text-[11px] text-[#7b7b78] block mb-1">Perfil</label>
                <select
                  value={agentProfileId ?? ""}
                  onChange={(e) => updateAgent({ agent_profile_id: e.target.value || null })}
                  className="w-full bg-white border border-[#dedbd6] rounded-[6px] text-[12px] px-2 py-1.5 text-[#111111] focus:border-[#111111] focus:outline-none"
                >
                  <option value="">Valeria Inbound (padrão)</option>
                  {agentProfiles.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
              {/* Status toggle */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <div className={`w-2 h-2 rounded-full ${aiEnabled ? "bg-green-500" : "bg-[#9b9b98]"}`} />
                  <span className="text-[13px] text-[#111111]">{aiEnabled ? "Ativo" : "Pausado"}</span>
                </div>
                <button
                  onClick={() => updateAgent({ ai_enabled: !aiEnabled })}
                  className={`text-[12px] px-3 py-1 rounded-[4px] border transition-colors ${
                    aiEnabled
                      ? "border-[#dedbd6] text-[#7b7b78] hover:border-[#111111] hover:text-[#111111]"
                      : "border-green-500 text-green-600 hover:bg-green-50"
                  }`}
                >
                  {aiEnabled ? "Pausar" : "Ativar"}
                </button>
              </div>
            </div>
          </div>

          {/* Stage info */}
          <div>
            <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1 block">Stage (Agente)</span>
            <span className="text-[14px] text-[#111111]">{stageInfo?.label || lead.stage}</span>
          </div>

          {activeDeal && (
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-3">
              <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Oportunidade ativa</span>
              <p className="text-[13px] font-medium text-[#111111]">{activeDeal.title}</p>
              <p className="text-[14px] font-medium text-[#111111] mt-0.5">
                {activeDeal.value > 0 ? `R$ ${activeDeal.value.toLocaleString("pt-BR")}` : "\u2014"}
              </p>
            </div>
          )}

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
    </div>
  );
}
