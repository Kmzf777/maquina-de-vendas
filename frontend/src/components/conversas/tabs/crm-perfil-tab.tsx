"use client";

import { useState } from "react";
import { AGENT_STAGES } from "@/lib/constants";
import { EditableField } from "../editable-field";
import type { Lead, Tag, Pipeline, PipelineStage } from "@/lib/types";

interface LeadSale {
  id: string;
  sold_at: string;
  value: number;
  product: string;
  sold_by: string | null;
}

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

interface CrmPerfilTabProps {
  lead: Lead;
  onSaveField: (field: string, value: string) => Promise<void>;
  deals: LeadDeal[];
  pipelines: Pipeline[];
  tags: Tag[];
  leadTags: Tag[];
  onTagToggle: (tagId: string, add: boolean) => void;
  onCreateDeal: () => void;
  sales: LeadSale[];
  onCreateSale: () => void;
}

export function CrmPerfilTab({
  lead,
  onSaveField,
  deals,
  tags,
  leadTags,
  onTagToggle,
  onCreateDeal,
  sales,
  onCreateSale,
}: CrmPerfilTabProps) {
  const [showTagDropdown, setShowTagDropdown] = useState(false);

  const leadTagIds = new Set(leadTags.map((t) => t.id));
  const availableTags = tags.filter((t) => !leadTagIds.has(t.id));
  const stageInfo = AGENT_STAGES.find((s) => s.key === lead.stage);

  return (
    <div className="p-4 space-y-4 text-sm">
      <div className="space-y-3">
        <h4 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Identificacao</h4>
        <EditableField
          label="Nome"
          value={lead.name}
          onSave={(v) => onSaveField("name", v)}
          placeholder="Nome do contato"
        />
        <EditableField
          label="Empresa"
          value={lead.company}
          onSave={(v) => onSaveField("company", v)}
          placeholder="Empresa"
        />
        <div>
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1 block">Telefone</span>
          <span className="text-[14px] text-[#111111] px-2 py-0.5 block">{lead.phone}</span>
        </div>
        <EditableField
          label="Email"
          value={lead.email}
          onSave={(v) => onSaveField("email", v)}
          placeholder="email@exemplo.com"
        />
        <EditableField
          label="Instagram"
          value={lead.instagram}
          onSave={(v) => onSaveField("instagram", v)}
          placeholder="@usuario"
        />
      </div>

      <div className="border-t border-[#dedbd6] pt-4 space-y-3">
        <h4 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Empresa B2B</h4>
        <EditableField label="CNPJ" value={lead.cnpj} onSave={(v) => onSaveField("cnpj", v)} placeholder="00.000.000/0000-00" />
        <EditableField label="Razao Social" value={lead.razao_social} onSave={(v) => onSaveField("razao_social", v)} />
        <EditableField label="Nome Fantasia" value={lead.nome_fantasia} onSave={(v) => onSaveField("nome_fantasia", v)} />
        <EditableField label="Inscricao Estadual" value={lead.inscricao_estadual} onSave={(v) => onSaveField("inscricao_estadual", v)} />
        <EditableField label="Endereco" value={lead.endereco} onSave={(v) => onSaveField("endereco", v)} />
        <EditableField label="Tel. Comercial" value={lead.telefone_comercial} onSave={(v) => onSaveField("telefone_comercial", v)} />
      </div>

      <div className="border-t border-[#dedbd6] pt-4 space-y-3">
        <h4 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Status CRM</h4>
        <div>
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1 block">Stage</span>
          <select
            value={lead.stage}
            onChange={(e) => onSaveField("stage", e.target.value)}
            className="bg-white border border-[#dedbd6] rounded-[6px] px-2 py-1 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
          >
            {AGENT_STAGES.map((s) => (
              <option key={s.key} value={s.key}>{s.label}</option>
            ))}
          </select>
        </div>
        <EditableField label="Atribuido a" value={lead.assigned_to} onSave={(v) => onSaveField("assigned_to", v)} placeholder="Ninguem" />
      </div>

      <div className="border-t border-[#dedbd6] pt-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Oportunidades</span>
          <button
            onClick={onCreateDeal}
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

      <div className="border-t border-[#dedbd6] pt-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Vendas</span>
          <button
            onClick={onCreateSale}
            className="w-6 h-6 flex items-center justify-center rounded-[4px] border border-[#dedbd6] text-[#7b7b78] hover:border-[#111111] hover:text-[#111111] transition-colors"
            title="Registrar venda"
          >
            <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
            </svg>
          </button>
        </div>
        {sales.length === 0 ? (
          <p className="text-[12px] text-[#7b7b78]">Nenhuma venda registrada</p>
        ) : (
          <div className="space-y-2">
            {sales.slice(0, 3).map((sale) => (
              <div key={sale.id} className="flex items-start gap-2 p-2 rounded-[6px] border border-[#dedbd6] bg-white">
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] text-[#111111] truncate">{sale.product}</p>
                  <p className="text-[11px] text-[#7b7b78]">
                    {new Date(sale.sold_at).toLocaleDateString("pt-BR")}
                    {sale.sold_by ? ` · ${sale.sold_by}` : ""}
                  </p>
                  <p className="text-[12px] text-[#111111]">
                    R$ {Number(sale.value).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                  </p>
                </div>
              </div>
            ))}
            {sales.length > 3 && (
              <p className="text-[11px] text-[#7b7b78]">+{sales.length - 3} mais vendas</p>
            )}
          </div>
        )}
      </div>

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
    </div>
  );
}
