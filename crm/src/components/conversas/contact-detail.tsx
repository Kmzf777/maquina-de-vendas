"use client";

import { useState } from "react";
import { SELLER_STAGES, AGENT_STAGES } from "@/lib/constants";
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

  const stageInfo = lead
    ? AGENT_STAGES.find((s) => s.key === lead.stage)
    : null;

  const sellerStageInfo = lead
    ? SELLER_STAGES.find((s) => s.key === lead.seller_stage)
    : null;

  const leadTagIds = new Set(leadTags.map((t) => t.id));
  const availableTags = tags.filter((t) => !leadTagIds.has(t.id));

  return (
    <div className="w-80 bg-gray-900 border-l border-gray-800 flex flex-col h-full overflow-y-auto">
      {/* Avatar + Name */}
      <div className="flex flex-col items-center pt-8 pb-4 px-4 border-b border-gray-800">
        <div className="w-20 h-20 rounded-full bg-violet-600 flex items-center justify-center text-white text-2xl font-bold mb-3">
          {displayName.charAt(0).toUpperCase()}
        </div>
        <h3 className="text-white font-medium text-lg">{displayName}</h3>
        <p className="text-gray-400 text-sm">{phone}</p>
      </div>

      {lead ? (
        <div className="p-4 space-y-4">
          {/* Lead Info */}
          <div className="space-y-2">
            {lead.company && (
              <div>
                <span className="text-gray-500 text-xs block">Empresa</span>
                <span className="text-gray-200 text-sm">{lead.company}</span>
              </div>
            )}
            <div>
              <span className="text-gray-500 text-xs block">Stage (Agente)</span>
              <span className="text-gray-200 text-sm">
                {stageInfo?.label || lead.stage}
              </span>
            </div>
            <div>
              <span className="text-gray-500 text-xs block">Stage (Vendedor)</span>
              <select
                value={lead.seller_stage}
                onChange={(e) => onSellerStageChange(e.target.value)}
                className="bg-gray-800 text-gray-200 text-sm rounded px-2 py-1 mt-1 w-full outline-none focus:ring-1 focus:ring-violet-500"
              >
                {SELLER_STAGES.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <span className="text-gray-500 text-xs block">Criado em</span>
              <span className="text-gray-200 text-sm">
                {new Date(lead.created_at).toLocaleDateString("pt-BR")}
              </span>
            </div>
          </div>

          {/* Tags */}
          <div>
            <span className="text-gray-500 text-xs block mb-2">Tags</span>
            <div className="flex flex-wrap gap-1 mb-2">
              {leadTags.map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs text-white"
                  style={{ backgroundColor: tag.color }}
                >
                  {tag.name}
                  <button
                    onClick={() => onTagToggle(tag.id, false)}
                    className="hover:opacity-70"
                  >
                    x
                  </button>
                </span>
              ))}
            </div>
            <div className="relative">
              <button
                onClick={() => setShowTagDropdown(!showTagDropdown)}
                className="text-violet-400 text-xs hover:text-violet-300"
              >
                + Adicionar tag
              </button>
              {showTagDropdown && availableTags.length > 0 && (
                <div className="absolute top-6 left-0 bg-gray-800 rounded-lg shadow-lg border border-gray-700 py-1 z-10 min-w-[160px]">
                  {availableTags.map((tag) => (
                    <button
                      key={tag.id}
                      onClick={() => {
                        onTagToggle(tag.id, true);
                        setShowTagDropdown(false);
                      }}
                      className="flex items-center gap-2 w-full px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-700"
                    >
                      <span
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: tag.color }}
                      />
                      {tag.name}
                    </button>
                  ))}
                </div>
              )}
              {showTagDropdown && availableTags.length === 0 && (
                <div className="absolute top-6 left-0 bg-gray-800 rounded-lg shadow-lg border border-gray-700 p-3 z-10">
                  <p className="text-gray-400 text-xs">Nenhuma tag disponivel.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="p-4 space-y-4">
          <div className="bg-gray-800 rounded-lg p-3">
            <p className="text-gray-400 text-sm">Contato pessoal</p>
            <p className="text-gray-500 text-xs mt-1">
              Este contato nao esta cadastrado como lead.
            </p>
          </div>
          <button
            onClick={onCreateLead}
            className="w-full bg-violet-600 text-white py-2 rounded text-sm hover:bg-violet-700"
          >
            Criar Lead
          </button>
        </div>
      )}
    </div>
  );
}
