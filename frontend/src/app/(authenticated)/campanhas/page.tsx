"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useRealtimeBroadcasts } from "@/hooks/use-realtime-broadcasts";
import { useRealtimeCampaigns } from "@/hooks/use-realtime-campaigns";
import { CampaignsDashboard } from "@/components/campaigns/campaigns-dashboard";
import { BroadcastList } from "@/components/campaigns/broadcast-list";
import { CadenceList } from "@/components/campaigns/cadence-list";
import { CreateBroadcastModal } from "@/components/campaigns/create-broadcast-modal";
import { QuickSendModal } from "@/components/campaigns/quick-send-modal";
import { TemplatesTab } from "@/components/campaigns/templates-tab";

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

const VALID_TABS = ["visao-geral", "disparos", "cadencias", "templates"] as const;
type TabId = typeof VALID_TABS[number];

function CampanhasPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const { broadcasts, loading: bLoading } = useRealtimeBroadcasts();
  const { campaigns, loading: cLoading } = useRealtimeCampaigns();
  const [period, setPeriod] = useState("30d");
  const [showBroadcastModal, setShowBroadcastModal] = useState(false);
  const [showCadenceModal, setShowCadenceModal] = useState(false);
  const [showQuickSendModal, setShowQuickSendModal] = useState(false);
  const [quickSendToast, setQuickSendToast] = useState<string | null>(null);
  const [cadenceName, setCadenceName] = useState("");
  const [channelId, setChannelId] = useState("");
  const [channels, setChannels] = useState<{ id: string; name: string; is_active: boolean; provider: string }[]>([]);
  const [priority, setPriority] = useState(5);
  const [frequencyCap, setFrequencyCap] = useState(1);
  const [creatingSaving, setCreatingSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>("visao-geral");
  // Load connected channels once on mount
  useEffect(() => {
    fetch("/api/channels")
      .then(r => r.json())
      .then((data: { id: string; name: string; is_active: boolean; provider: string }[]) => {
        setChannels(Array.isArray(data) ? data.filter(c => c.is_active) : []);
      })
      .catch(() => {});
  }, []);

  // Read ?tab= query param on mount / change
  useEffect(() => {
    const tab = searchParams.get("tab") as TabId | null;
    if (tab && (VALID_TABS as readonly string[]).includes(tab)) {
      setActiveTab(tab);
    }
  }, [searchParams]);

  const handleCreateCadence = async () => {
    if (!cadenceName.trim() || !channelId) return;
    setCreatingSaving(true);
    try {
      const res = await fetch("/api/campaigns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: cadenceName.trim(), priority, frequency_cap: frequencyCap, channel_id: channelId || null }),
      });
      if (!res.ok) {
        const err = await res.json();
        alert(`Erro ao criar cadência: ${err.error || res.statusText}`);
        return;
      }
      const camp = await res.json();
      setCadenceName("");
      setChannelId("");
      setShowCadenceModal(false);
      router.push(`/campanhas/cadencias/${camp.id}`);
    } catch (e) {
      alert(`Erro de rede: ${e}`);
    } finally {
      setCreatingSaving(false);
    }
  };

  const handleQuickSendSuccess = (count: number) => {
    setQuickSendToast(`Disparo Rápido enviado para ${count} número${count > 1 ? "s" : ""}!`);
    setTimeout(() => setQuickSendToast(null), 10000);
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
            onClick={() => setShowQuickSendModal(true)}
            className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
          >
            + Disparo Rápido
          </button>
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
          {(VALID_TABS).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-3 text-[14px] border-b-2 transition-colors ${
                activeTab === tab
                  ? "border-[#111111] text-[#111111]"
                  : "border-transparent text-[#7b7b78] hover:text-[#111111]"
              }`}
            >
              {tab === "visao-geral" ? "Visão Geral"
                : tab === "disparos" ? "Disparos"
                : tab === "cadencias" ? "Cadências"
                : "Templates"}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto px-4 md:px-8 py-4 md:py-8 bg-[#faf9f6]">
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
                    <div
                      key={b.id}
                      className="flex items-center gap-4 cursor-pointer hover:opacity-80 transition-opacity"
                      onClick={() => router.push(`/campanhas/disparos/${b.id}`)}
                    >
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
                {campaigns.slice(0, 3).map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center justify-between cursor-pointer hover:opacity-80 transition-opacity"
                    onClick={() => router.push(`/campanhas/cadencias/${c.id}`)}
                  >
                    <StatusBadge status={c.status} />
                    <span className="text-[14px] text-[#111111] flex-1 mx-3 truncate">{c.name}</span>
                    <span className="text-[12px] text-[#7b7b78]">{c.nodes?.length ?? 0} nós</span>
                  </div>
                ))}
                {campaigns.length === 0 && (
                  <p className="text-[14px] text-[#7b7b78] py-4 text-center">Nenhuma cadência ainda</p>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === "disparos" && <BroadcastList broadcasts={broadcasts} onRefresh={() => {}} />}
        {activeTab === "cadencias" && <CadenceList campaigns={campaigns} onRefresh={() => {}} />}
        {activeTab === "templates" && <TemplatesTab />}
      </div>

      <CreateBroadcastModal
        open={showBroadcastModal}
        onClose={() => setShowBroadcastModal(false)}
        onCreated={() => {}}
      />

      <QuickSendModal
        open={showQuickSendModal}
        onClose={() => setShowQuickSendModal(false)}
        onSuccess={handleQuickSendSuccess}
      />

      {quickSendToast && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#111111] text-white text-[14px] px-4 py-3 rounded-[6px] shadow-lg flex items-center gap-3">
          <span>{quickSendToast}</span>
          <button
            onClick={() => setQuickSendToast(null)}
            className="text-white/60 hover:text-white transition-colors leading-none text-lg"
          >
            &times;
          </button>
        </div>
      )}

      {/* Create Cadence Modal */}
      {showCadenceModal && (
        <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[14px] font-normal text-[#111111]">Nova Cadencia</h2>
              <button onClick={() => { setShowCadenceModal(false); setCadenceName(""); setChannelId(""); setPriority(5); setFrequencyCap(1); }} className="text-[#7b7b78] hover:text-[#111111] text-xl transition-colors">&times;</button>
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
              {/* Canal padrão */}
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                  Canal padrão <span className="text-red-500">*</span>
                </label>
                <select
                  value={channelId}
                  onChange={(e) => setChannelId(e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  <option value="">— Selecione um canal —</option>
                  {channels.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
                {channels.length === 0 && (
                  <p className="text-[11px] text-[#7b7b78] mt-1">Nenhum canal conectado encontrado</p>
                )}
              </div>

              {/* Priority */}
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                  Prioridade (1 = baixa · 10 = alta)
                </label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={priority}
                  onChange={(e) => setPriority(Number(e.target.value))}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                />
              </div>

              {/* Frequency cap */}
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                  Máx. mensagens por lead por dia
                </label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={frequencyCap}
                  onChange={(e) => setFrequencyCap(Number(e.target.value))}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                />
              </div>

              <p className="text-[12px] text-[#7b7b78]">
                Apos criar, voce podera configurar steps, triggers e demais opcoes na pagina de detalhe.
              </p>
            </div>
            <div className="pt-4 border-t border-[#dedbd6] mt-4 flex justify-end gap-2">
              <button
                onClick={() => { setShowCadenceModal(false); setCadenceName(""); setChannelId(""); setPriority(5); setFrequencyCap(1); }}
                className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
              >
                Cancelar
              </button>
              <button
                onClick={handleCreateCadence}
                disabled={!cadenceName.trim() || !channelId || creatingSaving}
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

export default function CampanhasPage() {
  return (
    <Suspense>
      <CampanhasPageInner />
    </Suspense>
  );
}
