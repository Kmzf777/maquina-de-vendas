"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import type { Cadence } from "@/lib/types";
import { CadenceStepsTable } from "@/components/campaigns/cadence-steps-table";
import { CadenceTriggerConfig } from "@/components/campaigns/cadence-trigger-config";
import { CadenceEnrollmentsTable } from "@/components/campaigns/cadence-enrollments-table";

export default function CadenceDetailPage() {
  const params = useParams();
  const cadenceId = params.id as string;
  const [cadence, setCadence] = useState<Cadence | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"steps" | "leads" | "config">("steps");

  useEffect(() => {
    fetch(`/api/cadences/${cadenceId}`)
      .then((r) => r.json())
      .then((d) => { setCadence(d); setLoading(false); });
  }, [cadenceId]);

  const handleConfigChange = async (field: string, value: string | number | null) => {
    if (!cadence) return;
    const updated = { ...cadence, [field]: value };
    setCadence(updated as Cadence);
    await fetch(`/api/cadences/${cadenceId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: value }),
    });
  };

  const handleToggleStatus = async () => {
    if (!cadence) return;
    const newStatus = cadence.status === "active" ? "paused" : "active";
    setCadence({ ...cadence, status: newStatus });
    await fetch(`/api/cadences/${cadenceId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus }),
    });
  };

  if (loading || !cadence) {
    return (
      <div className="flex flex-col h-full">
        <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0">
          <div className="h-8 w-48 rounded-[4px] animate-pulse bg-[#dedbd6]" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Page header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <Link href="/campanhas" className="text-[#7b7b78] hover:text-[#111111] transition-colors text-[14px]">
            ← Campanhas
          </Link>
          <span className="text-[#dedbd6]">/</span>
          <h1 style={{ letterSpacing: '-0.96px', lineHeight: '1.00' }} className="text-[32px] font-normal text-[#111111]">
            {cadence?.name ?? "..."}
          </h1>
          {cadence && (
            <span className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border ${
              cadence.status === "active" ? "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20" : "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20"
            }`}>
              {cadence.status === "active" ? "Ativa" : "Pausada"}
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleToggleStatus}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
          >
            {cadence.status === "active" ? "Pausar" : "Ativar"}
          </button>
        </div>
      </div>

      {/* Config bar */}
      {cadence && (
        <div className="bg-[#f7f5f1] border-b border-[#dedbd6] px-8 py-3 flex gap-6 flex-shrink-0">
          {[
            { label: "Janela de envio", value: `${cadence.send_start_hour}h – ${cadence.send_end_hour}h` },
            { label: "Cooldown", value: `${cadence.cooldown_hours}h após resposta` },
            { label: "Máx. mensagens", value: `${cadence.max_messages} por lead` },
          ].map(({ label, value }) => (
            <div key={label} className="flex items-center gap-2">
              <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">{label}:</span>
              <span className="text-[13px] font-medium text-[#111111]">{value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Tab nav */}
      <div className="border-b border-[#dedbd6] bg-white px-8 flex-shrink-0">
        <div className="flex">
          {(["steps", "leads", "config"] as const).map((tab) => (
            <button key={tab} onClick={() => setActiveTab(tab)}
              className={`px-4 py-3 text-[14px] border-b-2 transition-colors ${
                activeTab === tab ? "border-[#111111] text-[#111111]" : "border-transparent text-[#7b7b78] hover:text-[#111111]"
              }`}>
              {tab === "steps" ? "Steps" : tab === "leads" ? "Leads" : "Configuração"}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-8 bg-[#faf9f6]">
        {activeTab === "steps" && <CadenceStepsTable cadenceId={cadenceId} />}
        {activeTab === "leads" && <CadenceEnrollmentsTable cadenceId={cadenceId} />}
        {activeTab === "config" && (
          <div className="space-y-4">
            <CadenceTriggerConfig
              targetType={cadence.target_type}
              targetStage={cadence.target_stage}
              stagnationDays={cadence.stagnation_days}
              onChange={handleConfigChange}
            />

            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
              <h3 style={{ letterSpacing: '-0.3px' }} className="text-[18px] font-medium text-[#111111] mb-4">Configurações de envio</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Janela inicio (hora)</label>
                  <input type="number" value={cadence.send_start_hour} onChange={(e) => handleConfigChange("send_start_hour", Number(e.target.value))} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
                </div>
                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Janela fim (hora)</label>
                  <input type="number" value={cadence.send_end_hour} onChange={(e) => handleConfigChange("send_end_hour", Number(e.target.value))} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
                </div>
                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Cooldown após resposta (horas)</label>
                  <input type="number" value={cadence.cooldown_hours} onChange={(e) => handleConfigChange("cooldown_hours", Number(e.target.value))} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
                </div>
                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Max mensagens por lead</label>
                  <input type="number" value={cadence.max_messages} onChange={(e) => handleConfigChange("max_messages", Number(e.target.value))} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
                </div>
              </div>
            </div>

            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
              <h3 style={{ letterSpacing: '-0.3px' }} className="text-[18px] font-medium text-[#111111] mb-4">Nome e descrição</h3>
              <input
                value={cadence.name}
                onChange={(e) => handleConfigChange("name", e.target.value)}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full mb-3"
              />
              <textarea
                value={cadence.description || ""}
                onChange={(e) => handleConfigChange("description", e.target.value || null)}
                placeholder="Descrição da cadência..."
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full min-h-[60px]"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
