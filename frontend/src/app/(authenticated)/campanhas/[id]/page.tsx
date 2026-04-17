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
    return <div className="h-8 w-48 rounded-[4px] animate-pulse bg-[#dedbd6]" />;
  }

  const statusBadge = cadence.status === "active"
    ? "bg-[#0bdf50]/10 text-[#0bdf50] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border border-[#0bdf50]/20"
    : "bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]";

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111]">{cadence.name}</h1>
          {cadence.description && <p className="text-[14px] text-[#7b7b78] mt-1">{cadence.description}</p>}
        </div>
        <div className="flex items-center gap-3">
          <span className={statusBadge}>
            {cadence.status === "active" ? "Ativa" : cadence.status === "paused" ? "Pausada" : "Arquivada"}
          </span>
          <button
            onClick={handleToggleStatus}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
          >
            {cadence.status === "active" ? "Pausar" : "Ativar"}
          </button>
        </div>
      </div>

      {/* Config summary bar */}
      <div className="flex gap-3 mb-6">
        <span className="bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-3 py-1.5 rounded-[4px]">
          Janela: {cadence.send_start_hour}h-{cadence.send_end_hour}h
        </span>
        <span className="bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-3 py-1.5 rounded-[4px]">
          Cooldown: {cadence.cooldown_hours}h
        </span>
        <span className="bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-3 py-1.5 rounded-[4px]">
          Max: {cadence.max_messages} msgs
        </span>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[#dedbd6] mb-5">
        {(["steps", "leads", "config"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={tab === t
              ? "border-b-2 border-[#111111] text-[#111111] px-4 py-2 text-[14px] font-normal"
              : "border-b-2 border-transparent text-[#7b7b78] px-4 py-2 text-[14px] font-normal hover:text-[#111111] transition-colors"}
          >
            {t === "steps" ? "Steps" : t === "leads" ? "Leads" : "Configuracao"}
          </button>
        ))}
      </div>

      {tab === "steps" && <CadenceStepsTable cadenceId={cadenceId} />}
      {tab === "leads" && <CadenceEnrollmentsTable cadenceId={cadenceId} />}
      {tab === "config" && (
        <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-5 space-y-5">
          <CadenceTriggerConfig
            targetType={cadence.target_type}
            targetStage={cadence.target_stage}
            stagnationDays={cadence.stagnation_days}
            onChange={handleConfigChange}
          />

          <div className="border-t border-[#dedbd6] pt-5 space-y-4">
            <h3 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Configuracoes de envio</h3>
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
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Cooldown apos resposta (horas)</label>
                <input type="number" value={cadence.cooldown_hours} onChange={(e) => handleConfigChange("cooldown_hours", Number(e.target.value))} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Max mensagens por lead</label>
                <input type="number" value={cadence.max_messages} onChange={(e) => handleConfigChange("max_messages", Number(e.target.value))} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
              </div>
            </div>
          </div>

          <div className="border-t border-[#dedbd6] pt-5">
            <h3 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Nome e descricao</h3>
            <input
              value={cadence.name}
              onChange={(e) => handleConfigChange("name", e.target.value)}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full mb-3"
            />
            <textarea
              value={cadence.description || ""}
              onChange={(e) => handleConfigChange("description", e.target.value || null)}
              placeholder="Descricao da cadencia..."
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full min-h-[60px]"
            />
          </div>
        </div>
      )}
    </div>
  );
}
