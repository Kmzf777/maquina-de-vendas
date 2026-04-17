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
        <div className="h-8 w-48 rounded-[4px] animate-pulse bg-[#dedbd6]" />
        <div className="grid grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 h-20 animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111]">
            Campanhas
          </h1>
          <p className="text-[14px] text-[#7b7b78] mt-1">
            Disparos em massa e cadencias de follow-up
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowBroadcastModal(true)}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
          >
            + Disparo
          </button>
          <button
            onClick={() => setShowCadenceModal(true)}
            className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
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
        <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[14px] font-normal text-[#111111]">Nova Cadencia</h2>
              <button onClick={() => { setShowCadenceModal(false); setCadenceName(""); }} className="text-[#7b7b78] hover:text-[#111111] text-xl transition-colors">&times;</button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Nome da cadencia</label>
                <input
                  value={cadenceName}
                  onChange={(e) => setCadenceName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleCreateCadence()}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                  placeholder="Ex: Follow-up Atacado"
                  autoFocus
                />
              </div>
              <p className="text-[12px] text-[#7b7b78]">
                Apos criar, voce podera configurar steps, triggers e demais opcoes na pagina de detalhe.
              </p>
            </div>
            <div className="pt-4 border-t border-[#dedbd6] mt-4 flex justify-end gap-2">
              <button
                onClick={() => { setShowCadenceModal(false); setCadenceName(""); }}
                className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
              >
                Cancelar
              </button>
              <button
                onClick={handleCreateCadence}
                disabled={!cadenceName.trim() || creatingSaving}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
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
