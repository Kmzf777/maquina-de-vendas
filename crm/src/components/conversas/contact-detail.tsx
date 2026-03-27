"use client";

import { useState } from "react";
import { SELLER_STAGES, AGENT_STAGES } from "@/lib/constants";
import { EditableField } from "./editable-field";
import { createClient } from "@/lib/supabase/client";
import type { Lead, Tag } from "@/lib/types";

interface ContactDetailProps {
  phone: string;
  pushName: string | null;
  lead: Lead | null;
  tags: Tag[];
  leadTags: Tag[];
  onTagToggle: (tagId: string, add: boolean) => void;
  onCreateLead: () => void;
  onSellerStageChange: (stage: string) => void;
}

export function ContactDetail({
  phone,
  pushName,
  lead,
  tags,
  leadTags,
  onTagToggle,
  onCreateLead,
  onSellerStageChange,
}: ContactDetailProps) {
  const [showTagDropdown, setShowTagDropdown] = useState(false);
  const displayName = lead?.name || pushName || phone;
  const supabase = createClient();

  const stageInfo = lead ? AGENT_STAGES.find((s) => s.key === lead.stage) : null;
  const leadTagIds = new Set(leadTags.map((t) => t.id));
  const availableTags = tags.filter((t) => !leadTagIds.has(t.id));

  async function updateLeadField(field: string, value: string) {
    if (!lead) return;
    const numericFields = ["sale_value"];
    const updateValue = numericFields.includes(field) ? Number(value) || 0 : value;
    await supabase.from("leads").update({ [field]: updateValue }).eq("id", lead.id);
  }

  const daysActive = lead
    ? Math.floor((Date.now() - new Date(lead.created_at).getTime()) / (1000 * 60 * 60 * 24))
    : 0;

  return (
    <div className="w-[320px] bg-white border-l border-[#e5e5dc] flex flex-col h-full overflow-y-auto">
      {/* Avatar + Name */}
      <div className="flex flex-col items-center pt-8 pb-4 px-4 border-b border-[#e5e5dc]">
        <div className="w-20 h-20 rounded-full bg-[#c8cc8e] flex items-center justify-center text-white text-2xl font-bold mb-3">
          {displayName.charAt(0).toUpperCase()}
        </div>
        <h3 className="text-[18px] font-semibold text-[#1f1f1f]">{displayName}</h3>
        <p className="text-[13px] text-[#5f6368]">{phone}</p>
        {lead?.on_hold && (
          <span className="mt-2 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-[#f0ecd0] text-[#8a7a2a]">
            Em espera
          </span>
        )}
      </div>

      {lead ? (
        <div className="p-4 space-y-4 text-sm">
          {/* Stage info */}
          <div className="space-y-3">
            <div>
              <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-0.5">Stage (Agente)</span>
              <span className="text-[14px] text-[#1f1f1f]">{stageInfo?.label || lead.stage}</span>
            </div>
            <div>
              <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-0.5">Stage (Vendedor)</span>
              <select
                value={lead.seller_stage}
                onChange={(e) => onSellerStageChange(e.target.value)}
                className="input-field text-[14px] rounded-xl px-3 py-1.5 mt-1 w-full"
              >
                {SELLER_STAGES.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Sale Value */}
          <EditableField
            label="Valor da Venda"
            value={String(lead.sale_value || 0)}
            onSave={(v) => updateLeadField("sale_value", v)}
            placeholder="0"
            mask="currency"
          />

          {/* B2B Fields */}
          <div className="border-t border-[#e5e5dc] pt-4 space-y-3">
            <h4 className="text-[12px] font-semibold uppercase tracking-wider text-[#9ca3af]">Dados da Empresa</h4>
            <EditableField label="CNPJ" value={lead.cnpj} onSave={(v) => updateLeadField("cnpj", v)} placeholder="00.000.000/0000-00" />
            <EditableField label="Razao Social" value={lead.razao_social} onSave={(v) => updateLeadField("razao_social", v)} />
            <EditableField label="Nome Fantasia" value={lead.nome_fantasia} onSave={(v) => updateLeadField("nome_fantasia", v)} />
            <EditableField label="Inscricao Estadual" value={lead.inscricao_estadual} onSave={(v) => updateLeadField("inscricao_estadual", v)} />
            <EditableField label="Endereco" value={lead.endereco} onSave={(v) => updateLeadField("endereco", v)} />
          </div>

          {/* Contact Info */}
          <div className="border-t border-[#e5e5dc] pt-4 space-y-3">
            <h4 className="text-[12px] font-semibold uppercase tracking-wider text-[#9ca3af]">Contato</h4>
            <EditableField label="Telefone Comercial" value={lead.telefone_comercial} onSave={(v) => updateLeadField("telefone_comercial", v)} />
            <EditableField label="Email" value={lead.email} onSave={(v) => updateLeadField("email", v)} />
            <EditableField label="Instagram" value={lead.instagram} onSave={(v) => updateLeadField("instagram", v)} placeholder="@usuario" />
          </div>

          {/* Tags */}
          <div className="border-t border-[#e5e5dc] pt-4">
            <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-2">Tags</span>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {leadTags.map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs text-white"
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
                className="text-[12px] text-[#5f6368] hover:underline"
              >
                + Adicionar tag
              </button>
              {showTagDropdown && availableTags.length > 0 && (
                <div className="absolute top-6 left-0 bg-white rounded-xl shadow-lg border border-[#e5e5dc] py-1 z-10 min-w-[160px]">
                  {availableTags.map((tag) => (
                    <button
                      key={tag.id}
                      onClick={() => { onTagToggle(tag.id, true); setShowTagDropdown(false); }}
                      className="flex items-center gap-2 w-full px-3 py-1.5 text-sm text-[#1f1f1f] hover:bg-[#f6f7ed] transition-colors"
                    >
                      <span className="w-3 h-3 rounded-full" style={{ backgroundColor: tag.color }} />
                      {tag.name}
                    </button>
                  ))}
                </div>
              )}
              {showTagDropdown && availableTags.length === 0 && (
                <div className="absolute top-6 left-0 bg-white rounded-xl shadow-lg border border-[#e5e5dc] p-3 z-10">
                  <p className="text-[#9ca3af] text-xs">Nenhuma tag disponivel.</p>
                </div>
              )}
            </div>
          </div>

          {/* Contact Stats */}
          <div className="border-t border-[#e5e5dc] pt-4 space-y-2">
            <h4 className="text-[12px] font-semibold uppercase tracking-wider text-[#9ca3af]">Estatisticas</h4>
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-[#5f6368]">Dias ativos</span>
              <span className="text-[13px] font-medium text-[#1f1f1f]">{daysActive}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-[#5f6368]">Fonte</span>
              <span className="text-[13px] font-medium text-[#1f1f1f]">{lead.channel}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-[#5f6368]">Criado em</span>
              <span className="text-[13px] font-medium text-[#1f1f1f]">
                {new Date(lead.created_at).toLocaleDateString("pt-BR")}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="p-4 space-y-4">
          <div className="bg-[#f6f7ed] border border-[#e5e5dc] rounded-xl p-3">
            <p className="text-[#5f6368] text-sm font-medium">Contato pessoal</p>
            <p className="text-[#9ca3af] text-xs mt-1">Este contato nao esta cadastrado como lead.</p>
          </div>
          <button onClick={onCreateLead} className="btn-primary w-full py-2 rounded-xl text-sm">
            Criar Lead
          </button>
        </div>
      )}
    </div>
  );
}
