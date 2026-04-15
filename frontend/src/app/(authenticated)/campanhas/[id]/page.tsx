"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import type { Cadence } from "@/lib/types";
import { CadenceStepsTable } from "@/components/campaigns/cadence-steps-table";
import { CadenceTriggerConfig } from "@/components/campaigns/cadence-trigger-config";
import { CadenceEnrollmentsTable } from "@/components/campaigns/cadence-enrollments-table";

export default function CadenceDetailPage() {
  const params = useParams();
  const cadenceId = params.id as string;
  const [cadence, setCadence] = useState<Cadence | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"steps" | "leads" | "config">("steps");

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
    return <div className="h-8 w-48 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-[24px] font-bold text-[#1f1f1f]">{cadence.name}</h1>
          {cadence.description && <p className="text-[14px] text-[#5f6368] mt-1">{cadence.description}</p>}
        </div>
        <div className="flex items-center gap-3">
          <span className={`px-2.5 py-1 rounded-full text-[12px] font-medium ${
            cadence.status === "active" ? "bg-[#d8f0dc] text-[#2d6a3f]" :
            cadence.status === "paused" ? "bg-[#f0ecd0] text-[#8a7a2a]" :
            "bg-[#f4f4f0] text-[#5f6368]"
          }`}>
            {cadence.status === "active" ? "Ativa" : cadence.status === "paused" ? "Pausada" : "Arquivada"}
          </span>
          <button
            onClick={handleToggleStatus}
            className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333]"
          >
            {cadence.status === "active" ? "Pausar" : "Ativar"}
          </button>
        </div>
      </div>

      {/* Config summary bar */}
      <div className="flex gap-4 mb-6 text-[12px]">
        <span className="px-3 py-1.5 rounded-full bg-[#f6f7ed] text-[#5f6368]">
          Janela: {cadence.send_start_hour}h-{cadence.send_end_hour}h
        </span>
        <span className="px-3 py-1.5 rounded-full bg-[#f6f7ed] text-[#5f6368]">
          Cooldown: {cadence.cooldown_hours}h
        </span>
        <span className="px-3 py-1.5 rounded-full bg-[#f6f7ed] text-[#5f6368]">
          Max: {cadence.max_messages} msgs
        </span>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5">
        {(["steps", "leads", "config"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-[13px] font-medium transition-colors ${
              tab === t ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
            }`}
          >
            {t === "steps" ? "Steps" : t === "leads" ? "Leads" : "Configuracao"}
          </button>
        ))}
      </div>

      {tab === "steps" && <CadenceStepsTable cadenceId={cadenceId} />}
      {tab === "leads" && <CadenceEnrollmentsTable cadenceId={cadenceId} />}
      {tab === "config" && (
        <div className="card p-5 space-y-5">
          <CadenceTriggerConfig
            targetType={cadence.target_type}
            targetStage={cadence.target_stage}
            stagnationDays={cadence.stagnation_days}
            onChange={handleConfigChange}
          />

          <div className="border-t border-[#e5e5dc] pt-5 space-y-4">
            <h3 className="text-[13px] font-semibold uppercase tracking-wider text-[#9ca3af]">Configuracoes de envio</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[12px] text-[#5f6368] block mb-1">Janela inicio (hora)</label>
                <input type="number" value={cadence.send_start_hour} onChange={(e) => handleConfigChange("send_start_hour", Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] block mb-1">Janela fim (hora)</label>
                <input type="number" value={cadence.send_end_hour} onChange={(e) => handleConfigChange("send_end_hour", Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] block mb-1">Cooldown apos resposta (horas)</label>
                <input type="number" value={cadence.cooldown_hours} onChange={(e) => handleConfigChange("cooldown_hours", Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] block mb-1">Max mensagens por lead</label>
                <input type="number" value={cadence.max_messages} onChange={(e) => handleConfigChange("max_messages", Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
              </div>
            </div>
          </div>

          <div className="border-t border-[#e5e5dc] pt-5">
            <h3 className="text-[13px] font-semibold uppercase tracking-wider text-[#9ca3af] mb-3">Nome e descricao</h3>
            <input
              value={cadence.name}
              onChange={(e) => handleConfigChange("name", e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px] mb-3"
            />
            <textarea
              value={cadence.description || ""}
              onChange={(e) => handleConfigChange("description", e.target.value || null)}
              placeholder="Descricao da cadencia..."
              className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px] min-h-[60px]"
            />
          </div>
        </div>
      )}
    </div>
  );
}
