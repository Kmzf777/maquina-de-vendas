"use client";

import { useState } from "react";
import { useRealtimeBroadcasts } from "@/hooks/use-realtime-broadcasts";
import { useRealtimeCadences } from "@/hooks/use-realtime-cadences";
import { CampaignsDashboard } from "@/components/campaigns/campaigns-dashboard";
import { BroadcastList } from "@/components/campaigns/broadcast-list";
import { CadenceList } from "@/components/campaigns/cadence-list";
import { CreateBroadcastModal } from "@/components/campaigns/create-broadcast-modal";

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    draft: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
    running: "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20",
    paused: "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20",
    completed: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20",
    failed: "bg-[#c41c1c]/10 text-[#c41c1c] border-[#c41c1c]/20",
    active: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20",
    archived: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
  };
  const labels: Record<string, string> = {
    draft: "Rascunho", running: "Rodando", paused: "Pausado",
    completed: "Completo", failed: "Falhou", active: "Ativa", archived: "Arquivada",
  };
  return (
    <span className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border flex-shrink-0 ${styles[status] ?? styles.draft}`}>
      {labels[status] ?? status}
    </span>
  );
}

export default function CampanhasPage() {
  const { broadcasts, loading: bLoading } = useRealtimeBroadcasts();
  const { cadences, loading: cLoading } = useRealtimeCadences();
  const [period, setPeriod] = useState("30d");
  const [showBroadcastModal, setShowBroadcastModal] = useState(false);
  const [showCadenceModal, setShowCadenceModal] = useState(false);
  const [cadenceName, setCadenceName] = useState("");
  const [creatingSaving, setCreatingSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<"visao-geral" | "disparos" | "cadencias">("visao-geral");

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
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex items-center justify-between flex-shrink-0">
        <div>
          <h1 style={{ letterSpacing: '-0.96px', lineHeight: '1.00' }} className="text-[32px] font-normal text-[#111111]">
            Campanhas
          </h1>
          <p className="text-[14px] text-[#7b7b78] mt-0.5">Disparos e cadências de follow-up</p>
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

      {/* Tab nav */}
      <div className="border-b border-[#dedbd6] bg-white px-8 flex-shrink-0">
        <div className="flex">
          {(["visao-geral", "disparos", "cadencias"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-3 text-[14px] border-b-2 transition-colors ${
                activeTab === tab
                  ? "border-[#111111] text-[#111111]"
                  : "border-transparent text-[#7b7b78] hover:text-[#111111]"
              }`}
            >
              {tab === "visao-geral" ? "Visão Geral" : tab === "disparos" ? "Disparos" : "Cadências"}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto p-8 bg-[#faf9f6]">
        {activeTab === "visao-geral" && (
          <div className="space-y-6">
            <CampaignsDashboard period={period} onPeriodChange={setPeriod} />

            {/* Mini broadcast list */}
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 style={{ letterSpacing: '-0.3px' }} className="text-[18px] font-medium text-[#111111]">Disparos Recentes</h3>
                <button onClick={() => setActiveTab("disparos")} className="text-[13px] text-[#7b7b78] hover:text-[#111111] transition-colors">
                  Ver todos →
                </button>
              </div>
              <div className="space-y-3">
                {broadcasts.slice(0, 5).map((b) => {
                  const pct = b.total_leads > 0 ? Math.round((b.sent / b.total_leads) * 100) : 0;
                  const fillColor = b.status === "completed" ? "#0bdf50" : b.status === "running" ? "#ff5600" : "#dedbd6";
                  return (
                    <div key={b.id} className="flex items-center gap-4">
                      <StatusBadge status={b.status} />
                      <span className="text-[14px] text-[#111111] flex-1 truncate">{b.name}</span>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <div className="w-24 h-1.5 bg-[#f0ede8] rounded-full overflow-hidden">
                          <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: fillColor }} />
                        </div>
                        <span className="text-[12px] text-[#7b7b78] w-8 text-right">{pct}%</span>
                      </div>
                    </div>
                  );
                })}
                {broadcasts.length === 0 && (
                  <p className="text-[14px] text-[#7b7b78] py-4 text-center">Nenhum disparo ainda</p>
                )}
              </div>
            </div>

            {/* Mini cadence list */}
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 style={{ letterSpacing: '-0.3px' }} className="text-[18px] font-medium text-[#111111]">Cadências Ativas</h3>
                <button onClick={() => setActiveTab("cadencias")} className="text-[13px] text-[#7b7b78] hover:text-[#111111] transition-colors">
                  Ver todas →
                </button>
              </div>
              <div className="space-y-3">
                {cadences.slice(0, 3).map((c) => (
                  <div key={c.id} className="flex items-center justify-between">
                    <StatusBadge status={c.status} />
                    <span className="text-[14px] text-[#111111] flex-1 mx-3 truncate">{c.name}</span>
                    <span className="text-[12px] text-[#7b7b78]">{c.target_type}</span>
                  </div>
                ))}
                {cadences.length === 0 && (
                  <p className="text-[14px] text-[#7b7b78] py-4 text-center">Nenhuma cadência ainda</p>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === "disparos" && <BroadcastList broadcasts={broadcasts} onRefresh={() => {}} />}
        {activeTab === "cadencias" && <CadenceList cadences={cadences} />}
      </div>

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
