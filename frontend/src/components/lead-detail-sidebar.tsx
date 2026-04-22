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
    <div className="fixed inset-y-0 right-0 w-[340px] bg-white border-l border-[#dedbd6] z-50 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-end p-4 border-b border-[#dedbd6]">
        <button
          onClick={onClose}
          className="w-8 h-8 flex items-center justify-center rounded-[4px] border border-[#dedbd6] text-[#7b7b78] hover:border-[#111111] hover:text-[#111111] transition-colors"
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
      <div className="flex flex-col items-center px-6 py-6 border-b border-[#dedbd6]">
        <div className="w-16 h-16 rounded-full bg-[#111111] flex items-center justify-center mb-3">
          <span className="text-[24px] font-semibold text-white">{initial}</span>
        </div>
        <h2
          className="text-[24px] font-normal text-[#111111] text-center"
          style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}
        >
          {lead.name || lead.phone}
        </h2>
        {lead.company && (
          <p className="text-[13px] text-[#7b7b78] mt-1">{lead.company}</p>
        )}
      </div>

      {/* Detailed Information */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div>
          <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-4">
            Informacoes detalhadas
          </p>
          <div className="space-y-4">
            {fields.map((field) => (
              <div key={field.label}>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-0.5">
                  {field.label}
                </label>
                <p className="text-[14px] text-[#111111]">{field.value}</p>
              </div>
            ))}
          </div>
        </div>

        {leadDeals.length > 0 && (
          <div className="mt-4 pt-4 border-t border-[#dedbd6]">
            <span className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">Oportunidades</span>
            {leadDeals.map((deal) => (
              <div key={deal.id} className="flex justify-between items-center py-1.5">
                <span className="text-[13px] text-[#111111]">{deal.title}</span>
                <span className="text-[12px] font-semibold text-[#0bdf50]">
                  {deal.value > 0 ? `R$ ${deal.value.toLocaleString("pt-BR")}` : "\u2014"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="p-6 border-t border-[#dedbd6]">
        <button
          onClick={markAsLost}
          className="w-full border border-[#c41c1c] text-[#c41c1c] py-2.5 rounded-[4px] text-[13px] hover:bg-[#c41c1c] hover:text-white transition-colors"
        >
          Marcar como perdido
        </button>
      </div>
    </div>
  );
}
