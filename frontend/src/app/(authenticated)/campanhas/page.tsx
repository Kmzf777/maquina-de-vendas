"use client";

import { useState } from "react";
import { useRealtimeBroadcasts } from "@/hooks/use-realtime-broadcasts";
import { useRealtimeCadences } from "@/hooks/use-realtime-cadences";
import { CampaignsDashboard } from "@/components/campaigns/campaigns-dashboard";
import { CampaignsTabs } from "@/components/campaigns/campaigns-tabs";
import { CreateBroadcastModal } from "@/components/campaigns/create-broadcast-modal";

export default function CampanhasPage() {
  const { broadcasts, loading: bLoading } = useRealtimeBroadcasts();
  const { cadences, loading: cLoading } = useRealtimeCadences();
  const [period, setPeriod] = useState("30d");
  const [showBroadcastModal, setShowBroadcastModal] = useState(false);
  const [showCadenceModal, setShowCadenceModal] = useState(false);
  const [cadenceName, setCadenceName] = useState("");
  const [creatingSaving, setCreatingSaving] = useState(false);

  const handleCreateCadence = async () => {
    if (!cadenceName.trim()) return;
    setCreatingSaving(true);
    try {
      const res = await fetch("/api/cadences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: cadenceName.trim() }),
      });
      if (!res.ok) {
        const err = await res.json();
        alert(`Erro ao criar cadencia: ${err.error || res.statusText}`);
        return;
      }
      setCadenceName("");
      setShowCadenceModal(false);
    } catch (e) {
      alert(`Erro de rede: ${e}`);
    } finally {
      setCreatingSaving(false);
    }
  };

  if (bLoading || cLoading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
        <div className="grid grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="card p-4 h-20 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
            Campanhas
          </h1>
          <p className="text-[14px] mt-1" style={{ color: "var(--text-muted)" }}>
            Disparos em massa e cadencias de follow-up
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowBroadcastModal(true)}
            className="px-4 py-2 rounded-xl text-[13px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333] transition-colors"
          >
            + Disparo
          </button>
          <button
            onClick={() => setShowCadenceModal(true)}
            className="px-4 py-2 rounded-xl text-[13px] font-medium bg-[#f6f7ed] text-[#1f1f1f] border border-[#e5e5dc] hover:bg-[#eef0e0] transition-colors"
          >
            + Cadencia
          </button>
        </div>
      </div>

      <CampaignsDashboard period={period} onPeriodChange={setPeriod} />
      <CampaignsTabs broadcasts={broadcasts} cadences={cadences} onRefreshBroadcasts={() => {}} />

      <CreateBroadcastModal
        open={showBroadcastModal}
        onClose={() => setShowBroadcastModal(false)}
        onCreated={() => {}}
      />

      {/* Create Cadence Modal */}
      {showCadenceModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl w-full max-w-md">
            <div className="bg-[#1f1f1f] text-white px-6 py-4 rounded-t-2xl flex items-center justify-between">
              <h2 className="text-[16px] font-semibold">Nova Cadencia</h2>
              <button onClick={() => { setShowCadenceModal(false); setCadenceName(""); }} className="text-[#9ca3af] hover:text-white text-xl">&times;</button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Nome da cadencia</label>
                <input
                  value={cadenceName}
                  onChange={(e) => setCadenceName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreateCadence()}
                  className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
                  placeholder="Ex: Follow-up Atacado"
                  autoFocus
                />
              </div>
              <p className="text-[12px] text-[#9ca3af]">
                Apos criar, voce podera configurar steps, triggers e demais opcoes na pagina de detalhe.
              </p>
            </div>
            <div className="px-6 py-4 border-t border-[#e5e5dc] flex justify-end gap-2">
              <button
                onClick={() => { setShowCadenceModal(false); setCadenceName(""); }}
                className="px-4 py-2 rounded-lg text-[13px] font-medium text-[#5f6368] hover:bg-[#f6f7ed]"
              >
                Cancelar
              </button>
              <button
                onClick={handleCreateCadence}
                disabled={!cadenceName.trim() || creatingSaving}
                className="px-4 py-2 rounded-lg text-[13px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333] disabled:opacity-50"
              >
                {creatingSaving ? "Criando..." : "Criar Cadencia"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
