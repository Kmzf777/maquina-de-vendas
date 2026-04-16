"use client";

import { useState, useEffect } from "react";
import type { Channel, Cadence, TemplatePreset, AgentProfile } from "@/lib/types";
import { LeadSelector } from "@/components/lead-selector";

interface CreateBroadcastModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function CreateBroadcastModal({ open, onClose, onCreated }: CreateBroadcastModalProps) {
  const [step, setStep] = useState(1);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [cadences, setCadences] = useState<Cadence[]>([]);
  const [presets, setPresets] = useState<TemplatePreset[]>([]);
  const [agentProfiles, setAgentProfiles] = useState<AgentProfile[]>([]);
  const [saving, setSaving] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [channelId, setChannelId] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [templateVars, setTemplateVars] = useState<Record<string, string>>({});
  const [presetId, setPresetId] = useState("");
  const [cadenceId, setCadenceId] = useState("");
  const [agentProfileId, setAgentProfileId] = useState("");
  const [intervalMin, setIntervalMin] = useState(3);
  const [intervalMax, setIntervalMax] = useState(8);

  // Leads
  const [selectedLeadIds, setSelectedLeadIds] = useState<Set<string>>(new Set());
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [leadTab, setLeadTab] = useState<"crm" | "csv">("crm");

  useEffect(() => {
    if (!open) return;
    fetch("/api/channels").then((r) => r.json()).then((d) => {
      const metaChannels = (d.data || d).filter((c: Channel) => c.provider === "meta_cloud" && c.is_active);
      setChannels(metaChannels);
    });
    fetch("/api/cadences").then((r) => r.json()).then((d) => {
      setCadences((d.data || d).filter((c: Cadence) => c.status === "active"));
    });
    fetch("/api/template-presets").then((r) => r.json()).then((d) => setPresets(Array.isArray(d) ? d : d.data || []));
    fetch("/api/agent-profiles").then((r) => r.json()).then((d) => setAgentProfiles(Array.isArray(d) ? d : d.data || []));
  }, [open]);

  const handlePresetSelect = (id: string) => {
    setPresetId(id);
    const preset = presets.find((p) => p.id === id);
    if (preset) {
      setTemplateName(preset.template_name);
      setTemplateVars(preset.variables as Record<string, string>);
    }
  };

  const handleCreate = async () => {
    setSaving(true);
    try {
      const res = await fetch("/api/broadcasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          channel_id: channelId || null,
          template_name: templateName,
          template_preset_id: presetId || null,
          template_variables: templateVars,
          cadence_id: cadenceId || null,
          agent_profile_id: agentProfileId || null,
          send_interval_min: intervalMin,
          send_interval_max: intervalMax,
        }),
      });
      const broadcast = await res.json();

      if (leadTab === "crm" && selectedLeadIds.size) {
        await fetch(`/api/broadcasts/${broadcast.id}/leads`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lead_ids: [...selectedLeadIds] }),
        });
      } else if (leadTab === "csv" && csvFile) {
        const formData = new FormData();
        formData.append("file", csvFile);
        const fastApiUrl = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";
        await fetch(`${fastApiUrl}/api/broadcasts/${broadcast.id}/import`, {
          method: "POST",
          body: formData,
        });
      }

      onCreated();
      onClose();
      resetForm();
    } finally {
      setSaving(false);
    }
  };

  const resetForm = () => {
    setStep(1);
    setName("");
    setChannelId("");
    setTemplateName("");
    setTemplateVars({});
    setPresetId("");
    setCadenceId("");
    setAgentProfileId("");
    setSelectedLeadIds(new Set());
    setCsvFile(null);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto">
        <div className="bg-[#1f1f1f] text-white px-6 py-4 rounded-t-2xl flex items-center justify-between">
          <h2 className="text-[16px] font-semibold">Novo Disparo — Passo {step}/3</h2>
          <button onClick={() => { onClose(); resetForm(); }} className="text-[#9ca3af] hover:text-white text-xl">&times;</button>
        </div>

        <div className="p-6 space-y-4">
          {step === 1 && (
            <>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Nome do disparo</label>
                <input value={name} onChange={(e) => setName(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" placeholder="Ex: Promo Black Friday" />
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Canal (Meta Cloud)</label>
                <select value={channelId} onChange={(e) => setChannelId(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]">
                  <option value="">Selecionar canal...</option>
                  {channels.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.phone})</option>)}
                </select>
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Preset (opcional)</label>
                <select value={presetId} onChange={(e) => handlePresetSelect(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]">
                  <option value="">Nenhum preset</option>
                  {presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Template</label>
                <input value={templateName} onChange={(e) => setTemplateName(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" placeholder="Nome do template na Meta" />
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Cadencia vinculada (opcional)</label>
                <select value={cadenceId} onChange={(e) => setCadenceId(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]">
                  <option value="">Sem cadencia</option>
                  {cadences.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">
                  Agente
                </label>
                <select
                  value={agentProfileId}
                  onChange={(e) => setAgentProfileId(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
                >
                  <option value="">Agente padrão do canal</option>
                  {agentProfiles.map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Intervalo min (s)</label>
                  <input type="number" value={intervalMin} onChange={(e) => setIntervalMin(Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
                </div>
                <div>
                  <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Intervalo max (s)</label>
                  <input type="number" value={intervalMax} onChange={(e) => setIntervalMax(Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
                </div>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <div className="flex gap-2 mb-4">
                <button onClick={() => setLeadTab("crm")} className={`px-3 py-1.5 rounded-lg text-[12px] font-medium ${leadTab === "crm" ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] bg-[#f4f4f0]"}`}>
                  Do CRM
                </button>
                <button onClick={() => setLeadTab("csv")} className={`px-3 py-1.5 rounded-lg text-[12px] font-medium ${leadTab === "csv" ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] bg-[#f4f4f0]"}`}>
                  Importar CSV
                </button>
              </div>

              {leadTab === "crm" ? (
                <LeadSelector selectedIds={selectedLeadIds} onSelectionChange={setSelectedLeadIds} />
              ) : (
                <div className="border-2 border-dashed border-[#e5e5dc] rounded-xl p-8 text-center">
                  <input type="file" accept=".csv" onChange={(e) => setCsvFile(e.target.files?.[0] || null)} className="text-[13px]" />
                  {csvFile && <p className="text-[12px] text-[#2d6a3f] mt-2">Arquivo: {csvFile.name}</p>}
                </div>
              )}
              <p className="text-[12px] text-[#5f6368]">
                {leadTab === "crm" ? `${selectedLeadIds.size} leads selecionados` : csvFile ? "CSV pronto para envio" : "Nenhum arquivo selecionado"}
              </p>
            </>
          )}

          {step === 3 && (
            <div className="space-y-3">
              <h3 className="text-[14px] font-semibold text-[#1f1f1f]">Revisao do disparo</h3>
              <div className="bg-[#f6f7ed] rounded-xl p-4 space-y-2 text-[13px]">
                <p><span className="text-[#5f6368]">Nome:</span> <strong>{name}</strong></p>
                <p><span className="text-[#5f6368]">Template:</span> <strong>{templateName}</strong></p>
                <p><span className="text-[#5f6368]">Leads:</span> <strong>{leadTab === "crm" ? selectedLeadIds.size : "CSV"}</strong></p>
                <p><span className="text-[#5f6368]">Intervalo:</span> <strong>{intervalMin}-{intervalMax}s</strong></p>
                {cadenceId && <p><span className="text-[#5f6368]">Cadencia:</span> <strong>{cadences.find((c) => c.id === cadenceId)?.name}</strong></p>}
                {agentProfileId && (
                  <p>
                    <span className="text-[#5f6368]">Agente:</span>{" "}
                    <strong>{agentProfiles.find((a) => a.id === agentProfileId)?.name}</strong>
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-[#e5e5dc] flex justify-between">
          {step > 1 ? (
            <button onClick={() => setStep(step - 1)} className="px-4 py-2 rounded-lg text-[13px] font-medium text-[#5f6368] hover:bg-[#f6f7ed]">
              Voltar
            </button>
          ) : <div />}
          {step < 3 ? (
            <button
              onClick={() => setStep(step + 1)}
              disabled={step === 1 && (!name || !templateName)}
              className="px-4 py-2 rounded-lg text-[13px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333] disabled:opacity-50"
            >
              Proximo
            </button>
          ) : (
            <button onClick={handleCreate} disabled={saving} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333] disabled:opacity-50">
              {saving ? "Criando..." : "Criar Disparo"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
