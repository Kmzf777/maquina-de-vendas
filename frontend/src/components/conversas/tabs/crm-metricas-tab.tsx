"use client";

import { getTemperature, TEMPERATURE_CONFIG } from "@/lib/temperature";
import type { Lead } from "@/lib/types";

interface CrmMetricasTabProps {
  lead: Lead;
}

export function CrmMetricasTab({ lead }: CrmMetricasTabProps) {
  const temp = getTemperature(lead.last_msg_at);
  const tempConfig = TEMPERATURE_CONFIG[temp];

  const daysInCrm = Math.floor((Date.now() - new Date(lead.created_at).getTime()) / (1000 * 60 * 60 * 24));

  const firstResponseTime = lead.first_response_at
    ? Math.round((new Date(lead.first_response_at).getTime() - new Date(lead.created_at).getTime()) / 60000)
    : null;
  const firstResponseStr = firstResponseTime !== null
    ? firstResponseTime < 60 ? `${firstResponseTime}min` : `${Math.round(firstResponseTime / 60)}h`
    : "—";

  const daysInStage = lead.entered_stage_at
    ? Math.floor((Date.now() - new Date(lead.entered_stage_at).getTime()) / (1000 * 60 * 60 * 24))
    : null;

  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 text-center">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Temperatura</p>
          <p className="text-[14px] font-semibold mt-2" style={{ color: tempConfig.color }}>
            {tempConfig.label}
          </p>
          <p className="text-[11px] text-[#7b7b78] mt-0.5">
            Ultima msg: {lead.last_msg_at ? new Date(lead.last_msg_at).toLocaleDateString("pt-BR") : "Nunca"}
          </p>
        </div>
        <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 text-center">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">1a Resposta</p>
          <p className="text-[24px] font-semibold text-[#111111] mt-1">{firstResponseStr}</p>
        </div>
      </div>

      <div>
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Engajamento</p>
        <div className="grid grid-cols-2 gap-2.5">
          <div className="border border-[#dedbd6] rounded-[8px] p-3 text-center">
            <p className="text-[20px] font-semibold text-[#111111]">{daysInCrm}d</p>
            <p className="text-[11px] text-[#7b7b78] mt-1">No CRM</p>
          </div>
          <div className="border border-[#dedbd6] rounded-[8px] p-3 text-center">
            <p className="text-[20px] font-semibold text-[#111111]">
              {daysInStage !== null ? `${daysInStage}d` : "—"}
            </p>
            <p className="text-[11px] text-[#7b7b78] mt-1">No stage atual</p>
          </div>
        </div>
      </div>

      <div className="border-t border-[#dedbd6] pt-4 space-y-2">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Detalhes</p>
        <div className="flex items-center justify-between">
          <span className="text-[12px] text-[#7b7b78]">Fonte</span>
          <span className="text-[13px] text-[#111111]">{lead.channel || "—"}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[12px] text-[#7b7b78]">Criado em</span>
          <span className="text-[13px] text-[#111111]">
            {new Date(lead.created_at).toLocaleDateString("pt-BR")}
          </span>
        </div>
        {lead.entered_stage_at && (
          <div className="flex items-center justify-between">
            <span className="text-[12px] text-[#7b7b78]">Entrou no stage</span>
            <span className="text-[13px] text-[#111111]">
              {new Date(lead.entered_stage_at).toLocaleDateString("pt-BR")}
            </span>
          </div>
        )}
        {lead.first_response_at && (
          <div className="flex items-center justify-between">
            <span className="text-[12px] text-[#7b7b78]">1a resposta em</span>
            <span className="text-[13px] text-[#111111]">
              {new Date(lead.first_response_at).toLocaleDateString("pt-BR")}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
