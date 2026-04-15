"use client";

import { useState, useEffect } from "react";
import type { Lead } from "@/lib/types";
import { createClient } from "@/lib/supabase/client";

interface LeadDetailSidebarProps {
  lead: Lead;
  onClose: () => void;
}

export function LeadDetailSidebar({ lead, onClose }: LeadDetailSidebarProps) {
  const supabase = createClient();
  const [leadDeals, setLeadDeals] = useState<Array<{ id: string; title: string; value: number; stage: string }>>([]);

  useEffect(() => {
    supabase
      .from("deals")
      .select("id, title, value, stage")
      .eq("lead_id", lead.id)
      .order("created_at", { ascending: false })
      .then(({ data }) => {
        if (data) setLeadDeals(data);
      });
  }, [lead.id]);

  async function markAsLost() {
    await supabase
      .from("leads")
      .update({ status: "lost" })
      .eq("id", lead.id);
    onClose();
  }

  const initial = (lead.name || lead.phone || "?")[0].toUpperCase();

  const fields = [
    { label: "NOME", value: lead.name || "\u2014" },
    { label: "TELEFONE", value: lead.phone },
    { label: "EMPRESA", value: lead.company || "\u2014" },
    { label: "STAGE (AGENTE)", value: lead.stage },
    { label: "CANAL", value: lead.channel },
    {
      label: "CRIADO EM",
      value: new Date(lead.created_at).toLocaleDateString("pt-BR"),
    },
    {
      label: "ULTIMA MENSAGEM",
      value: lead.last_msg_at
        ? new Date(lead.last_msg_at).toLocaleString("pt-BR")
        : "\u2014",
    },
  ];

  return (
    <div className="fixed inset-y-0 right-0 w-[340px] bg-white shadow-xl border-l border-[#e5e5dc] z-50 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-end p-4">
        <button
          onClick={onClose}
          className="w-8 h-8 flex items-center justify-center rounded-full bg-[#f4f4f0] text-[#5f6368] hover:bg-[#e5e5dc] hover:text-[#1f1f1f] transition-colors"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>

      {/* Avatar + Name */}
      <div className="flex flex-col items-center px-6 pb-6">
        <div className="w-16 h-16 rounded-full bg-[#c8cc8e] flex items-center justify-center mb-3">
          <span className="text-[24px] font-bold text-white">{initial}</span>
        </div>
        <h2 className="text-[20px] font-bold text-[#1f1f1f] text-center">
          {lead.name || lead.phone}
        </h2>
        {lead.company && (
          <p className="text-[13px] text-[#5f6368] mt-0.5">{lead.company}</p>
        )}
      </div>

      {/* Detailed Information */}
      <div className="flex-1 overflow-y-auto px-6">
        <div className="border-t border-[#e5e5dc] pt-4">
          <h3 className="text-[11px] font-semibold tracking-wider text-[#9ca3af] uppercase mb-4">
            Informacoes detalhadas
          </h3>
          <div className="space-y-4">
            {fields.map((field) => (
              <div key={field.label}>
                <label className="block text-[11px] font-medium tracking-wider text-[#9ca3af] uppercase mb-0.5">
                  {field.label}
                </label>
                <p className="text-[14px] text-[#1f1f1f]">{field.value}</p>
              </div>
            ))}
          </div>
        </div>

        {leadDeals.length > 0 && (
          <div className="mt-4 border-t border-[#e5e5dc] pt-4">
            <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-2">Oportunidades</span>
            {leadDeals.map((deal) => (
              <div key={deal.id} className="flex justify-between items-center py-1.5">
                <span className="text-[13px] text-[#1f1f1f]">{deal.title}</span>
                <span className="text-[12px] font-semibold text-[#2d6a3f]">
                  {deal.value > 0 ? `R$ ${deal.value.toLocaleString("pt-BR")}` : "\u2014"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="p-6 border-t border-[#e5e5dc]">
        <button
          onClick={markAsLost}
          className="w-full border border-red-200 text-red-500 py-2.5 rounded-xl text-[13px] font-medium hover:bg-red-50 hover:border-red-300 transition-colors"
        >
          Marcar como perdido
        </button>
      </div>
    </div>
  );
}
